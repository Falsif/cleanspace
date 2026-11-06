"""Фоновое выполнение долгих операций (интерфейс не зависает, операцию можно отменить)."""
from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.scanner import ScanControl


class _Worker(QObject):
    progress = Signal(str, object, object)  # object: размеры > 2 ГБ не влезают в int Qt
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[ScanControl], object], control: ScanControl):
        super().__init__()
        self.fn = fn
        self.control = control
        control.progress = lambda cur, a, b: self.progress.emit(cur, a, b)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(self.control)
        except Exception as exc:  # ошибка не должна ронять программу
            traceback.print_exc()
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        self.done.emit(result)


class Task(QObject):
    """Одна фоновая операция. Держите ссылку на объект, пока операция идёт."""
    progress = Signal(str, object, object)  # object: размеры > 2 ГБ не влезают в int Qt
    finished = Signal(object)
    failed = Signal(str)

    _active: set["Task"] = set()

    def __init__(self, fn: Callable[[ScanControl], object], economy: bool = False, parent=None):
        super().__init__(parent)
        self.control = ScanControl(economy=economy)
        self._thread = QThread()
        self._worker = _Worker(fn, self.control)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self.running = False

    def start(self) -> "Task":
        Task._active.add(self)
        self.running = True
        self._thread.start()
        return self

    def cancel(self) -> None:
        self.control.cancel()

    @property
    def cancelled(self) -> bool:
        return self.control.cancelled

    def _cleanup(self) -> None:
        self.running = False
        self._thread.quit()
        self._thread.wait(5000)
        Task._active.discard(self)

    def _on_done(self, result) -> None:
        self._cleanup()
        self.finished.emit(result)

    def _on_failed(self, msg: str) -> None:
        self._cleanup()
        self.failed.emit(msg)

    @classmethod
    def cancel_all(cls) -> None:
        for t in list(cls._active):
            t.cancel()
        for t in list(cls._active):
            t._thread.quit()
            t._thread.wait(3000)
