"""Базовая страница: заголовок, баннер безопасного режима, фоновые задачи."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (QFileDialog, QFrame, QMessageBox, QScrollArea, QVBoxLayout,
                               QWidget)

from ..context import AppContext
from ..dialogs import ConfirmDialog, ResultDialog
from ..widgets import Banner, PageHeader, ProgressPanel
from ..workers import Task


class BasePage(QWidget):
    key = ""
    title = ""
    subtitle = ""
    scrollable = False

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        self.task: Task | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setObjectName("Page")
        self.lay = QVBoxLayout(content)
        self.lay.setContentsMargins(28, 22, 28, 22)
        self.lay.setSpacing(14)
        if self.scrollable:
            sa = QScrollArea()
            sa.setObjectName("PageScroll")
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setWidget(content)
            outer.addWidget(sa)
        else:
            outer.addWidget(content)
        self.lay.addWidget(PageHeader(self.title, self.subtitle))
        self.safe_banner = Banner("Включён безопасный режим: доступен только просмотр результатов. "
                                  "Удаление и перемещение отключены (Настройки → Безопасность).",
                                  "info")
        self.lay.addWidget(self.safe_banner)
        self.progress = ProgressPanel()
        self.progress.cancel_requested.connect(self.cancel_task)
        self.lay.addWidget(self.progress)
        ctx.settings_changed.connect(self._on_setting)
        self.safe_banner.setVisible(ctx.safe_mode)  # кнопки страницы ещё не созданы

    # --- безопасный режим ----------------------------------------------------
    def _on_setting(self, key: str) -> None:
        if key in ("safe_mode", "allow_program_files"):
            self._update_safe_mode()

    def _update_safe_mode(self) -> None:
        self.safe_banner.setVisible(self.ctx.safe_mode)
        self.on_safe_mode(self.ctx.safe_mode)

    def on_safe_mode(self, safe: bool) -> None:
        """Переопределяется: отключить кнопки удаления."""

    def on_show(self) -> None:
        """Вызывается при открытии страницы."""

    # --- фоновые задачи -------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.task is not None and self.task.running

    def run_task(self, fn: Callable, title: str, on_done: Callable, steps: bool = False) -> None:
        if self.busy:
            return
        self.progress.start(title, determinate=False)
        self.task = Task(fn, economy=self.ctx.economy, parent=self)
        if steps:
            self.task.progress.connect(self.progress.update_steps)
        else:
            self.task.progress.connect(self.progress.update_files)
        self.task.finished.connect(lambda r: self._task_done(r, on_done))
        self.task.failed.connect(self._task_failed)
        self.set_busy(True)
        self.task.start()

    def _task_done(self, result, on_done) -> None:
        self.progress.finish()
        self.set_busy(False)
        try:
            on_done(result)
        except Exception as exc:  # не даём ошибке интерфейса уронить приложение
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Ошибка", f"Не удалось показать результат: {exc}")

    def _task_failed(self, msg: str) -> None:
        self.progress.finish()
        self.set_busy(False)
        QMessageBox.warning(self, "Ошибка", f"Операция завершилась с ошибкой:\n{msg}")

    def cancel_task(self) -> None:
        if self.task:
            self.task.cancel()

    def set_busy(self, busy: bool) -> None:
        """Переопределяется: блокировка кнопок на время операции."""

    # --- операции с файлами ---------------------------------------------------
    def confirm(self, title: str, intro: str, rows, action: str, note: str = "",
                danger: bool = True, target_header: str = "Действие") -> bool:
        if self.ctx.safe_mode:
            QMessageBox.information(self, "Безопасный режим",
                                    "Безопасный режим включён — изменения файлов отключены.")
            return False
        if not rows:
            QMessageBox.information(self, title, "Ничего не выбрано.")
            return False
        dlg = ConfirmDialog(self, title, intro, rows, action, note, danger, target_header)
        return dlg.exec() == ConfirmDialog.Accepted

    def show_result(self, title: str, result) -> None:
        ResultDialog(self, title, result).exec()

    def pick_folder(self, start: str = "") -> str:
        return QFileDialog.getExistingDirectory(self, "Выберите папку или диск", start)
