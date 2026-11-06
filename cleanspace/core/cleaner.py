"""Безопасное выполнение операций с файлами.

Перед каждым действием:
1. файл перепроверяется — он существует и не изменился с момента сканирования
   (размер и дата изменения совпадают);
2. путь проверяется защитой (системные файлы — никогда, файлы программ — только
   если пользователь разрешил в настройках);
3. для временных файлов дополнительно проверяется, что путь всё ещё лежит внутри
   разрешённой папки категории (защита от подмены через ссылки).

Освобождённым считается только место от окончательно удалённых файлов.
Перемещение в корзину учитывается отдельно — место при этом не освобождается.
"""
from __future__ import annotations

import os
import shutil
import stat as stat_mod
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import protection
from .scanner import ScanControl, file_signature
from .utils import is_under, norm, real_norm


@dataclass(slots=True)
class FileItem:
    path: str
    size: int
    mtime: float


@dataclass
class OperationResult:
    processed: int = 0
    failed: int = 0
    freed: int = 0        # окончательно удалено
    recycled: int = 0     # перемещено в корзину
    moved: int = 0        # перемещено в другие папки
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False
    done_paths: list[str] = field(default_factory=list)

    def fail(self, path: str, reason: str) -> None:
        self.failed += 1
        if len(self.errors) < 500:
            self.errors.append(f"{path} — {reason}")

    def merge(self, other: "OperationResult") -> None:
        self.processed += other.processed
        self.failed += other.failed
        self.freed += other.freed
        self.recycled += other.recycled
        self.moved += other.moved
        self.errors.extend(other.errors[: max(0, 500 - len(self.errors))])
        self.cancelled = self.cancelled or other.cancelled
        self.done_paths.extend(other.done_paths)


def _explain(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "нет доступа или файл используется другой программой"
    if isinstance(exc, FileNotFoundError):
        return "файл больше не существует"
    winerr = getattr(exc, "winerror", None)
    if winerr == 32:
        return "файл используется другой программой"
    if winerr == 5:
        return "нет доступа"
    return str(exc) or exc.__class__.__name__


def verify_unchanged(item: FileItem) -> str | None:
    """None — файл на месте и не изменился; иначе — причина отказа."""
    sig = file_signature(item.path)
    if sig is None:
        return "файл больше не существует"
    size, mtime = sig
    if size != item.size or abs(mtime - item.mtime) > 1e-3:
        return "файл изменился после сканирования — пропущен"
    if os.path.islink(item.path):
        return "это ссылка — пропущено"
    return None


def _progress(control: ScanControl | None, i: int, total: int, path: str) -> None:
    if control:
        control.report(path, i, total)


def delete_temp_files(items: Iterable[FileItem], allowed_roots: Iterable[str],
                      control: ScanControl | None = None) -> OperationResult:
    """Окончательное удаление временных файлов (только внутри allowed_roots)."""
    result = OperationResult()
    roots = [real_norm(r) for r in allowed_roots]
    items = list(items)
    touched_dirs: set[str] = set()
    for i, item in enumerate(items):
        if control and control.cancelled:
            result.cancelled = True
            break
        _progress(control, i, len(items), item.path)
        real = real_norm(item.path)
        if not any(is_under(real, r) and real != r for r in roots):
            result.fail(item.path, "файл вне разрешённой папки — пропущен")
            continue
        if protection.classify(item.path) == protection.SYSTEM:
            result.fail(item.path, "системный файл — пропущен")
            continue
        reason = verify_unchanged(item)
        if reason:
            result.fail(item.path, reason)
            continue
        try:
            try:
                os.remove(item.path)
            except PermissionError:
                # снимаем атрибут «только чтение» у временного файла и пробуем ещё раз
                st = os.stat(item.path)
                if st.st_mode & stat_mod.S_IWRITE:
                    raise
                os.chmod(item.path, st.st_mode | stat_mod.S_IWRITE)
                os.remove(item.path)
            result.processed += 1
            result.freed += item.size
            result.done_paths.append(item.path)
            touched_dirs.add(os.path.dirname(item.path))
        except OSError as exc:
            result.fail(item.path, _explain(exc))
    _remove_empty_dirs(touched_dirs, roots)
    return result


def _remove_empty_dirs(dirs: set[str], roots: list[str]) -> None:
    """Удаляет опустевшие подпапки временных каталогов (сами корни не трогаем)."""
    for d in sorted(dirs, key=len, reverse=True):
        current = d
        while True:
            nreal = real_norm(current)
            if not any(is_under(nreal, r) and nreal != r for r in roots):
                break
            if os.path.islink(current):
                break
            try:
                os.rmdir(current)  # удаляет только пустую папку
            except OSError:
                break
            current = os.path.dirname(current)


def _send_to_trash(path: str) -> None:
    from send2trash import send2trash
    send2trash(path)


def recycle_files(items: Iterable[FileItem], allow_program_files: bool = False,
                  control: ScanControl | None = None,
                  trash_func: Callable[[str], None] | None = None) -> OperationResult:
    """Перемещение выбранных пользователем файлов в корзину Windows."""
    trash = trash_func or _send_to_trash
    result = OperationResult()
    items = list(items)
    for i, item in enumerate(items):
        if control and control.cancelled:
            result.cancelled = True
            break
        _progress(control, i, len(items), item.path)
        ok, why = protection.can_remove(item.path, allow_program_files)
        if not ok:
            result.fail(item.path, why)
            continue
        reason = verify_unchanged(item)
        if reason:
            result.fail(item.path, reason)
            continue
        try:
            trash(item.path)
            if os.path.lexists(item.path):
                result.fail(item.path, "Windows не переместила файл в корзину")
                continue
            result.processed += 1
            result.recycled += item.size
            result.done_paths.append(item.path)
        except Exception as exc:
            result.fail(item.path, _explain(exc))
    return result


def unique_destination(dest_dir: str, name: str) -> str:
    """Имя без конфликтов: «файл.zip» -> «файл (2).zip», если такой уже есть."""
    base, ext = os.path.splitext(name)
    candidate = os.path.join(dest_dir, name)
    n = 2
    while os.path.lexists(candidate):
        candidate = os.path.join(dest_dir, f"{base} ({n}){ext}")
        n += 1
    return candidate


def move_files(plan: Iterable[tuple[FileItem, str]], allow_program_files: bool = False,
               control: ScanControl | None = None) -> OperationResult:
    """Перемещение файлов по плану [(файл, папка назначения), ...]. Ничего не перезаписывает."""
    result = OperationResult()
    plan = list(plan)
    for i, (item, dest_dir) in enumerate(plan):
        if control and control.cancelled:
            result.cancelled = True
            break
        _progress(control, i, len(plan), item.path)
        ok, why = protection.can_remove(item.path, allow_program_files)
        if not ok:
            result.fail(item.path, why)
            continue
        if protection.classify(dest_dir) in (protection.SYSTEM, protection.PROGRAM):
            result.fail(item.path, "папка назначения — системная или программная")
            continue
        reason = verify_unchanged(item)
        if reason:
            result.fail(item.path, reason)
            continue
        try:
            os.makedirs(dest_dir, exist_ok=True)
            if norm(os.path.dirname(item.path)) == norm(dest_dir):
                continue  # уже на месте
            target = unique_destination(dest_dir, os.path.basename(item.path))
            shutil.move(item.path, target)
            result.processed += 1
            result.moved += item.size
            result.done_paths.append(item.path)
        except OSError as exc:
            result.fail(item.path, _explain(exc))
    return result
