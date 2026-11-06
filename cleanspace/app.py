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


def _install_error_handler(app, app_name: str) -> None:
    """Ошибки не закрывают программу. Они записываются в errors.log, а сообщение
    показывается только из главного потока (окно из фонового потока было бы пустым)."""
    import threading
    import time

    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtWidgets import QMessageBox

    from .core.utils import app_data_dir

    log_path = app_data_dir() / "errors.log"

    class Relay(QObject):
        show = Signal(str)

    relay = Relay()
    state = {"last": 0.0}

    def show_box(text: str) -> None:
        if time.monotonic() - state["last"] < 5:  # не засыпать пользователя окнами
            return
        state["last"] = time.monotonic()
        QMessageBox.warning(None, app_name,
                            "Произошла ошибка, но программа продолжает работу.\n\n"
                            f"{text}\n\nПодробности записаны в файл:\n{log_path}")

    relay.show.connect(show_box, Qt.QueuedConnection)
    app._error_relay = relay  # держим ссылку

    def handle(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        print(text, file=sys.stderr)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(time.strftime("\n=== %d.%m.%Y %H:%M:%S ===\n") + text)
        except OSError:
            pass
        relay.show.emit(f"{exc_type.__name__}: {exc}")  # доставится в главный поток

    sys.excepthook = handle
    threading.excepthook = lambda a: handle(a.exc_type, a.exc_value, a.exc_traceback)


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

    _install_error_handler(app, APP_NAME)

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
