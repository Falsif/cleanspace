"""Общий контекст приложения: хранилище, сигналы между страницами, уведомления."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.cleaner import OperationResult
from ..core.scanner import Exclusions
from ..core.storage import Storage
from ..core.utils import format_size, user_home


class AppContext(QObject):
    summary_changed = Signal()
    history_changed = Signal()
    settings_changed = Signal(str)
    navigate = Signal(str)              # переход на страницу по ключу
    notify_requested = Signal(str, str, str)  # (тип, заголовок, текст)
    smart_results_ready = Signal(object)  # результаты умной очистки с главной страницы
    large_results_ready = Signal(object)  # (порог, FinderResult)
    analyze_path = Signal(str)            # открыть «Анализ дисков» для пути

    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage

    # --- настройки -----------------------------------------------------------
    def setting(self, key: str):
        return self.storage.get(key)

    def set_setting(self, key: str, value) -> None:
        self.storage.set(key, value)
        self.settings_changed.emit(key)

    def exclusions(self) -> Exclusions:
        return Exclusions(self.storage.get("exclusions") or [])

    def add_exclusion(self, path: str) -> None:
        ex = list(self.storage.get("exclusions") or [])
        if path not in ex:
            ex.append(path)
            self.set_setting("exclusions", ex)

    def scan_roots(self) -> list[str]:
        roots = [r for r in (self.storage.get("scan_folders") or []) if r]
        return roots or [str(user_home())]

    @property
    def economy(self) -> bool:
        return bool(self.storage.get("economy_mode"))

    @property
    def safe_mode(self) -> bool:
        return bool(self.storage.get("safe_mode"))

    @property
    def allow_program_files(self) -> bool:
        return bool(self.storage.get("allow_program_files"))

    @property
    def max_results(self) -> int:
        try:
            return max(100, int(self.storage.get("max_results")))
        except (TypeError, ValueError):
            return 5000

    # --- итоги и история -----------------------------------------------------
    def update_summary(self, **values) -> None:
        self.storage.update_summary(**values)
        self.summary_changed.emit()

    def record(self, result: OperationResult, category: str, action: str) -> None:
        if result.processed == 0 and result.failed == 0:
            return
        self.storage.add_history(category, action, result.processed, result.failed,
                                 result.freed, result.recycled, result.errors, result.moved)
        self.history_changed.emit()
        self.summary_changed.emit()
        parts = []
        if result.freed:
            parts.append(f"освобождено {format_size(result.freed)}")
        if result.recycled:
            parts.append(f"в корзину {format_size(result.recycled)}")
        if result.moved:
            parts.append(f"перемещено {format_size(result.moved)}")
        if result.failed:
            parts.append(f"не удалось: {result.failed}")
        self.notify("clean_done", "Очистка завершена", f"{category}: " + ", ".join(parts))

    def notify(self, kind: str, title: str, text: str) -> None:
        self.notify_requested.emit(kind, title, text)
