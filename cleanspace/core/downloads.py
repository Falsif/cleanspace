"""Менеджер папки «Загрузки»: обзор, старые установщики, архивы, повторные загрузки,
план сортировки по папкам (только предложение — выполняется после подтверждения)."""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .cleaner import FileItem
from .duplicates import full_hash
from .scanner import ScanControl
from .utils import CATEGORIES, category_of, known_folder, norm

SORT_FOLDERS = {
    "video": "Видео", "image": "Изображения", "audio": "Музыка", "document": "Документы",
    "archive": "Архивы", "installer": "Установщики", "other": "Разное",
}

# «file (1).zip», «file(2).zip», «file - копия.zip», «file - Copy (3).zip»
_REDOWNLOAD_RE = re.compile(
    r"^(?P<base>.+?)(?:\s?\(\d{1,3}\)|\s-\s(?:копия|copy)(?:\s\(\d{1,3}\))?)$", re.IGNORECASE)


@dataclass
class DownloadEntry:
    item: FileItem
    category: str
    is_dir: bool = False


@dataclass
class DownloadsReport:
    folder: str
    files: list[DownloadEntry] = field(default_factory=list)
    old_installers: list[FileItem] = field(default_factory=list)
    archives: list[FileItem] = field(default_factory=list)
    redownloads: list[tuple[str, list[FileItem], bool]] = field(default_factory=list)
    # (базовое имя, файлы, содержимое идентично)
    errors: int = 0

    @property
    def total_size(self) -> int:
        return sum(e.item.size for e in self.files)

    def by_category(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for e in self.files:
            out[e.category][0] += e.item.size
            out[e.category][1] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}


def downloads_folder() -> str:
    return str(known_folder("downloads"))


def base_name(name: str) -> str:
    stem, ext = os.path.splitext(name)
    m = _REDOWNLOAD_RE.match(stem)
    return ((m.group("base") if m else stem).strip() + ext).lower()


def scan_downloads(folder: str, control: ScanControl, installer_age_days: int = 30) -> DownloadsReport:
    """Анализирует только верхний уровень папки «Загрузки» (вложенные папки не трогаем)."""
    rep = DownloadsReport(folder)
    if not os.path.isdir(folder):
        return rep
    cutoff = time.time() - installer_age_days * 86400
    groups: dict[str, list[FileItem]] = defaultdict(list)
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if control.cancelled:
                    break
                try:
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    rep.errors += 1
                    continue
                name = entry.name
                if name.lower() in ("desktop.ini", "thumbs.db") or name.lower().endswith(
                        (".crdownload", ".part", ".partial", ".tmp", ".opdownload")):
                    continue  # незавершённые загрузки и служебные файлы не трогаем
                item = FileItem(entry.path, st.st_size, st.st_mtime)
                cat = category_of(name)
                rep.files.append(DownloadEntry(item, cat))
                if cat == "installer" and st.st_mtime < cutoff:
                    rep.old_installers.append(item)
                if cat == "archive":
                    rep.archives.append(item)
                groups[base_name(name)].append(item)
    except OSError:
        rep.errors += 1
    rep.files.sort(key=lambda e: e.item.size, reverse=True)
    for base, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda f: f.mtime)
        identical = False
        if len({i.size for i in items}) == 1:
            try:
                identical = len({full_hash(i.path, control) for i in items}) == 1
            except Exception:
                identical = False
        rep.redownloads.append((base, items, identical))
    rep.redownloads.sort(key=lambda r: sum(i.size for i in r[1]), reverse=True)
    return rep


def sort_plan(report: DownloadsReport, target_root: str | None = None,
              categories: set[str] | None = None) -> list[tuple[FileItem, str]]:
    """Предлагаемый план: файл -> подпапка по типу. Ничего не выполняет."""
    root = target_root or report.folder
    plan = []
    for e in report.files:
        if categories is not None and e.category not in categories:
            continue
        dest = os.path.join(root, SORT_FOLDERS.get(e.category, "Разное"))
        if norm(os.path.dirname(e.item.path)) == norm(dest):
            continue
        plan.append((e.item, dest))
    return plan


def category_title(key: str) -> str:
    return CATEGORIES.get(key, CATEGORIES["other"])[0]
