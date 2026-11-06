"""Главное окно: боковая панель навигации, страницы, значок в трее, уведомления."""
from __future__ import annotations

import time

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow,
                               QMenu, QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, APP_VERSION
from ..core import disks
from ..core.utils import GB, format_size
from . import icons
from .context import AppContext
from .pages.analyzer import AnalyzerPage
from .pages.downloads import DownloadsPage
from .pages.duplicates import DuplicatesPage
from .pages.finder_pages import LargeFilesPage, OldFilesPage
from .pages.history import HistoryPage
from .pages.home import HomePage
from .pages.settings import SettingsPage
from .pages.smart_clean import SmartCleanPage
from .theme import Theme, apply_theme
from .widgets import fade_in, label, refresh_button_icon
from .workers import Task

NAV = [
    ("home", "Главная", HomePage),
    ("smart", "Умная очистка", SmartCleanPage),
    ("analyze", "Анализ дисков", AnalyzerPage),
    ("large", "Большие файлы", LargeFilesPage),
    ("dupes", "Дубликаты", DuplicatesPage),
    ("old", "Старые файлы", OldFilesPage),
    ("downloads", "Загрузки", DownloadsPage),
    ("history", "История очистки", HistoryPage),
    ("settings", "Настройки", SettingsPage),
]
ICON_FOR = {"home": "home", "smart": "smart", "analyze": "analyze", "large": "large",
            "dupes": "dupes", "old": "old", "downloads": "downloads", "history": "history",
            "settings": "settings"}
NOTIFY_KEYS = {"low_space": "notify_low_space", "scan_done": "notify_scan_done",
               "large_found": "notify_large_found", "clean_done": "notify_clean_done"}


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(1000, 640)
        self.resize(1280, 760)

        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # --- боковая панель ---
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(224)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 16, 12, 12)
        sl.setSpacing(3)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(30, 30))
        brand.addWidget(logo)
        brand.addWidget(label(APP_NAME, "brand"))
        brand.addStretch(1)
        sl.addLayout(brand)
        sl.addSpacing(14)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text, _cls in NAV:
            b = QPushButton("  " + text)
            b.setProperty("nav", True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            if key == "settings":
                sl.addStretch(1)
            sl.addWidget(b)
        self.theme_btn = QPushButton()
        self.theme_btn.setProperty("nav", True)
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(self.toggle_theme)
        sl.addWidget(self.theme_btn)
        sl.addSpacing(4)
        sl.addWidget(label(f"Версия {APP_VERSION}", "faint"))
        h.addWidget(side)

        # --- страницы ---
        self.stack = QStackedWidget()
        self.pages = {}
        for key, _text, cls in NAV:
            page = cls(ctx)
            self.pages[key] = page
            self.stack.addWidget(page)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        ctx.navigate.connect(self.show_page)
        ctx.notify_requested.connect(self.notify)
        ctx.settings_changed.connect(self._on_setting)

        self._setup_tray()
        self._low_space_last: dict[str, float] = {}
        self.monitor = QTimer(self)
        self.monitor.timeout.connect(self.check_free_space)
        self._update_monitor()
        QTimer.singleShot(4000, self.check_free_space)

        self._refresh_nav_icons()
        geo = ctx.setting("window_geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        self.show_page("home", animate=False)

    # --- навигация ---
    def show_page(self, key: str, animate: bool = True) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.nav_buttons[key].setChecked(True)
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
            if animate:
                fade_in(page)
        page.on_show()

    def _refresh_nav_icons(self):
        for key, b in self.nav_buttons.items():
            b.setIcon(icons.icon(ICON_FOR[key], Theme.c["accent"] if key != "settings"
                                 else Theme.c["muted"], 18))
        dark = Theme.name == "dark"
        self.theme_btn.setText("  Светлая тема" if dark else "  Тёмная тема")
        self.theme_btn.setIcon(icons.icon("sun" if dark else "moon", Theme.c["muted"], 18))

    def toggle_theme(self):
        self.ctx.set_setting("theme", "light" if Theme.name == "dark" else "dark")

    def _on_setting(self, key: str):
        if key == "theme":
            apply_theme(QApplication.instance(), self.ctx.setting("theme"))
            icons._pixmap.cache_clear()
            self._refresh_nav_icons()
            for w in QApplication.allWidgets():
                if isinstance(w, QPushButton):
                    refresh_button_icon(w)
                w.update()
            self.pages["home"].refresh_disks()
        elif key in ("background_monitoring", "monitor_interval_min"):
            self._update_monitor()

    # --- трей и уведомления ---
    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        a = QAction("Открыть CleanSpace", menu)
        a.triggered.connect(self.restore_window)
        menu.addAction(a)
        a = QAction("Проверить свободное место", menu)
        a.triggered.connect(lambda: self.check_free_space(force=True))
        menu.addAction(a)
        menu.addSeparator()
        a = QAction("Выход", menu)
        a.triggered.connect(self.quit_app)
        menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.restore_window() if r in (QSystemTrayIcon.Trigger,
                                                     QSystemTrayIcon.DoubleClick) else None)
        self.tray.messageClicked.connect(self.restore_window)
        self.tray.show()

    def notify(self, kind: str, title: str, text: str):
        if not self.ctx.setting("notifications_enabled"):
            return
        key = NOTIFY_KEYS.get(kind)
        if key and not self.ctx.setting(key):
            return
        if self.tray:
            self.tray.showMessage(title, text, icons.app_icon(), 6000)

    def _update_monitor(self):
        if self.ctx.setting("background_monitoring"):
            minutes = max(5, int(self.ctx.setting("monitor_interval_min") or 15))
            self.monitor.start(minutes * 60_000)
        else:
            self.monitor.stop()

    def check_free_space(self, force: bool = False):
        """Фоновая проверка: только чтение свободного места, без сканирования файлов."""
        if not force and not self.ctx.setting("background_monitoring"):
            return
        threshold = float(self.ctx.setting("low_space_threshold_gb") or 10) * GB
        sysd = disks.system_disk()
        found = False
        for d in disks.list_disks():
            if d.removable:
                continue
            if d.free < threshold or (d is sysd and d.free < threshold):
                found = True
                last = self._low_space_last.get(d.mountpoint, 0)
                if force or time.time() - last > 6 * 3600:
                    self._low_space_last[d.mountpoint] = time.time()
                    self.notify("low_space", "На диске осталось мало места",
                                f"Диск {d.name}: свободно {format_size(d.free)} из "
                                f"{format_size(d.total)}. Откройте CleanSpace для очистки.")
        if force and not found:
            self.notify("low_space", "Свободного места достаточно",
                        "На всех дисках свободно больше заданного порога.")

    def restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        self.ctx.set_setting("window_geometry", bytes(self.saveGeometry().toBase64()).decode())
        if self.ctx.setting("minimize_to_tray") and self.tray and not getattr(self, "_quitting", False):
            e.ignore()
            self.hide()
            self.notify("info", APP_NAME, "CleanSpace продолжает работать в области уведомлений.")
            return
        self._quitting = True
        Task.cancel_all()
        if self.tray:
            self.tray.hide()
        e.accept()
        QApplication.instance().quit()

    def quit_app(self):
        self._quitting = True
        self.close()
