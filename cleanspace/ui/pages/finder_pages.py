"""Страницы «Большие файлы» и «Старые файлы» (общая основа)."""
from __future__ import annotations

import os
import time

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QMessageBox, QSpinBox

from ...core import disks, finders, winshell
from ...core.cleaner import recycle_files
from ...core.utils import GB, MB, format_size, plural
from ..file_table import FileTable
from ..widgets import Banner, ChipGroup, button, label
from .base import BasePage


class FinderPage(BasePage):
    chips: list = []
    custom_suffix = ""
    search_title = ""

    def __init__(self, ctx):
        super().__init__(ctx)
        row = QHBoxLayout()
        self.where = QComboBox()
        self.where.setMinimumWidth(240)
        row.addWidget(label("Где искать:", "muted"))
        row.addWidget(self.where)
        pick = button("Папка…", "folder")
        pick.clicked.connect(self._pick)
        row.addWidget(pick)
        row.addStretch(1)
        self.search_btn = button("Найти", "search", "accent")
        self.search_btn.clicked.connect(self.search)
        row.addWidget(self.search_btn)
        self.lay.addLayout(row)

        frow = QHBoxLayout()
        self.chip_group = ChipGroup(self.chips, default_index=self.default_chip)
        self.chip_group.changed.connect(self._chip_changed)
        frow.addWidget(self.chip_group)
        self.custom = QSpinBox()
        self.custom.setRange(1, 1_000_000)
        self.custom.setValue(self.custom_default)
        self.custom.setSuffix(self.custom_suffix)
        self.custom.setEnabled(False)
        frow.addWidget(self.custom)
        self.extra_filters(frow)
        frow.addStretch(1)
        self.lay.addLayout(frow)

        self.info = Banner("", "info")
        self.info.hide()
        self.lay.addWidget(self.info)
        self.summary = label(self.empty_hint, "muted", wrap=True)
        self.lay.addWidget(self.summary)

        frow2 = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Фильтр по имени или пути…")
        self.filter.textChanged.connect(lambda t: self.table.filter_text(t))
        frow2.addWidget(self.filter, 1)
        self.lay.addLayout(frow2)

        self.table = FileTable(ctx, checkable=True)
        self.table.checked_changed.connect(self._update_sel)
        self.table.exclude_requested.connect(self._exclude)
        self.lay.addWidget(self.table, 1)

        act = QHBoxLayout()
        self.sel_label = label("", "muted")
        act.addWidget(self.sel_label)
        act.addStretch(1)
        b = button("Выбрать все")
        b.clicked.connect(lambda: self.table.set_all_checked(True))
        act.addWidget(b)
        b = button("Снять выбор")
        b.clicked.connect(lambda: self.table.set_all_checked(False))
        act.addWidget(b)
        self.loc_btn = button("Открыть расположение", "open")
        self.loc_btn.clicked.connect(self._open_loc)
        act.addWidget(self.loc_btn)
        self.prop_btn = button("Свойства", "properties")
        self.prop_btn.clicked.connect(self._props)
        act.addWidget(self.prop_btn)
        self.ex_btn = button("В исключения", "exclude")
        self.ex_btn.clicked.connect(self._exclude_current)
        act.addWidget(self.ex_btn)
        self.trash_btn = button("В корзину…", "delete", "danger")
        self.trash_btn.clicked.connect(self.trash)
        act.addWidget(self.trash_btn)
        self.lay.addLayout(act)
        self._fill_where()
        ctx.settings_changed.connect(lambda k: self._fill_where() if k == "scan_folders" else None)
        self._busy = False
        self._update_sel()

    # --- для наследников ---
    default_chip = 0
    custom_default = 100
    empty_hint = ""

    def extra_filters(self, row):
        pass

    def make_job(self, roots, value, ex, max_results):
        raise NotImplementedError

    def describe(self, res, value) -> str:
        raise NotImplementedError

    def current_value(self):
        v = self.chip_group.value()
        return self.custom.value() if v is None else v

    # --- общее ---
    def _fill_where(self):
        self.where.clear()
        roots = self.ctx.scan_roots()
        self.where.addItem("Выбранные папки: " + "; ".join(roots), roots)
        for d in disks.list_disks():
            self.where.addItem(f"Весь диск {d.name}", [d.mountpoint])

    def on_show(self):
        if self.where.count() == 0:
            self._fill_where()

    def _pick(self):
        p = self.pick_folder()
        if p:
            p = os.path.normpath(p)
            self.where.insertItem(0, f"Папка: {p}", [p])
            self.where.setCurrentIndex(0)

    def _chip_changed(self, v):
        self.custom.setEnabled(v is None)

    def set_busy(self, busy):
        self._busy = busy
        self.search_btn.setEnabled(not busy)
        self._update_sel()

    def on_safe_mode(self, safe):
        if hasattr(self, "trash_btn"):
            self._update_sel()

    def search(self):
        roots = self.where.currentData() or self.ctx.scan_roots()
        value = self.current_value()
        ex = self.ctx.exclusions()
        maxr = self.ctx.max_results
        self.run_task(lambda c: self.make_job(roots, value, ex, maxr)(c), self.search_title,
                      lambda r: self._done(r, value))

    def _done(self, res, value):
        self.table.set_files(res.files, self.extra_values(res))
        self.summary.setText(self.describe(res, value))
        notes = []
        if self.task and self.task.cancelled:
            notes.append("Поиск остановлен — результаты неполные.")
        if res.stats.errors:
            notes.append(f"Нет доступа к {res.stats.errors} папкам/файлам — они не проверены.")
        if res.truncated:
            notes.append(f"Показаны {len(res.files)} крупнейших из {res.matched} найденных "
                         "(ограничение в настройках, чтобы не расходовать много памяти).")
        self.info.setText(" ".join(notes))
        self.after_search(res, value)

    def extra_values(self, res):
        return None

    def after_search(self, res, value):
        pass

    def _update_sel(self):
        files = self.table.checked_files()
        size = sum(f.size for f in files)
        self.sel_label.setText(f"Выбрано: {len(files)} · {format_size(size)}" if files else
                               "Отметьте файлы галочками. 🔒 — защищённые файлы.")
        self.trash_btn.setEnabled(bool(files) and not self.ctx.safe_mode and not self._busy)

    def _current_path(self):
        it = self.table.currentItem()
        return self.table.path_of(it) if it else None

    def _open_loc(self):
        p = self._current_path()
        if p:
            winshell.open_location(p)

    def _props(self):
        p = self._current_path()
        if p:
            self.table._properties(p)

    def _exclude_current(self):
        p = self._current_path()
        if p:
            self._exclude(p)

    def _exclude(self, path):
        self.ctx.add_exclusion(path)
        self.table.remove_paths({f.path for f in list(self.table._items.values())
                                 if f.path == path or f.path.startswith(path.rstrip("\\/") + os.sep)})
        QMessageBox.information(self, "Исключения",
                                f"Добавлено в исключения:\n{path}\n\nCleanSpace больше не будет "
                                "анализировать это место. Изменить список можно в Настройках.")

    def trash(self):
        files = self.table.checked_files()
        rows = [(f.path, f.size, "В корзину") for f in files]
        note = ("Файлы перемещаются в корзину Windows — их можно восстановить. Место на диске "
                "освободится только после очистки корзины. Перед перемещением каждый файл "
                "перепроверяется.")
        if not self.confirm("Переместить в корзину", "Выбранные файлы будут перемещены в корзину:",
                            rows, "Переместить в корзину", note):
            return
        allow = self.ctx.allow_program_files
        self.run_task(lambda c: recycle_files(files, allow, c), "Перемещение в корзину…",
                      self._trash_done, steps=True)

    def _trash_done(self, result):
        self.ctx.record(result, self.title, "Перемещение в корзину")
        self.table.remove_paths(set(result.done_paths))
        self.show_result("Готово", result)


