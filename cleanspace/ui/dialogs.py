"""Диалоги: предварительный просмотр операций, список файлов, итоги."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QTreeWidget, QVBoxLayout)

from ..core import protection
from ..core.cleaner import OperationResult
from ..core.utils import format_datetime, format_size
from .widgets import Banner, SizeItem, button, label


def _tree(columns: list[str]) -> QTreeWidget:
    t = QTreeWidget()
    t.setHeaderLabels(columns)
    t.setRootIsDecorated(False)
    t.setAlternatingRowColors(True)
    t.setUniformRowHeights(True)
    t.setSortingEnabled(True)
    t.header().setSectionResizeMode(0, QHeaderView.Interactive)
    t.header().setStretchLastSection(True)
    return t


class ConfirmDialog(QDialog):
    """Точный список операций перед подтверждением.

    rows: [(путь, размер, куда/примечание)]
    """

    def __init__(self, parent, title: str, intro: str, rows: list[tuple[str, int, str]],
                 action_text: str, note: str = "", danger: bool = True,
                 target_header: str = "Действие"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)
        lay.addWidget(label(title, "h2"))
        lay.addWidget(label(intro, "muted", wrap=True))
        total = sum(r[1] for r in rows)
        lay.addWidget(label(f"Объектов: {len(rows)} · Общий размер: {format_size(total)}"))
        risky = [r for r in rows if protection.classify(r[0]) == protection.PROGRAM]
        tree = _tree(["Файл", "Размер", target_header, "Папка"])
        tree.setSortingEnabled(False)
        shown = rows[:20000]
        for path, size, target in shown:
            it = SizeItem([os.path.basename(path) or path, format_size(size), target,
                           os.path.dirname(path)])
            it.setData(1, Qt.UserRole, size)
            it.setToolTip(3, path)
            tree.addTopLevelItem(it)
        tree.setSortingEnabled(True)
        tree.setColumnWidth(0, 260)
        tree.setColumnWidth(1, 90)
        tree.setColumnWidth(2, 180)
        lay.addWidget(tree, 1)
        if len(rows) > len(shown):
            lay.addWidget(label(f"Показаны первые {len(shown)} из {len(rows)}.", "faint"))
        if note:
            lay.addWidget(Banner(note, "info"))
        self.ack = None
        if risky:
            lay.addWidget(Banner(f"Среди выбранного {len(risky)} файлов программ. Их удаление "
                                 "может нарушить работу приложений. Лучше удалять программы через "
                                 "«Параметры → Приложения»."))
            self.ack = QCheckBox("Я понимаю риск и подтверждаю действие с файлами программ")
            lay.addWidget(self.ack)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Отмена")
        cancel.clicked.connect(self.reject)
        self.ok = button(action_text, "check", "danger" if danger else "accent")
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)
        if self.ack is not None:
            self.ok.setEnabled(False)
            self.ack.toggled.connect(self.ok.setEnabled)
        cancel.setFocus()


class FileListDialog(QDialog):
    def __init__(self, parent, title: str, files: list, note: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 540)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(label(title, "h2"))
        if note:
            lay.addWidget(label(note, "muted", wrap=True))
        tree = _tree(["Файл", "Размер", "Изменён", "Папка"])
        tree.setSortingEnabled(False)
        for f in files[:20000]:
            it = SizeItem([os.path.basename(f.path), format_size(f.size),
                           format_datetime(f.mtime), os.path.dirname(f.path)])
            it.setData(1, Qt.UserRole, f.size)
            it.setData(2, Qt.UserRole, f.mtime)
            it.setToolTip(3, f.path)
            tree.addTopLevelItem(it)
        tree.setSortingEnabled(True)
        tree.sortItems(1, Qt.DescendingOrder)
        tree.setColumnWidth(0, 280)
        tree.setColumnWidth(1, 90)
        tree.setColumnWidth(2, 130)
        lay.addWidget(tree, 1)
        if len(files) > 20000:
            lay.addWidget(label(f"Показаны 20 000 крупнейших из {len(files)}.", "faint"))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Закрыть")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def result_text(r: OperationResult) -> str:
    lines = [f"Обработано файлов: {r.processed}"]
    if r.freed:
        lines.append(f"Освобождено на диске: {format_size(r.freed)}")
    if r.recycled:
        lines.append(f"Перемещено в корзину: {format_size(r.recycled)} "
                     "(место освободится после очистки корзины)")
    if r.moved:
        lines.append(f"Перемещено в папки: {format_size(r.moved)}")
    if r.failed:
        lines.append(f"Не удалось: {r.failed}")
    if r.cancelled:
        lines.append("Операция остановлена пользователем.")
    return "\n".join(lines)


class ResultDialog(QDialog):
    def __init__(self, parent, title: str, r: OperationResult):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 420 if r.errors else 220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(label(title, "h2"))
        lay.addWidget(label(result_text(r), wrap=True))
        if r.errors:
            lay.addWidget(label("Причины ошибок:", "muted"))
            tree = _tree(["Файл и причина"])
            for e in r.errors:
                tree.addTopLevelItem(SizeItem([e]))
            lay.addWidget(tree, 1)
        else:
            lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
