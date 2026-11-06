"""Поиск дубликатов: наборы одинаковых файлов (подтверждено SHA-256)."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QSpinBox, QSplitter,
                               QTreeWidget)

from ...core import disks, duplicates, protection, winshell
from ...core.utils import IMAGE_PREVIEW_EXT, format_datetime, format_size, num, plural
from ..theme import Theme
from ..widgets import Banner, Card, SizeItem, button, label
from .base import BasePage

PATH_ROLE = Qt.UserRole + 1
GROUP_ROLE = Qt.UserRole + 2


class DuplicatesPage(BasePage):
    key = "dupes"
    title = "Дубликаты"
    subtitle = ("Одинаковые файлы определяются по содержимому (SHA-256), а не по имени. "
                "В каждом наборе всегда остаётся хотя бы одна копия.")

    def __init__(self, ctx):
        super().__init__(ctx)
        row = QHBoxLayout()
        row.addWidget(label("Где искать:", "muted"))
        self.where = QComboBox()
        self.where.setMinimumWidth(240)
        row.addWidget(self.where)
        pick = button("Папка…", "folder")
        pick.clicked.connect(self._pick)
        row.addWidget(pick)
        row.addWidget(label("мин. размер", "muted"))
        self.min_kb = QSpinBox()
        self.min_kb.setRange(1, 10_000_000)
        self.min_kb.setValue(int(ctx.setting("dup_min_size_kb") or 1))
        self.min_kb.setSuffix(" КБ")
        row.addWidget(self.min_kb)
        row.addStretch(1)
        self.search_btn = button("Найти дубликаты", "search", "accent")
        self.search_btn.clicked.connect(self.search)
        row.addWidget(self.search_btn)
        self.lay.addLayout(row)

        self.info = Banner("", "info")
        self.info.hide()
        self.lay.addWidget(self.info)
        self.summary = label("Выберите папку или диск и нажмите «Найти дубликаты».", "muted", wrap=True)
        self.lay.addWidget(self.summary)

        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Файл", "Размер", "Изменён", "Расположение"])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(QHeaderView.Interactive)
        self.tree.header().setStretchLastSection(True)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 130)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(self._preview)
        self.tree.itemDoubleClicked.connect(self._open_item)
        split.addWidget(self.tree)

        prev = Card(margins=12, spacing=8)
        prev.lay.addWidget(label("Предпросмотр", "h2"))
        self.preview = QLabel("Выберите файл")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(220, 200)
        self.preview.setProperty("role", "muted")
        prev.lay.addWidget(self.preview, 1)
        self.prev_info = label("", "muted", wrap=True)
        self.prev_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        prev.lay.addWidget(self.prev_info)
        split.addWidget(prev)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([760, 280])
        self.lay.addWidget(split, 1)

        act = QHBoxLayout()
        self.sel_label = label("", "muted")
        act.addWidget(self.sel_label, 1)
        self.auto_btn = button("Автовыбор копий", "check",
                               tooltip="Отмечает лишние копии только в личных папках "
                                       "(Документы, Изображения, Видео, Музыка, Рабочий стол, "
                                       "Загрузки). Самая старая копия остаётся.")
        self.auto_btn.clicked.connect(self.auto_select)
        act.addWidget(self.auto_btn)
        b = button("Снять выбор")
        b.clicked.connect(lambda: self._check_all(set()))
        act.addWidget(b)
        b = button("Открыть расположение", "open")
        b.clicked.connect(lambda: self._open_item(self.tree.currentItem()))
        act.addWidget(b)
        self.trash_btn = button("Выбранные в корзину…", "delete", "danger")
        self.trash_btn.clicked.connect(self.trash)
        act.addWidget(self.trash_btn)
        self.lay.addLayout(act)

        self.groups: list[duplicates.DuplicateGroup] = []
        self._mute = False
        self._busy = False
        self._fill_where()
        ctx.settings_changed.connect(lambda k: self._fill_where() if k == "scan_folders" else None)
        self._update_sel()

    def _fill_where(self):
        self.where.clear()
        roots = self.ctx.scan_roots()
        self.where.addItem("Выбранные папки: " + "; ".join(roots), roots)
        for d in disks.list_disks():
            self.where.addItem(f"Весь диск {d.name}", [d.mountpoint])

    def _pick(self):
        p = self.pick_folder()
        if p:
            p = os.path.normpath(p)
            self.where.insertItem(0, f"Папка: {p}", [p])
            self.where.setCurrentIndex(0)

    def set_busy(self, busy):
        self._busy = busy
        self.search_btn.setEnabled(not busy)
        self.auto_btn.setEnabled(not busy)
        self._update_sel()

    def on_safe_mode(self, safe):
        if hasattr(self, "trash_btn"):
            self._update_sel()

    def search(self):
        roots = self.where.currentData() or self.ctx.scan_roots()
        min_size = self.min_kb.value() * 1024
        self.ctx.set_setting("dup_min_size_kb", self.min_kb.value())
        ex = self.ctx.exclusions()
        maxg = self.ctx.max_results
        self.run_task(lambda c: duplicates.find_duplicates(roots, c, ex, min_size, maxg),
                      "Поиск дубликатов…", self._done, steps=True)

    def _done(self, res: duplicates.DuplicateResult):
        self.groups = res.groups
        self._fill_tree()
        cancelled = self.task and self.task.cancelled
        n = len(res.groups)
        self.summary.setText(
            f"Найдено {n} {plural(n, 'набор', 'набора', 'наборов')} одинаковых файлов. "
            f"Можно освободить до {format_size(res.wasted)}, если оставить по одной копии. "
            f"Проверено файлов: {num(res.stats.files)}.")
        notes = []
        if cancelled:
            notes.append("Поиск остановлен — найдены не все дубликаты.")
        if res.stats.errors or res.hash_errors:
            notes.append(f"Не удалось прочитать {res.stats.errors + res.hash_errors} объектов — "
                         "они пропущены.")
        if res.skipped_cloud:
            notes.append(f"Файлы OneDrive «только в облаке» ({res.skipped_cloud}) не проверялись, "
                         "чтобы не скачивать их.")
        self.info.setText(" ".join(notes))
        if not cancelled:
            self.ctx.update_summary(dup_groups=n, dup_wasted=res.wasted, dup_ts=time.time())

    def _fill_tree(self):
        self._mute = True
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        allow = self.ctx.allow_program_files
        for gi, g in enumerate(self.groups):
            name = os.path.basename(g.files[0].path)
            top = SizeItem([f"{name}  ·  {g.copies} {plural(g.copies, 'копия', 'копии', 'копий')}",
                            format_size(g.size), "", f"можно освободить {format_size(g.wasted)}"])
            top.setData(1, Qt.UserRole, g.wasted)
            top.setData(0, GROUP_ROLE, gi)
            top.setFirstColumnSpanned(False)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            for fi in g.files:
                ch = SizeItem([os.path.basename(fi.path), format_size(fi.size),
                               format_datetime(fi.mtime), os.path.dirname(fi.path)])
                ch.setData(0, PATH_ROLE, fi.path)
                ch.setData(0, GROUP_ROLE, gi)
                ch.setToolTip(3, fi.path)
                ok, why = protection.can_remove(fi.path, allow)
                level = protection.classify(fi.path)
                if ok:
                    ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
                    ch.setCheckState(0, Qt.Unchecked)
                    if level != protection.PERSONAL:
                        ch.setToolTip(0, f"{protection.LEVEL_NAMES[level]} — автоматически не выбирается")
                else:
                    ch.setText(0, "🔒 " + ch.text(0))
                    ch.setToolTip(0, why)
                    for c in range(4):
                        ch.setForeground(c, Theme.color("faint"))
                top.addChild(ch)
            self.tree.addTopLevelItem(top)
            if gi < 30:
                top.setExpanded(True)
        self.tree.setUpdatesEnabled(True)
        self._mute = False
        self._update_sel()

    def _children(self, top):
        return [top.child(i) for i in range(top.childCount())]

    def _item_changed(self, item, col):
        if self._mute or col != 0 or item.data(0, PATH_ROLE) is None:
            return
        top = item.parent()
        if item.checkState(0) == Qt.Checked and all(
                c.checkState(0) == Qt.Checked or not (c.flags() & Qt.ItemIsUserCheckable)
                for c in self._children(top)):
            # нельзя выбрать все копии набора — хотя бы одна должна остаться
            checkable_unchecked = [c for c in self._children(top)
                                   if c.flags() & Qt.ItemIsUserCheckable and c.checkState(0) != Qt.Checked]
            protected_left = [c for c in self._children(top)
                              if not (c.flags() & Qt.ItemIsUserCheckable)]
            if not checkable_unchecked and not protected_left:
                self._mute = True
                item.setCheckState(0, Qt.Unchecked)
                self._mute = False
                self.sel_label.setText("⚠ В каждом наборе должна остаться хотя бы одна копия.")
                return
        self._update_sel()

    def selected_paths(self) -> set[str]:
        out = set()
        for i in range(self.tree.topLevelItemCount()):
            for c in self._children(self.tree.topLevelItem(i)):
                if c.flags() & Qt.ItemIsUserCheckable and c.checkState(0) == Qt.Checked:
                    out.add(c.data(0, PATH_ROLE))
        return out

    def _update_sel(self):
        sel = self.selected_paths()
        size = 0
        for g in self.groups:
            size += sum(f.size for f in g.files if f.path in sel)
        self.sel_label.setText(f"Выбрано копий: {len(sel)} · {format_size(size)}" if sel else
                               "Отметьте лишние копии. 🔒 — защищённые файлы.")
        self.trash_btn.setEnabled(bool(sel) and not self.ctx.safe_mode and not self._busy)

    def _check_all(self, paths: set[str]):
        self._mute = True
        for i in range(self.tree.topLevelItemCount()):
            for c in self._children(self.tree.topLevelItem(i)):
                if c.flags() & Qt.ItemIsUserCheckable:
                    c.setCheckState(0, Qt.Checked if c.data(0, PATH_ROLE) in paths else Qt.Unchecked)
        self._mute = False
        self._update_sel()

    def auto_select(self):
        paths = set()
        for g in self.groups:
            paths |= {f.path for f in duplicates.auto_select(g)}
        self._check_all(paths)
        if not paths and self.groups:
            self.sel_label.setText("Автовыбор не нашёл копий в личных папках — выберите вручную.")

    def _preview(self, cur, _prev):
        path = cur.data(0, PATH_ROLE) if cur else None
        if not path:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Выберите файл")
            self.prev_info.setText("")
            return
        ext = os.path.splitext(path)[1].lower()
        shown = False
        if ext in IMAGE_PREVIEW_EXT:
            try:
                if os.path.getsize(path) < 60 * 1024 * 1024:
                    pm = QPixmap(path)
                    if not pm.isNull():
                        self.preview.setPixmap(pm.scaled(self.preview.width() - 8, 260,
                                                         Qt.KeepAspectRatio, Qt.SmoothTransformation))
                        shown = True
            except OSError:
                pass
        if not shown:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Предпросмотр недоступен\nдля этого типа файлов")
        g = self.groups[cur.data(0, GROUP_ROLE)]
        self.prev_info.setText(f"{path}\n\nЗащита: {protection.LEVEL_NAMES[protection.classify(path)]}"
                               f"\nSHA-256: {g.sha256[:32]}…")

    def _open_item(self, item, _col=None):
        if item and item.data(0, PATH_ROLE):
            winshell.open_location(item.data(0, PATH_ROLE))

    def trash(self):
        sel = self.selected_paths()
        rows = []
        for g in self.groups:
            keep = [f for f in g.files if f.path not in sel]
            for f in g.files:
                if f.path in sel:
                    rows.append((f.path, f.size, f"В корзину (остаётся: {os.path.basename(keep[0].path)})"
                                 if keep else "В корзину"))
        note = ("Перед перемещением CleanSpace заново проверит SHA-256 каждой копии и убедится, "
                "что оставляемая копия на месте и не изменилась. Место освободится после очистки "
                "корзины.")
        if not self.confirm("Дубликаты в корзину", "Будут перемещены в корзину следующие копии:",
                            rows, "Переместить в корзину", note):
            return
        groups = list(self.groups)
        allow = self.ctx.allow_program_files
        self.run_task(lambda c: duplicates.remove_duplicates(groups, sel, allow, c),
                      "Перемещение дубликатов в корзину…", self._trash_done, steps=True)

    def _trash_done(self, result):
        self.ctx.record(result, "Дубликаты", "Перемещение копий в корзину")
        done = set(result.done_paths)
        new_groups = []
        for g in self.groups:
            files = [f for f in g.files if f.path not in done]
            if len(files) > 1:
                new_groups.append(duplicates.DuplicateGroup(g.sha256, g.size, files))
        self.groups = new_groups
        self._fill_tree()
        self.show_result("Готово", result)
