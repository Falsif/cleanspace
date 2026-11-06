"""Анализ дисков: дерево папок, Treemap, распределение по типам файлов."""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QSplitter,
                               QStyledItemDelegate, QTreeWidget, QVBoxLayout, QWidget)

from ...core import analyzer, disks, winshell
from ...core.utils import (CATEGORY_COLORS, CATEGORY_ORDER, category_name, format_size, norm,
                           num, plural)
from ..theme import Theme
from ..widgets import Banner, Card, Legend, SizeItem, StackedBar, Treemap, button, label
from .base import BasePage

NODE_ROLE = Qt.UserRole + 5
PATH_ROLE = Qt.UserRole + 6


class PercentDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)
        pct = index.data(Qt.UserRole)
        if pct is None:
            return
        r = option.rect.adjusted(6, option.rect.height() // 2 - 3, -44, -(option.rect.height() // 2 - 3))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), 3, 3)
        painter.fillPath(path, Theme.color("track"))
        w = r.width() * max(0.0, min(1.0, pct / 100))
        if w > 0:
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(r.x(), r.y(), max(w, 3), r.height()), 3, 3)
            painter.fillPath(fill, QColor(Theme.c["accent"] if pct < 50 else Theme.c["purple"]))
        painter.setPen(Theme.color("muted"))
        painter.drawText(option.rect.adjusted(0, 0, -4, 0), Qt.AlignRight | Qt.AlignVCenter,
                         f"{pct:.1f}%")
        painter.restore()

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = ""