class LargeFilesPage(FinderPage):
    key = "large"
    title = "Большие файлы"
    subtitle = "Поиск файлов, которые занимают много места"
    search_title = "Поиск больших файлов…"
    chips = [("> 100 МБ", 100 * MB), ("> 500 МБ", 500 * MB), ("> 1 ГБ", GB), ("> 5 ГБ", 5 * GB),
             ("Свой размер", None)]
    custom_suffix = " МБ"
    custom_default = 250
    default_chip = 0
    empty_hint = "Выберите порог и нажмите «Найти»."

    def __init__(self, ctx):
        super().__init__(ctx)
        ctx.large_results_ready.connect(self._from_home)

    def current_value(self):
        v = self.chip_group.value()
        return self.custom.value() * MB if v is None else v

    def make_job(self, roots, value, ex, maxr):
        return lambda c: finders.find_large(roots, value, c, ex, maxr)

    def describe(self, res, value):
        return (f"Найдено {res.matched} {plural(res.matched, 'файл', 'файла', 'файлов')} больше "
                f"{format_size(value)}, всего {format_size(res.matched_size)}. "
                "Системные файлы и файлы программ отмечены 🔒 и защищены от удаления.")

    def after_search(self, res, value):
        if not (self.task and self.task.cancelled):
            self.ctx.update_summary(large_count=res.matched, large_size=res.matched_size,
                                    large_threshold=value, large_ts=time.time())
            if res.matched:
                self.ctx.notify("large_found", "Найдены большие файлы",
                                f"{res.matched} файлов больше {format_size(value)}")

    def _from_home(self, data):
        value, res = data
        self._done(res, value)
        self.chip_group.group.button(1).setChecked(True)


class OldFilesPage(FinderPage):
    key = "old"
    title = "Старые файлы"
    subtitle = ("Файлы, которые давно не изменялись. Старый файл — не обязательно ненужный: "
                "решение всегда остаётся за вами.")
    search_title = "Поиск старых файлов…"
    chips = [("Старше 30 дней", 30), ("90 дней", 90), ("180 дней", 180), ("Года", 365),
             ("Свой период", None)]
    custom_suffix = " дн."
    custom_default = 730
    default_chip = 3
    empty_hint = "Выберите период и нажмите «Найти». Сначала показываются самые крупные файлы."

    def extra_filters(self, row):
        row.addSpacing(16)
        row.addWidget(label("не меньше", "muted"))
        self.min_size = QSpinBox()
        self.min_size.setRange(0, 100_000)
        self.min_size.setValue(1)
        self.min_size.setSuffix(" МБ")
        row.addWidget(self.min_size)

    def make_job(self, roots, value, ex, maxr):
        min_size = self.min_size.value() * MB
        return lambda c: finders.find_old(roots, value, c, ex, min_size, maxr)

    def extra_values(self, res):
        return None

    def describe(self, res, value):
        return (f"Найдено {res.matched} {plural(res.matched, 'файл', 'файла', 'файлов')}, "
                f"не изменявшихся более {value} дн., всего {format_size(res.matched_size)}. "
                "Проверьте каждый файл перед удалением — возраст не означает, что файл не нужен.")
