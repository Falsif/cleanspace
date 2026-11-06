"""Запуск приложения CleanSpace."""
from __future__ import annotations

import os
import sys
import traceback


def _single_instance(app) -> bool:
    """Не даём запустить вторую копию (она бы конкурировала за базу настроек)."""
    from PySide6.QtCore import QSharedMemory
    mem = QSharedMemory("CleanSpace_single_instance_v1")
    if mem.attach():
        mem.detach()  # на случай «мусора» после аварийного завершения в Unix
        if mem.attach():
            return False
    mem.create(1)
    app._single_mem = mem
    return True


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import APP_NAME
    from .core.storage import Storage
    from .ui import icons
    from .ui.context import AppContext
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("LUNEXA")
    app.setWindowIcon(icons.app_icon())
    app.setQuitOnLastWindowClosed(False)

    if sys.platform == "win32":
        try:  # своя иконка на панели задач, а не значок Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LUNEXA.CleanSpace")
        except Exception:
            pass

    if not _single_instance(app):
        QMessageBox.information(None, APP_NAME, "CleanSpace уже запущен (проверьте область уведомлений).")
        return 0

    def excepthook(exc_type, exc, tb):  # программа не должна закрываться из-за ошибки
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        print(text, file=sys.stderr)
        try:
            QMessageBox.warning(None, APP_NAME, f"Произошла ошибка, но программа продолжает работу:\n\n"
                                                f"{exc_type.__name__}: {exc}")
        except Exception:
            pass
    sys.excepthook = excepthook

    try:
        storage = Storage()
    except Exception as exc:
        QMessageBox.critical(None, APP_NAME, f"Не удалось открыть базу настроек:\n{exc}")
        return 1
    apply_theme(app, storage.get("theme"))
    ctx = AppContext(storage)
    win = MainWindow(ctx)
    if "--minimized" in sys.argv and win.tray is not None:
        pass  # запуск вместе с Windows — сразу в трей
    else:
        win.show()
    code = app.exec()
    storage.close()
    return code
