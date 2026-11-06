"""Поиск дубликатов по содержимому.

Алгоритм:
1. группировка по размеру (файлы уникального размера сразу отбрасываются);
2. быстрый предварительный хеш: SHA-256 от первых и последних 64 КБ;
3. полный SHA-256 только для совпавших кандидатов;
4. в результат попадают только наборы с полностью совпавшим SHA-256.
Одинаковые имена НЕ считаются признаком дубликата.
Файлы OneDrive «только в облаке» не читаются (иначе Windows начнёт их скачивать).
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field

from . import protection
from .cleaner import FileItem, OperationResult, recycle_files, verify_unchanged
from .scanner import Exclusions, ScanCancelled, ScanControl, ScanStats, scan_priority, walk

QUICK_CHUNK = 64 * 1024
FULL_CHUNK = 1024 * 1024


@dataclass
class DuplicateGroup:
    sha256: str
    size: int
    files: list[FileItem]

    @property
    def copies(self) -> int:
        return len(self.files)

    @property
    def wasted(self) -> int:
        """Сколько места займёт освобождение всех копий, кроме одной."""
        return self.size * (len(self.files) - 1)


@dataclass
class DuplicateResult:
    groups: list[DuplicateGroup] = field(default_factory=list)
    stats: ScanStats = field(default_factory=ScanStats)
    hashed_files: int = 0
    hash_errors: int = 0
    skipped_cloud: int = 0

    @property
    def wasted(self) -> int:
        return sum(g.wasted for g in self.groups)


def quick_hash(path: str, size: int) -> str:
    h = hashlib.sha256()
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(QUICK_CHUNK))
        if size > QUICK_CHUNK * 2:
            f.seek(-QUICK_CHUNK, os.SEEK_END)
            h.update(f.read(QUICK_CHUNK))
    return h.hexdigest()


def full_hash(path: str, control: ScanControl | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if control is not None and control.cancelled:
                raise ScanCancelled()
            chunk = f.read(FULL_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def find_duplicates(roots: list[str], control: ScanControl,
                    exclusions: Exclusions | None = None, min_size: int = 1024,
                    max_groups: int = 5000) -> DuplicateResult:
    res = DuplicateResult()
    by_size: dict[int, list[FileItem]] = defaultdict(list)
    seen: set[str] = set()
    with scan_priority(control.economy):
        # Этап 1: размеры
        for fe in walk(roots, control, res.stats, exclusions):
            if fe.size < max(1, min_size):
                continue
            if fe.cloud_only:
                res.skipped_cloud += 1
                continue
            key = os.path.normcase(fe.path)
            if key in seen:      # одинаковые корни/вложенные папки — без двойного учёта
                continue
            seen.add(key)
            by_size[fe.size].append(FileItem(fe.path, fe.size, fe.mtime))
        seen.clear()
        if control.cancelled:
            return res
        candidates = {s: items for s, items in by_size.items() if len(items) > 1}
        by_size.clear()
        total = sum(len(v) for v in candidates.values())
        done = 0
        # Этапы 2–3: быстрый и полный хеш
        try:
            for size in sorted(candidates, reverse=True):
                items = candidates[size]
                quick: dict[str, list[FileItem]] = defaultdict(list)
                for item in items:
                    control.check()
                    done += 1
                    control.report(f"Быстрая проверка: {item.path}", done, total)
                    try:
                        quick[quick_hash(item.path, size)].append(item)
                    except OSError:
                        res.hash_errors += 1
                for qitems in quick.values():
                    if len(qitems) < 2:
                        continue
                    full: dict[str, list[FileItem]] = defaultdict(list)
                    for item in qitems:
                        control.check()
                        control.report(f"SHA-256: {item.path}", done, total)
                        try:
                            digest = full_hash(item.path, control)
                            full[digest].append(item)
                            res.hashed_files += 1
                        except OSError:
                            res.hash_errors += 1
                    for digest, same in full.items():
                        if len(same) > 1:
                            same.sort(key=lambda f: f.mtime)
                            res.groups.append(DuplicateGroup(digest, size, same))
                            if len(res.groups) >= max_groups:
                                raise _Enough()
        except ScanCancelled:
            res.stats.cancelled = True
        except _Enough:
            pass
    res.groups.sort(key=lambda g: g.wasted, reverse=True)
    return res


class _Enough(Exception):
    pass


def auto_select(group: DuplicateGroup) -> list[FileItem]:
    """Предложение, какие копии можно убрать: всё, кроме самой старой (оригинала).

    Автоматически отмечаются только файлы из личных папок пользователя;
    файлы из системных, программных и неизвестных мест не отмечаются никогда.
    Хотя бы одна копия всегда остаётся.
    """
    if len(group.files) < 2:
        return []
    keep = group.files[0]  # самая старая
    picked = [f for f in group.files[1:] if protection.auto_select_allowed(f.path)]
    if len(picked) >= len(group.files):
        picked = picked[:-1]
    assert keep not in picked
    return picked


def remove_duplicates(groups: list[DuplicateGroup], selected: set[str],
                      allow_program_files: bool = False,
                      control: ScanControl | None = None,
                      trash_func=None) -> OperationResult:
    """Перемещает выбранные копии в корзину, гарантируя, что в каждом наборе
    остаётся минимум одна неизменённая копия с тем же содержимым."""
    total = OperationResult()
    for g in groups:
        if control and control.cancelled:
            total.cancelled = True
            break
        to_remove = [f for f in g.files if f.path in selected]
        if not to_remove:
            continue
        keepers = [f for f in g.files if f.path not in selected]
        if not keepers:
            for f in to_remove:
                total.fail(f.path, "в наборе должна остаться хотя бы одна копия — пропущено")
            continue
        # перепроверяем, что сохраняемая копия существует и по-прежнему идентична
        keeper_ok = False
        for k in keepers:
            if verify_unchanged(k) is None:
                try:
                    if full_hash(k.path) == g.sha256:
                        keeper_ok = True
                        break
                except (OSError, ScanCancelled):
                    pass
        if not keeper_ok:
            for f in to_remove:
                total.fail(f.path, "оставляемая копия изменилась или недоступна — набор пропущен")
            continue
        verified: list[FileItem] = []
        for f in to_remove:
            reason = verify_unchanged(f)
            if reason:
                total.fail(f.path, reason)
                continue
            try:
                if full_hash(f.path) != g.sha256:
                    total.fail(f.path, "содержимое изменилось — пропущено")
                    continue
            except OSError as exc:
                total.fail(f.path, f"не удалось перепроверить: {exc}")
                continue
            verified.append(f)
        total.merge(recycle_files(verified, allow_program_files, control, trash_func))
    return total
