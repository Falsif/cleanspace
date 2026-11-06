"""Анализ дисков: дерево папок с размерами, категории файлов, данные для Treemap.

Для экономии памяти в узле хранится только имя (полный путь собирается по
цепочке родителей), а из файлов каждой папки запоминаются только самые крупные
(TOP_FILES_PER_DIR); остальные объединяются в «Остальные файлы».
"""
from __future__ import annotations

import heapq
import os
import stat as stat_mod
import time
from dataclasses import dataclass, field

from .scanner import Exclusions, ScanControl, ScanStats, _is_link, scan_priority
from .utils import CATEGORY_ORDER, category_of, norm

TOP_FILES_PER_DIR = 40


class DirNode:
    __slots__ = ("name", "parent", "children", "own_size", "size", "files", "total_files",
                 "top_files", "other_size", "other_count", "error", "mtime")

    def __init__(self, name: str, parent: "DirNode | None" = None):
        self.name = name
        self.parent = parent
        self.children: list[DirNode] = []
        self.own_size = 0          # файлы прямо в этой папке
        self.size = 0              # всего вместе с подпапками
        self.files = 0             # файлов прямо в папке
        self.total_files = 0       # всего файлов с подпапками
        self.top_files: list[tuple[int, str, float]] = []  # мин-куча (размер, имя, mtime)
        self.other_size = 0
        self.other_count = 0
        self.error = False         # не удалось прочитать содержимое
        self.mtime = 0.0

    @property
    def path(self) -> str:
        parts = []
        node: DirNode | None = self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        parts.reverse()
        return os.path.join(*parts) if parts else ""

    def add_file(self, name: str, size: int, mtime: float) -> None:
        self.own_size += size
        self.files += 1
        item = (size, name, mtime)
        if len(self.top_files) < TOP_FILES_PER_DIR:
            heapq.heappush(self.top_files, item)
        else:
            smallest = heapq.heappushpop(self.top_files, item)
            self.other_size += smallest[0]
            self.other_count += 1

    def sorted_children(self) -> list["DirNode"]:
        return sorted(self.children, key=lambda n: n.size, reverse=True)

    def sorted_files(self) -> list[tuple[int, str, float]]:
        return sorted(self.top_files, reverse=True)


@dataclass
class AnalysisResult:
    root: DirNode
    stats: ScanStats
    categories: dict[str, list[int]] = field(default_factory=dict)  # ключ -> [байт, файлов]
    duration: float = 0.0
    disk_used: int | None = None  # если анализировался корень диска — занято на диске

    @property
    def complete(self) -> bool:
        return self.stats.complete

    def coverage_note(self) -> str:
        """Честное пояснение полноты анализа."""
        notes = []
        if self.stats.cancelled:
            notes.append("Сканирование остановлено — данные неполные.")
        if self.stats.errors:
            notes.append(f"Нет доступа к {self.stats.errors} папкам/файлам — их размер не учтён.")
        if self.stats.skipped_excluded:
            notes.append(f"Пропущено исключений: {self.stats.skipped_excluded}.")
        if self.stats.skipped_links:
            notes.append(f"Ссылок и точек соединения не учтено: {self.stats.skipped_links} "
                         "(чтобы не считать данные дважды).")
        if self.disk_used:
            pct = min(100.0, self.root.size / self.disk_used * 100) if self.disk_used else 0
            notes.append(f"Учтено {pct:.0f}% занятого на диске места. Остальное — системные "
                         "области, недоступные без прав администратора (файл подкачки, "
                         "теневые копии, служебные данные NTFS).")
        return " ".join(notes)


