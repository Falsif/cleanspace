"""История очистки и отчёты за неделю и месяц."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QMessageBox,
                               QTreeWidget, QWidget)

from ...core.utils import format_datetime, format_size
from ..widgets import BarChart, Card, SizeItem, button, label
from .base import BasePage


class ReportCard(Card):
    def __init__(self, title: str):
        super().__init__(margins=14, spacing=4)
        self.lay.addWidget(label(title, "muted"))
        self.freed = label("—", "big")
        self.lay.addWidget(self.freed)
        self.details = label("", "faint", wrap=True)
        self.lay.addWidget(self.details)

    def set(self, r: dict):
        self.freed.setText(format_size(r["freed"]))
        self.details.setText(
            f"освобождено на диске · операций: {r['operations']} · файлов: {r['processed']}\n"
            f"в корзину: {format_size(r['recycled'])} · перемещено: {format_size(r['moved'])} · "
            f"ошибок: {r['failed']}")


class HistoryPage(BasePage):
    key = "history"
    title = "История очистки"
    subtitle = ("Журнал всех действий. Освобождённым считается только окончательно удалённое; "
                "перемещение в корзину учитывается отдельно.")

    def __init__(self, ctx):
        super().__init__(ctx)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.week = ReportCard("Отчёт за неделю")
        self.month = ReportCard("Отчёт за месяц")
        grid.addWidget(self.week, 0, 0)
        grid.addWidget(self.month, 0, 1)
        chart_card = Card(margins=14, spacing=6)
        chart_card.lay.addWidget(label("Освобождено по дням (30 дней)", "h2"))
        self.chart = BarChart()
        self.chart.setMinimumHeight(140)
        chart_card.lay.addWidget(self.chart)
        grid.addWidget(chart_card, 0, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)
        w = QWidget()
        w.setLayout(grid)
        self.lay.addWidget(w)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Дата и время", "Категория", "Действие", "Файлов", "Ошибок",
                                   "Освобождено", "В корзину", "Перемещено"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.header().setSectionResizeMode(QHeaderView.Interactive)
        for i, wdt in enumerate([150, 270, 200, 70, 70, 105, 95, 95]):
            self.tree.setColumnWidth(i, wdt)
        self.lay.addWidget(self.tree, 1)

        act = QHBoxLayout()
        act.addWidget(label("Разверните запись, чтобы увидеть причины ошибок.", "faint"), 1)
        b = button("Экспорт в CSV…", "export")
        b.clicked.connect(self.export)
        act.addWidget(b)
        b = button("Очистить журнал", "delete")
        b.clicked.connect(self.clear)
        act.addWidget(b)
        self.lay.addLayout(act)
        ctx.history_changed.connect(self.refresh)
        self.refresh()

    def on_show(self):
        self.refresh()

    def refresh(self):
        s = self.ctx.storage
        self.week.set(s.report(7))
        self.month.set(s.report(30))
        data = []
        for day, freed in s.daily_freed(30):
            data.append((time.strftime("%d.%m", time.localtime(day)), freed,
                         f"{time.strftime('%d.%m.%Y', time.localtime(day))}: {format_size(freed)}"))
        self.chart.set_data(data)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for r in s.history(limit=2000):
            it = SizeItem([format_datetime(r.ts), r.category, r.action, str(r.processed),
                           str(r.failed), format_size(r.freed_bytes) if r.freed_bytes else "—",
                           format_size(r.recycled_bytes) if r.recycled_bytes else "—",
                           format_size(r.moved_bytes) if r.moved_bytes else "—"])
            for col, val in ((0, r.ts), (3, r.processed), (4, r.failed), (5, r.freed_bytes),
                             (6, r.recycled_bytes), (7, r.moved_bytes)):
                it.setData(col, Qt.UserRole, val)
            it.setToolTip(1, r.category)
            for e in r.errors:
                ch = SizeItem(["", e])
                ch.setFirstColumnSpanned(False)
                ch.setToolTip(1, e)
                it.addChild(ch)
            self.tree.addTopLevelItem(it)
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(0, Qt.DescendingOrder)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчёт", "CleanSpace_история.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        try:
            n = self.ctx.storage.export_history_csv(path)
            QMessageBox.information(self, "Экспорт", f"Сохранено записей: {n}\n{path}")
        except OSError as exc:
            QMessageBox.warning(self, "Экспорт", f"Не удалось сохранить файл:\n{exc}")

    def clear(self):
        if QMessageBox.question(self, "Очистить журнал",
                                "Удалить все записи истории? Сами файлы это не затронет.") \
                == QMessageBox.Yes:
            self.ctx.storage.clear_history()
            self.ctx.history_changed.emit()
