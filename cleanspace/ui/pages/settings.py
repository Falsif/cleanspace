"""Настройки CleanSpace (сохраняются в SQLite и действуют после перезапуска)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QListWidget,
                               QMessageBox, QSpinBox)

from ...core import winshell
from ...core.utils import IS_WINDOWS, user_home
from ..widgets import Card, button, label
from .base import BasePage


class SettingsPage(BasePage):
    key = "settings"
    title = "Настройки"
    subtitle = "Все изменения сохраняются автоматически"
    scrollable = True

    def __init__(self, ctx):
        super().__init__(ctx)
        self._loading = True
        # --- Оформление ---
        c = self._card("Оформление")
        row = QHBoxLayout()
        row.addWidget(label("Тема:"))
        self.theme = QComboBox()
        self.theme.addItem("Тёмная", "dark")
        self.theme.addItem("Светлая", "light")
        self.theme.currentIndexChanged.connect(
            lambda: self._set("theme", self.theme.currentData()))
        row.addWidget(self.theme)
        row.addSpacing(24)
        row.addWidget(label("Язык:"))
        self.lang = QComboBox()
        self.lang.addItem("Русский", "ru")
        row.addWidget(self.lang)
        row.addStretch(1)
        c.lay.addLayout(row)

        # --- Безопасность ---
        c = self._card("Безопасность")
        self.safe = self._check(c, "Безопасный режим — только просмотр результатов, без удаления "
                                   "и перемещения файлов", "safe_mode")
        self.allow_prog = self._check(
            c, "Разрешить действия с файлами программ (Program Files, ProgramData…) — не рекомендуется",
            "allow_program_files")
        c.lay.addWidget(label("Системные файлы Windows, точки восстановления, обновления и драйверы "
                              "CleanSpace не удаляет никогда — эту защиту отключить нельзя.",
                              "faint", wrap=True))

        # --- Папки для анализа ---
        c = self._card("Папки для анализа",
                       "Где искать большие, старые файлы и дубликаты по умолчанию. "
                       "Если список пуст — используется папка пользователя.")
        self.folders = QListWidget()
        self.folders.setMaximumHeight(120)
        c.lay.addWidget(self.folders)
        row = QHBoxLayout()
        b = button("Добавить папку…", "folder")
        b.clicked.connect(lambda: self._add_to_list("scan_folders", self.folders))
        row.addWidget(b)
        b = button("Удалить")
        b.clicked.connect(lambda: self._remove_from_list("scan_folders", self.folders))
        row.addWidget(b)
        row.addStretch(1)
        c.lay.addLayout(row)

        # --- Исключения ---
        c = self._card("Исключения",
                       "Эти папки и файлы CleanSpace не анализирует и не трогает. Защита работает и "
                       "при обращении через символические ссылки или точки соединения.")
        self.excl = QListWidget()
        self.excl.setMaximumHeight(140)
        c.lay.addWidget(self.excl)
        row = QHBoxLayout()
        b = button("Добавить папку…", "folder")
        b.clicked.connect(lambda: self._add_to_list("exclusions", self.excl))
        row.addWidget(b)
        b = button("Добавить файл…")
        b.clicked.connect(self._add_excl_file)
        row.addWidget(b)
        b = button("Удалить")
        b.clicked.connect(lambda: self._remove_from_list("exclusions", self.excl))
        row.addWidget(b)
        row.addStretch(1)
        c.lay.addLayout(row)

        # --- Уведомления ---
        c = self._card("Уведомления")
        self.n_all = self._check(c, "Показывать уведомления Windows", "notifications_enabled")
        self.n_low = self._check(c, "«На диске осталось мало места»", "notify_low_space")
        row = QHBoxLayout()
        row.addSpacing(28)
        row.addWidget(label("Порог свободного места на системном диске:", "muted"))
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 2000)
        self.threshold.setSuffix(" ГБ")
        self.threshold.valueChanged.connect(lambda v: self._set("low_space_threshold_gb", v))
        row.addWidget(self.threshold)
        row.addStretch(1)
        c.lay.addLayout(row)
        self.n_scan = self._check(c, "«Сканирование завершено»", "notify_scan_done")
        self.n_large = self._check(c, "«Найдены большие файлы»", "notify_large_found")
        self.n_clean = self._check(c, "«Очистка завершена»", "notify_clean_done")

        # --- Фон и производительность ---
        c = self._card("Работа в фоне и нагрузка")
        self.bg = self._check(c, "Фоновая проверка свободного места на дисках", "background_monitoring")
        row = QHBoxLayout()
        row.addSpacing(28)
        row.addWidget(label("Проверять каждые", "muted"))
        self.interval = QSpinBox()
        self.interval.setRange(5, 240)
        self.interval.setSuffix(" мин")
        self.interval.valueChanged.connect(lambda v: self._set("monitor_interval_min", v))
        row.addWidget(self.interval)
        row.addStretch(1)
        c.lay.addLayout(row)
        self.tray = self._check(c, "При закрытии окна сворачивать в область уведомлений",
                                "minimize_to_tray")
        self.economy = self._check(c, "Экономичный режим — пониженный приоритет сканирования, "
                                      "ноутбук не будет тормозить", "economy_mode")
        row = QHBoxLayout()
        row.addWidget(label("Максимум результатов в списках:", "muted"))
        self.maxr = QSpinBox()
        self.maxr.setRange(100, 100_000)
        self.maxr.setSingleStep(500)
        self.maxr.valueChanged.connect(lambda v: self._set("max_results", v))
        row.addWidget(self.maxr)
        row.addWidget(label("(ограничивает расход оперативной памяти)", "faint"))
        row.addStretch(1)
        c.lay.addLayout(row)

        # --- Система ---
        c = self._card("Запуск")
        self.autostart = QCheckBox("Запускать CleanSpace вместе с Windows (свёрнутым)")
        self.autostart.toggled.connect(self._toggle_autostart)
        self.autostart.setEnabled(IS_WINDOWS)
        c.lay.addWidget(self.autostart)

        # --- Данные ---
        c = self._card("Данные")
        c.lay.addWidget(label(f"Настройки и история хранятся в: {ctx.storage.path}", "faint", wrap=True))
        row = QHBoxLayout()
        b = button("Экспорт отчёта в CSV…", "export")
        b.clicked.connect(self._export)
        row.addWidget(b)
        b = button("Сбросить настройки", "refresh")
        b.clicked.connect(self._reset)
        row.addWidget(b)
        row.addStretch(1)
        c.lay.addLayout(row)
        self.lay.addStretch(1)
        self.load()

    def on_show(self):
        self.load()

    # --- помощники ---
    def _card(self, title: str, desc: str = "") -> Card:
        c = Card(margins=16, spacing=8)
        c.lay.addWidget(label(title, "h2"))
        if desc:
            c.lay.addWidget(label(desc, "muted", wrap=True))
        self.lay.insertWidget(self.lay.count(), c)
        return c

    def _check(self, card: Card, text: str, key: str) -> QCheckBox:
        cb = QCheckBox(text)
        cb.toggled.connect(lambda v: self._set(key, bool(v)))
        card.lay.addWidget(cb)
        return cb

    def _set(self, key, value):
        if self._loading:
            return
        if key == "allow_program_files" and value:
            if QMessageBox.warning(
                    self, "Файлы программ",
                    "Удаление файлов из папок установленных программ может сломать эти программы. "
                    "Правильный способ — «Параметры → Приложения → Удалить».\n\nВсё равно разрешить?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                self._loading = True
                self.allow_prog.setChecked(False)
                self._loading = False
                return
        self.ctx.set_setting(key, value)
        if key == "notifications_enabled":
            self._update_notify_enabled()

    def _update_notify_enabled(self):
        on = self.n_all.isChecked()
        for w in (self.n_low, self.n_scan, self.n_large, self.n_clean, self.threshold):
            w.setEnabled(on)

    def load(self):
        self._loading = True
        s = self.ctx.storage
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.get("theme"))))
        for cb, key in ((self.safe, "safe_mode"), (self.allow_prog, "allow_program_files"),
                        (self.n_all, "notifications_enabled"), (self.n_low, "notify_low_space"),
                        (self.n_scan, "notify_scan_done"), (self.n_large, "notify_large_found"),
                        (self.n_clean, "notify_clean_done"), (self.bg, "background_monitoring"),
                        (self.tray, "minimize_to_tray"), (self.economy, "economy_mode")):
            cb.setChecked(bool(s.get(key)))
        self.threshold.setValue(int(s.get("low_space_threshold_gb") or 10))
        self.interval.setValue(int(s.get("monitor_interval_min") or 15))
        self.maxr.setValue(int(s.get("max_results") or 5000))
        self.autostart.setChecked(winshell.autostart_enabled() if IS_WINDOWS else bool(s.get("autostart")))
        self.folders.clear()
        self.folders.addItems(s.get("scan_folders") or [])
        if not s.get("scan_folders"):
            self.folders.addItem(f"(по умолчанию) {user_home()}")
            self.folders.item(0).setFlags(Qt.NoItemFlags)
        self.excl.clear()
        self.excl.addItems(s.get("exclusions") or [])
        self._update_notify_enabled()
        self._loading = False

    def _add_to_list(self, key, widget):
        p = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if not p:
            return
        p = os.path.normpath(p)
        items = list(self.ctx.setting(key) or [])
        if p not in items:
            items.append(p)
            self.ctx.set_setting(key, items)
        self.load()

    def _add_excl_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if p:
            self.ctx.add_exclusion(os.path.normpath(p))
            self.load()

    def _remove_from_list(self, key, widget):
        it = widget.currentItem()
        if not it or not (it.flags() & Qt.ItemIsEnabled):
            return
        items = [x for x in (self.ctx.setting(key) or []) if x != it.text()]
        self.ctx.set_setting(key, items)
        self.load()

    def _toggle_autostart(self, on):
        if self._loading:
            return
        ok, err = winshell.set_autostart(on)
        if not ok:
            QMessageBox.warning(self, "Автозапуск", f"Не удалось изменить автозапуск:\n{err}")
            self._loading = True
            self.autostart.setChecked(not on)
            self._loading = False
            return
        self.ctx.set_setting("autostart", on)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчёт", "CleanSpace_отчёт.csv",
                                              "CSV (*.csv)")
        if path:
            try:
                n = self.ctx.storage.export_history_csv(path)
                QMessageBox.information(self, "Экспорт", f"Сохранено записей: {n}")
            except OSError as exc:
                QMessageBox.warning(self, "Экспорт", str(exc))

    def _reset(self):
        if QMessageBox.question(self, "Сброс настроек",
                                "Вернуть все настройки по умолчанию? История очистки сохранится.") \
                != QMessageBox.Yes:
            return
        self.ctx.storage.reset_settings()
        if IS_WINDOWS:
            winshell.set_autostart(False)
        self.load()
        for key in ("theme", "safe_mode", "allow_program_files", "exclusions", "scan_folders",
                    "background_monitoring", "economy_mode"):
            self.ctx.settings_changed.emit(key)
        self.ctx.summary_changed.emit()