def analyze(root_path: str, control: ScanControl, exclusions: Exclusions | None = None,
            disk_used: int | None = None) -> AnalysisResult:
    exclusions = exclusions or Exclusions()
    start = time.monotonic()
    root_real = os.path.realpath(root_path)
    root = DirNode(root_real)
    stats = ScanStats()
    cats: dict[str, list[int]] = {k: [0, 0] for k in CATEGORY_ORDER}
    pause = 300 if control.economy else 0
    counter = 0
    stack: list[DirNode] = [root]
    with scan_priority(control.economy):
        while stack:
            if control.cancelled:
                stats.cancelled = True
                break
            node = stack.pop()
            path = node.path
            stats.dirs += 1
            control.report(path, stats.files, stats.bytes)
            try:
                it = os.scandir(path)
            except OSError as exc:
                node.error = True
                stats.add_error(path, exc)
                continue
            with it:
                while True:
                    try:
                        entry = next(it)
                    except StopIteration:
                        break
                    except OSError as exc:
                        node.error = True
                        stats.add_error(path, exc)
                        break
                    if pause:
                        counter += 1
                        if counter % pause == 0:
                            time.sleep(0.004)
                    if control.cancelled:
                        break
                    try:
                        if _is_link(entry):
                            stats.skipped_links += 1
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if exclusions and exclusions.matches(norm(entry.path)):
                                stats.skipped_excluded += 1
                                continue
                            child = DirNode(entry.name, node)
                            node.children.append(child)
                            stack.append(child)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if exclusions and exclusions.matches(norm(entry.path)):
                            stats.skipped_excluded += 1
                            continue
                        st = entry.stat(follow_symlinks=False)
                        if not stat_mod.S_ISREG(st.st_mode):
                            continue
                        size = st.st_size
                        node.add_file(entry.name, size, st.st_mtime)
                        stats.files += 1
                        stats.bytes += size
                        c = cats[category_of(entry.name)]
                        c[0] += size
                        c[1] += 1
                    except OSError as exc:
                        stats.add_error(entry.path, exc)
    _aggregate(root)
    control.report("", stats.files, stats.bytes, force=True)
    return AnalysisResult(root, stats, cats, time.monotonic() - start, disk_used)


def _aggregate(root: DirNode) -> None:
    """Подсчёт итоговых размеров снизу вверх (без рекурсии — глубина папок не ограничена)."""
    order: list[DirNode] = []
    stack = [root]
    while stack:
        n = stack.pop()
        order.append(n)
        stack.extend(n.children)
    for n in reversed(order):
        n.size = n.own_size + sum(c.size for c in n.children)
        n.total_files = n.files + sum(c.total_files for c in n.children)


def treemap_items(node: DirNode, limit: int = 60) -> list[dict]:
    """Элементы для Treemap текущей папки: подпапки + крупные файлы + «Остальные»."""
    items: list[dict] = []
    for c in node.children:
        if c.size > 0:
            items.append({"name": c.name, "size": c.size, "kind": "dir", "node": c,
                          "category": None})
    for size, name, mtime in node.top_files:
        if size > 0:
            items.append({"name": name, "size": size, "kind": "file", "node": node,
                          "category": category_of(name), "mtime": mtime})
    items.sort(key=lambda d: d["size"], reverse=True)
    rest = items[limit:]
    items = items[:limit]
    rest_size = sum(i["size"] for i in rest) + node.other_size
    if rest_size > 0:
        items.append({"name": "Остальное", "size": rest_size, "kind": "rest", "node": node,
                      "category": "other"})
    return items


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple]:
    """Алгоритм squarified treemap. values — по убыванию. Возвращает [(x, y, w, h), ...]."""
    total = sum(values)
    if total <= 0 or w <= 0 or h <= 0:
        return [(x, y, 0, 0) for _ in values]
    scale = w * h / total
    areas = [v * scale for v in values]
    rects: list[tuple] = []

    def worst(row: list[float], side: float) -> float:
        s = sum(row)
        if s == 0 or side == 0:
            return float("inf")
        return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) for r in row if r > 0) \
            if any(r > 0 for r in row) else float("inf")

    i = 0
    while i < len(areas):
        side = min(w, h)
        row = [areas[i]]
        i += 1
        while i < len(areas) and worst(row + [areas[i]], side) <= worst(row, side):
            row.append(areas[i])
            i += 1
        s = sum(row)
        if w >= h:  # раскладываем столбцом слева
            col_w = s / h if h else 0
            yy = y
            for a in row:
                rh = a / col_w if col_w else 0
                rects.append((x, yy, col_w, rh))
                yy += rh
            x += col_w
            w -= col_w
        else:       # строкой сверху
            row_h = s / w if w else 0
            xx = x
            for a in row:
                rw = a / row_h if row_h else 0
                rects.append((xx, y, rw, row_h))
                xx += rw
            y += row_h
            h -= row_h
    return rects
