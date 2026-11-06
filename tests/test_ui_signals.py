"""Регресс: размеры больше 2 ГБ должны передаваться в интерфейс без переполнения."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_progress_signal_handles_more_than_2gb():
    from PySide6.QtWidgets import QApplication
    from cleanspace.ui.workers import Task

    app = QApplication.instance() or QApplication([])
    got, done = [], []

    def job(control):
        control.report("C:\\", 10, 5 * 1024 ** 3, force=True)
        return "ok"

    t = Task(job)
    t.progress.connect(lambda _p, _f, size: got.append(size))
    t.finished.connect(done.append)
    t.start()
    end = time.time() + 10
    while not done and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert done == ["ok"]
    assert got == [5 * 1024 ** 3]
