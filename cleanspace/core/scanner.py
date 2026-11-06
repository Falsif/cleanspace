"""Безопасный обход файловой системы.

* не переходит по символическим ссылкам и точкам соединения (junction) — поэтому
  исключённые папки нельзя «обойти» через ссылку, а размеры не считаются дважды;
* пропускает исключённые пользователем папки (сравнение по реальным путям);
* не падает на файлах без доступа — считает их и продолжает;
* поддерживает отмену и экономичный режим (низкий приоритет + паузы).
"""
from __future__ import annotations

import os
import stat as stat_mod
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

from .utils import IS_WINDOWS, is_under, norm, real_norm

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
_CLOUD_ATTRS = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


class ScanCancelled(Exception):
    pass


@dataclass
class ScanControl:
    """Общий объект управления: отмена, экономичный режим, прогресс."""
    cancel_event: threading.Event = field(default_factory=threading.Event)
    economy: bool = False
    progress: Callable[[str, int, int], None] | None = None  # (текущая папка, файлов, байт)
    _last_report: float = 0.0

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()

    def check(self) -> None:
        if self.cancel_event.is_set():
            raise ScanCancelled()

    def report(self, current: str, files: int, size: int, force: bool = False) -> None:
        now = time.monotonic()
        if self.progress and (force or now - self._last_report > 0.15):
            self._last_report = now
            self.progress(current, files, size)


@dataclass
class ScanStats:
    files: int = 0
    dirs: int = 0
    bytes: int = 0
    errors: int = 0          # папки/файлы без доступа
    skipped_links: int = 0   # ссылки и точки соединения (не обходятся)
    skipped_excluded: int = 0
    cancelled: bool = False
    error_samples: list[str] = field(default_factory=list)

    def add_error(self, path: str, exc: BaseException) -> None:
        self.errors += 1
        if len(self.error_samples) < 50:
            self.error_samples.append(f"{path}: {exc.__class__.__name__}")

    @property
    def complete(self) -> bool:
        return not self.cancelled and self.errors == 0


@dataclass(slots=True)
class FileEntry:
    path: str
    size: int
    mtime: float
    cloud_only: bool = False  # файл OneDrive «только в облаке» — содержимое не читаем


class Exclusions:
    """Список исключённых путей. Сравнение и по обычному, и по реальному пути."""

    def __init__(self, paths: Iterable[str] = ()):
        items: set[str] = set()
        for p in paths:
            if p:
                items.add(norm(p))
                items.add(real_norm(p))
        self._items = tuple(sorted(items))

    def __bool__(self) -> bool:
        return bool(self._items)

    def matches(self, npath: str) -> bool:
        return any(is_under(npath, ex) for ex in self._items)

    def matches_path(self, path: str) -> bool:
        return self.matches(norm(path)) or self.matches(real_norm(path))


def _is_link(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink():
            return True
        is_junction = getattr(entry, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        if IS_WINDOWS and entry.is_dir(follow_symlinks=False):
            st = entry.stat(follow_symlinks=False)
            attrs = getattr(st, "st_file_attributes", 0)
            # Папка-точка повторной обработки, но не облачная папка OneDrive
            if attrs & FILE_ATTRIBUTE_REPARSE_POINT and not attrs & _CLOUD_ATTRS:
                tag = getattr(st, "st_reparse_tag", 0)
                # 0xA0000003 = MOUNT_POINT (junction), 0xA000000C = SYMLINK
                if tag in (0xA0000003, 0xA000000C):
                    return True
    except OSError:
        return True
    return False


@contextmanager
def scan_priority(economy: bool):
    """Временно понижает приоритет процесса (CPU и диск), если включён экономичный режим."""
    if not economy:
        yield
        return
    restore = None
    restore_io = None
    try:
        import psutil
        proc = psutil.Process()
        try:
            restore = proc.nice()
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if IS_WINDOWS else 10)
        except Exception:
            restore = None
        try:
            restore_io = proc.ionice()
            if IS_WINDOWS:
                proc.ionice(psutil.IOPRIO_LOW)
            else:
                proc.ionice(psutil.IOPRIO_CLASS_IDLE)
        except Exception:
            restore_io = None
    except Exception:
        pass
    try:
        yield
    finally:
        try:
            import psutil
            proc = psutil.Process()
            if restore is not None:
                try:
                    proc.nice(restore)
                except Exception:
                    pass  # на Linux повысить приоритет обратно без прав нельзя — не страшно
            if restore_io is not None:
                try:
                    if IS_WINDOWS:
                        proc.ionice(restore_io)
                    else:
                        proc.ionice(restore_io.ioclass, restore_io.value)
                except Exception:
                    pass
        except Exception:
            pass


def walk(roots: Iterable[str], control: ScanControl, stats: ScanStats,
         exclusions: Exclusions | None = None,
         on_dir: Callable[[str], None] | None = None) -> Iterator[FileEntry]:
    """Обходит папки и выдаёт файлы. Отмена — через control (выход без исключения,
    stats.cancelled = True)."""
    exclusions = exclusions or Exclusions()
    pause_every = 300 if control.economy else 0
    counter = 0
    stack: list[str] = []
    for root in roots:
        if not root:
            continue
        real_root = os.path.realpath(root)
        if exclusions.matches_path(real_root) or exclusions.matches_path(root):
            stats.skipped_excluded += 1
            continue
        if os.path.isfile(real_root):
            try:
                st = os.stat(real_root)
                stats.files += 1
                stats.bytes += st.st_size
                yield FileEntry(real_root, st.st_size, st.st_mtime)
            except OSError as exc:
                stats.add_error(real_root, exc)
            continue
        stack.append(real_root)

    while stack:
        if control.cancelled:
            stats.cancelled = True
            return
        current = stack.pop()
        stats.dirs += 1
        if on_dir:
            on_dir(current)
        control.report(current, stats.files, stats.bytes)
        try:
            it = os.scandir(current)
        except OSError as exc:
            stats.add_error(current, exc)
            continue
        subdirs: list[str] = []
        with it:
            while True:
                try:
                    entry = next(it)
                except StopIteration:
                    break
                except OSError as exc:
                    stats.add_error(current, exc)
                    break
                if pause_every:
                    counter += 1
                    if counter % pause_every == 0:
                        time.sleep(0.004)
                if control.cancelled:
                    stats.cancelled = True
                    return
                try:
                    if _is_link(entry):
                        stats.skipped_links += 1
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if exclusions and exclusions.matches(norm(entry.path)):
                            stats.skipped_excluded += 1
                            continue
                        subdirs.append(entry.path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if exclusions and exclusions.matches(norm(entry.path)):
                        stats.skipped_excluded += 1
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if not stat_mod.S_ISREG(st.st_mode):
                        continue
                    cloud = bool(getattr(st, "st_file_attributes", 0) & _CLOUD_ATTRS)
                    stats.files += 1
                    stats.bytes += st.st_size
                    yield FileEntry(entry.path, st.st_size, st.st_mtime, cloud)
                except OSError as exc:
                    stats.add_error(entry.path, exc)
        # обратный порядок, чтобы обход шёл по алфавиту
        stack.extend(reversed(subdirs))
    control.report("", stats.files, stats.bytes, force=True)


def file_signature(path: str) -> tuple[int, float] | None:
    """(размер, mtime) — для перепроверки «файл не изменился с момента сканирования»."""
    try:
        st = os.stat(path, follow_symlinks=False)
        if not stat_mod.S_ISREG(st.st_mode):
            return None
        return st.st_size, st.st_mtime
    except OSError:
        return None