class AnalyzerPage(BasePage):
    key = "analyze"
    title = "Анализ дисков"
    subtitle = "Узнайте, какие папки и файлы занимают больше всего места"

    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.target = QComboBox()
        self.target.setMinimumWidth(260)
        bar.addWidget(self.target)
        pick = button("Выбрать папку…", "folder")
        pick.clicked.connect(self._pick)
        bar.addWidget(pick)
        self.scan_btn = button("Сканировать", "search", "accent")
        self.scan_btn.clicked.connect(self.scan)
        bar.addWidget(self.scan_btn)
        bar.addStretch(1)
        self.open_btn = button("Открыть в Проводнике", "open")
        self.open_btn.clicked.connect(self._open_selected)
        self.open_btn.setEnabled(False)
        bar.addWidget(self.open_btn)
        self.lay.addLayout(bar)

        self.coverage = Banner("", "warning")
        self.coverage.hide()
        self.lay.addWidget(self.coverage)
        self.summary = label("Выберите диск или папку и нажмите «Сканировать».", "muted", wrap=True)
        self.lay.addWidget(self.summary)

        split = QSplitter(Qt.Horizontal)
        # дерево
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Папка / файл", "Размер", "Доля", "Файлов"])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(False)
        self.tree.setItemDelegateForColumn(2, PercentDelegate(self.tree))
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(1, 85)
        self.tree.setColumnWidth(2, 120)
        self.tree.setColumnWidth(3, 70)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.currentItemChanged.connect(self._tree_selected)
        self.tree.itemDoubleClicked.connect(lambda it, _c: winshell.open_location(it.data(0, PATH_ROLE)))
        split.addWidget(self.tree)
        # Treemap + категории
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.setSpacing(8)
        crumb = QHBoxLayout()
        self.up_btn = button("Вверх", "up")
        self.up_btn.clicked.connect(self._go_up)
        self.up_btn.setEnabled(False)
        crumb.addWidget(self.up_btn)
        self.crumb = label("", "muted")
        self.crumb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        crumb.addWidget(self.crumb, 1)
        rl.addLayout(crumb)
        self.treemap = Treemap()
        self.treemap.item_clicked.connect(self._map_clicked)
        self.treemap.item_activated.connect(self._map_activated)
        rl.addWidget(self.treemap, 1)
        cat_card = Card(margins=12, spacing=8)
        cat_card.lay.addWidget(label("Типы файлов", "h2"))
        self.cat_bar = StackedBar()
        cat_card.lay.addWidget(self.cat_bar)
        self.legend = Legend()
        cat_card.lay.addWidget(self.legend)
        rl.addWidget(cat_card)
        split.addWidget(right)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 6)
        split.setSizes([480, 560])
        self.lay.addWidget(split, 1)

        self.result: analyzer.AnalysisResult | None = None
        self.current: analyzer.DirNode | None = None
        self.selected_path: str | None = None
        self._fill_targets()
        ctx.settings_changed.connect(lambda k: self._fill_targets() if k == "scan_folders" else None)
        ctx.analyze_path.connect(self.analyze_path)

    def _fill_targets(self):
        self.target.clear()
        for d in disks.list_disks():
            self.target.addItem(f"Диск {d.name} — свободно {format_size(d.free)} из "
                                f"{format_size(d.total)}", d.mountpoint)
        for r in self.ctx.scan_roots():
            self.target.addItem(f"Папка: {r}", r)

    def _pick(self):
        path = self.pick_folder(self.target.currentData() or "")
        if path:
            path = os.path.normpath(path)
            self.target.insertItem(0, f"Папка: {path}", path)
            self.target.setCurrentIndex(0)

    def analyze_path(self, path: str):
        idx = self.target.findData(path)
        if idx < 0:
            self.target.insertItem(0, f"Папка: {path}", path)
            idx = 0
        self.target.setCurrentIndex(idx)
        self.ctx.navigate.emit(self.key)
        if not self.busy:
            self.scan()

    def set_busy(self, busy: bool) -> None:
        self.scan_btn.setEnabled(not busy)
        self.target.setEnabled(not busy)

    def scan(self):
        path = self.target.currentData()
        if not path or not os.path.isdir(path):
            self.summary.setText("Папка не найдена.")
            return
        disk_used = None
        for d in disks.list_disks():
            if norm(d.mountpoint) == norm(path):
                disk_used = d.used
        ex = self.ctx.exclusions()
        self.coverage.hide()
        self.run_task(lambda c: analyzer.analyze(path, c, ex, disk_used),
                      f"Анализ: {path}", self._done)

    def _done(self, res: analyzer.AnalysisResult):
        self.result = res
        st = res.stats
        state = "Анализ завершён полностью." if res.complete else "Анализ НЕПОЛНЫЙ."
        self.summary.setText(
            f"{state} Учтено {format_size(res.root.size)} в {num(st.files)} файлах и {num(st.dirs)} папках "
            f"за {res.duration:.1f} с.")
        note = res.coverage_note()
        self.coverage.setText(note)
        self.coverage.setVisible(bool(note) and (not res.complete or bool(res.disk_used)))
        self._build_tree()
        self._show_dir(res.root)
        self._show_categories()

    # --- дерево ---
    def _make_item(self, node: analyzer.DirNode, parent_size: int) -> SizeItem:
        name = node.name if node.parent else node.path
        it = SizeItem(["📁 " + name if not node.error else "🔒 " + name, format_size(node.size), "",
                       num(node.total_files)])
        it.setData(0, NODE_ROLE, node)
        it.setData(0, PATH_ROLE, node.path)
        it.setData(1, Qt.UserRole, node.size)
        it.setData(2, Qt.UserRole, (node.size / parent_size * 100) if parent_size else 100.0)
        if node.error:
            it.setToolTip(0, "Нет доступа к содержимому папки")
        else:
            it.setToolTip(0, node.path)
        if node.children or node.top_files:
            it.setChildIndicatorPolicy(SizeItem.ShowIndicator)
        return it

    def _build_tree(self):
        self.tree.clear()
        root = self.result.root
        it = self._make_item(root, root.size)
        self.tree.addTopLevelItem(it)
        it.setExpanded(True)
        self.tree.setCurrentItem(it)

    def _expand(self, item):
        if item.childCount() or item.data(0, NODE_ROLE) is None:
            return
        node: analyzer.DirNode = item.data(0, NODE_ROLE)
        base = node.size or 1
        kids = []
        for c in node.sorted_children()[:300]:
            kids.append(self._make_item(c, base))
        for size, name, _m in node.sorted_files()[:100]:
            f = SizeItem(["    " + name, format_size(size), "", ""])
            path = os.path.join(node.path, name)
            f.setData(0, PATH_ROLE, path)
            f.setToolTip(0, path)
            f.setData(1, Qt.UserRole, size)
            f.setData(2, Qt.UserRole, size / base * 100)
            kids.append(f)
        if node.other_count:
            o = SizeItem([f"    … ещё {node.other_count} мелких файлов", format_size(node.other_size), "", ""])
            o.setData(2, Qt.UserRole, node.other_size / base * 100)
            kids.append(o)
        item.addChildren(kids)

    def _tree_selected(self, cur, _prev):
        if not cur:
            return
        self.selected_path = cur.data(0, PATH_ROLE)
        self.open_btn.setEnabled(bool(self.selected_path))
        node = cur.data(0, NODE_ROLE)
        if node is not None and node is not self.current:
            self._show_dir(node)

    # --- Treemap ---
    def _show_dir(self, node: analyzer.DirNode):
        self.current = node
        self.treemap.set_items(analyzer.treemap_items(node))
        self.crumb.setText(f"{node.path}  ·  {format_size(node.size)}")
        self.up_btn.setEnabled(node.parent is not None)
        self.selected_path = node.path
        self.open_btn.setEnabled(True)

    def _go_up(self):
        if self.current and self.current.parent:
            self._show_dir(self.current.parent)

    def _map_clicked(self, item: dict):
        if item["kind"] == "file":
            self.selected_path = os.path.join(item["node"].path, item["name"])
        elif item["kind"] == "dir":
            self.selected_path = item["node"].path
        self.open_btn.setEnabled(bool(self.selected_path))
        self.crumb.setText(f"{self.selected_path}  ·  {format_size(item['size'])}")

    def _map_activated(self, item: dict):
        if item["kind"] == "dir":
            self._show_dir(item["node"])
        elif item["kind"] == "file":
            winshell.open_location(os.path.join(item["node"].path, item["name"]))

    def _open_selected(self):
        if self.selected_path:
            winshell.open_location(self.selected_path)

    def _show_categories(self):
        cats = self.result.categories
        total = sum(v[0] for v in cats.values()) or 1
        segs, items = [], []
        for k in CATEGORY_ORDER:
            size, count = cats.get(k, [0, 0])
            color = CATEGORY_COLORS[k]
            segs.append((size, color, f"{category_name(k)}: {format_size(size)} ({count} файлов)"))
            items.append((color, f"{category_name(k)} · {num(count)} " + plural(count, "файл", "файла", "файлов"),
                          f"{format_size(size)}  ({size / total * 100:.1f}%)"))
        self.cat_bar.set_segments(segs)
        self.legend.set_items(items)
