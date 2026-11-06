"""Менеджер папки «Загрузки»."""
from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QMessageBox

from ...core import downloads, winshell
from ...core.cleaner import move_files, recycle_files
from ...core.utils import CATEGORY_COLORS, CATEGORY_ORDER, category_name, format_size
from ..file_table import FileTable
from ..widgets import Banner, Card, ChipGroup, Legend, StackedBar, button, label
from .base import BasePage

VIEWS = [("Все файлы", "all"), ("Старые установщики", "installers"), ("Архивы", "archives"),
         ("Повторные загрузки", "redownloads")]


class DownloadsPage(BasePage):
    key = "downloads"
    title = "Загрузки"
    subtitle = "Порядок в папке «Загрузки». Ничего не перемещается и не удаляется без подтверждения."

    def __init__(self, ctx):
        super().__init__(ctx)
        top = QHBoxLayout()
        self.folder = downloads.downloads_folder()
        self.folder_label = label(f"Папка: {self.folder}", "muted")
        top.addWidget(self.folder_label, 1)
        b = button("Открыть папку", "open")
        b.clicked.connect(lambda: winshell.open_location(self.folder))
        top.addWidget(b)
        self.refresh_btn = button("Проверить", "refresh", "accent")
        self.refresh_btn.clicked.connect(self.scan)
        top.addWidget(self.refresh_btn)
        self.lay.addLayout(top)

        stats = Card(margins=12, spacing=8)
        self.stats_title = label("Нажмите «Проверить», чтобы увидеть содержимое папки.", "h2")
        stats.lay.addWidget(self.stats_title)
        self.bar = StackedBar()
        stats.lay.addWidget(self.bar)
        self.legend = Legend()
        self.legend.lay.setSpacing(3)
        stats.lay.addWidget(self.legend)
        self.lay.addWidget(stats)
        self.tips = Banner("", "info")
        self.tips.hide()
        self.lay.addWidget(self.tips)

        frow = QHBoxLayout()
        self.view = ChipGroup(VIEWS)
        self.view.changed.connect(lambda _: self._apply_view())
        frow.addWidget(self.view, 1)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Поиск по имени…")
        self.filter.setMaximumWidth(260)
        self.filter.textChanged.connect(lambda t: self.table.filter_text(t))
        frow.addWidget(self.filter)
        self.lay.addLayout(frow)

        self.table = FileTable(ctx, checkable=True, extra_column="Пометка")
        self.table.checked_changed.connect(self._update_sel)
        self.table.exclude_requested.connect(self._exclude)
        self.lay.addWidget(self.table, 1)

        act = QHBoxLayout()
        self.sel_label = label("", "muted")
        act.addWidget(self.sel_label, 1)
        b = button("Выбрать все")
        b.clicked.connect(lambda: self.table.set_all_checked(True))
        act.addWidget(b)
        b = button("Снять выбор")
        b.clicked.connect(lambda: self.table.set_all_checked(False))
        act.addWidget(b)
        self.sort_btn = button("Разложить по папкам…", "sort")
        self.sort_btn.setToolTip("Предложить раскладку по типам: Видео, Изображения, Документы, "
                                 "Архивы, Установщики… Сначала покажет точный список изменений.")
        self.sort_btn.clicked.connect(self.sort_into_folders)
        act.addWidget(self.sort_btn)
        self.move_btn = button("Переместить в…", "move")
        self.move_btn.clicked.connect(self.move_to)
        act.addWidget(self.move_btn)
        self.trash_btn = button("В корзину…", "delete", "danger")
        self.trash_btn.clicked.connect(self.trash)
        act.addWidget(self.trash_btn)
        self.lay.addLayout(act)

        self.report: downloads.DownloadsReport | None = None
        self._busy = False
        self._update_sel()

    def on_show(self):
        if self.report is None and not self.busy:
            self.scan()

    def set_busy(self, busy):
        self._busy = busy
        self.refresh_btn.setEnabled(not busy)
        self._update_sel()

    def on_safe_mode(self, safe):
        if hasattr(self, "trash_btn"):
            self._update_sel()

    def scan(self):
        folder = self.folder
        self.run_task(lambda c: downloads.scan_downloads(folder, c), "Анализ папки «Загрузки»…",
                      self._done)

    def _done(self, rep: downloads.DownloadsReport):
        self.report = rep
        by = rep.by_category()
        total = rep.total_size or 1
        self.stats_title.setText(f"{len(rep.files)} файлов · {format_size(rep.total_size)}")
        segs, items = [], []
        for k in CATEGORY_ORDER:
            size, cnt = by.get(k, (0, 0))
            if cnt:
                segs.append((size, CATEGORY_COLORS[k], f"{category_name(k)}: {format_size(size)}"))
                items.append((CATEGORY_COLORS[k], f"{category_name(k)} · {cnt}",
                              f"{format_size(size)} ({size / total * 100:.0f}%)"))
        self.bar.set_segments(segs)
        self.legend.set_items(items)
        tips = []
        if rep.old_installers:
            tips.append(f"Старых установщиков (старше 30 дней): {len(rep.old_installers)}, "
                        f"{format_size(sum(f.size for f in rep.old_installers))} — обычно после "
                        "установки программы они не нужны.")
        ident = [r for r in rep.redownloads if r[2]]
        if rep.redownloads:
            tips.append(f"Повторно скачанных файлов: {len(rep.redownloads)} групп"
                        f"{f', из них полностью одинаковых: {len(ident)}' if ident else ''}.")
        if rep.archives:
            tips.append(f"Архивов: {len(rep.archives)} — если они уже распакованы, их можно убрать.")
        self.tips.setText(" ".join(tips))
        self._marks = {}
        for f in rep.old_installers:
            self._marks[f.path] = "Старый установщик"
        for f in rep.archives:
            self._marks.setdefault(f.path, "Архив")
        for base, items, same in rep.redownloads:
            for i, f in enumerate(items):
                self._marks[f.path] = ("Оригинал" if i == 0 else "Повтор") + \
                                      (" · идентичен" if same else " · отличается")
        self._apply_view()

    def _apply_view(self):
        if not self.report:
            return
        rep = self.report
        mode = self.view.value()
        if mode == "installers":
            files = rep.old_installers
        elif mode == "archives":
            files = rep.archives
        elif mode == "redownloads":
            files = [f for _b, items, _s in rep.redownloads for f in items]
        else:
            files = [e.item for e in rep.files]
        self.table.set_files(files, self._marks)
        if mode == "redownloads":
            self.table.sortItems(0, self.table.header().sortIndicatorOrder())
        self.table.filter_text(self.filter.text())

    def _update_sel(self):
        files = self.table.checked_files()
        self.sel_label.setText(f"Выбрано: {len(files)} · {format_size(sum(f.size for f in files))}"
                               if files else "Отметьте файлы галочками.")
        can = not self.ctx.safe_mode and not self._busy
        self.trash_btn.setEnabled(bool(files) and can)
        self.move_btn.setEnabled(bool(files) and can)
        self.sort_btn.setEnabled(self.report is not None and bool(self.report.files) and can)

    def _exclude(self, path):
        self.ctx.add_exclusion(path)
        QMessageBox.information(self, "Исключения", f"Добавлено в исключения:\n{path}")

    def sort_into_folders(self):
        root = self.ctx.setting("downloads_sort_root") or self.folder
        checked = self.table.checked_files()
        rep = self.report
        plan = downloads.sort_plan(rep, root)
        if checked:
            paths = {f.path for f in checked}
            plan = [(i, d) for i, d in plan if i.path in paths]
        rows = [(i.path, i.size, os.path.relpath(d, root) if d.startswith(root) else d)
                for i, d in plan]
        intro = (f"Файлы будут разложены по подпапкам внутри «{root}». "
                 + ("Только отмеченные файлы." if checked else "Все файлы папки «Загрузки».")
                 + " Существующие файлы не перезаписываются — при совпадении имён добавится номер.")
        if not self.confirm("Сортировка «Загрузок»", intro, rows, "Переместить", danger=False,
                            target_header="Новая папка"):
            return
        allow = self.ctx.allow_program_files
        self.run_task(lambda c: move_files(plan, allow, c), "Сортировка файлов…",
                      lambda r: self._op_done(r, "Сортировка по папкам"), steps=True)

    def move_to(self):
        files = self.table.checked_files()
        dest = QFileDialog.getExistingDirectory(self, "Куда переместить выбранные файлы?",
                                                self.folder)
        if not dest:
            return
        dest = os.path.normpath(dest)
        rows = [(f.path, f.size, dest) for f in files]
        if not self.confirm("Перемещение файлов", "Выбранные файлы будут перемещены:", rows,
                            "Переместить", danger=False, target_header="Куда"):
            return
        allow = self.ctx.allow_program_files
        plan = [(f, dest) for f in files]
        self.run_task(lambda c: move_files(plan, allow, c), "Перемещение файлов…",
                      lambda r: self._op_done(r, "Перемещение в папку"), steps=True)

    def trash(self):
        files = self.table.checked_files()
        rows = [(f.path, f.size, "В корзину") for f in files]
        if not self.confirm("Переместить в корзину", "Выбранные файлы будут перемещены в корзину:",
                            rows, "Переместить в корзину",
                            "Файлы можно восстановить из корзины. Место освободится после её очистки."):
            return
        allow = self.ctx.allow_program_files
        self.run_task(lambda c: recycle_files(files, allow, c), "Перемещение в корзину…",
                      lambda r: self._op_done(r, "Перемещение в корзину"), steps=True)

    def _op_done(self, result, action):
        self.ctx.record(result, "Загрузки", action)
        self.show_result("Готово", result)
        self.scan()
