"""Таблица файлов с галочками, сортировкой и контекстным меню."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QHeaderView, QMenu, QMessageBox, QTreeWidget, QTreeWidgetItem

from ..core import protection, winshell
from ..core.cleaner import FileItem
from ..core.utils import file_type_label, format_datetime, format_size, num
from .theme import Theme
from .widgets import SizeItem

COL_NAME, COL_SIZE, COL_TYPE, COL_DATE, COL_PATH = range(5)


class FileTable(QTreeWidget):
    checked_changed = Signal()
    exclude_requested = Signal(str)

    def __init__(self, ctx, checkable: bool = True, extra_column: str | None = None):
        super().__init__()
        self.ctx = ctx
        self.checkable = checkable
        cols = ["Имя", "Размер", "Тип", "Изменён", "Расположение"]
        if extra_column:
            cols.insert(2, extra_column)
        self.extra = extra_column is not None
        self.setHeaderLabels(cols)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(True)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemChanged.connect(self._on_changed)
        self.itemDoubleClicked.connect(lambda it, _c: self._open_location(it))
        h = self.header()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        self.setColumnWidth(0, 280)
        self.setColumnWidth(1, 90)
        self.setColumnWidth(2, 150 if not self.extra else 120)
        self.setColumnWidth(3, 130)
        if self.extra:
            self.setColumnWidth(4, 130)
        self._items: dict[str, FileItem] = {}
        self._mute = False

    def _col(self, c: int) -> int:
        return c + 1 if self.extra and c >= 2 else c

    def set_files(self, files: list[FileItem], extra: dict[str, str] | None = None) -> None:
        self._mute = True
        self.setSortingEnabled(False)
        self.setUpdatesEnabled(False)
        self.clear()
        self._items = {}
        allow_prog = self.ctx.allow_program_files
        rows = []
        for f in files:
            name = os.path.basename(f.path)
            values = [name, format_size(f.size), file_type_label(name), format_datetime(f.mtime),
                      os.path.dirname(f.path)]
            if self.extra:
                values.insert(2, (extra or {}).get(f.path, ""))
            it = SizeItem(values)
            it.setData(COL_NAME, Qt.UserRole + 1, f.path)
            it.setData(COL_SIZE, Qt.UserRole, f.size)
            it.setData(self._col(COL_DATE), Qt.UserRole, f.mtime)
            it.setToolTip(COL_NAME, f.path)
            it.setToolTip(self._col(COL_PATH), f.path)
            ok, why = protection.can_remove(f.path, allow_prog)
            if self.checkable:
                if ok:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(COL_NAME, Qt.Unchecked)
                else:
                    it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
                    it.setData(COL_NAME, Qt.CheckStateRole, None)
                    it.setText(COL_NAME, "🔒 " + name)
                    it.setToolTip(COL_NAME, f"{why}\n{f.path}")
                    for c in range(self.columnCount()):
                        it.setForeground(c, Theme.color("faint"))
            self._items[f.path] = f
            rows.append(it)
        self.addTopLevelItems(rows)
        self.setUpdatesEnabled(True)
        self.setSortingEnabled(True)
        self.sortItems(COL_SIZE, Qt.DescendingOrder)
        self._mute = False
        self.checked_changed.emit()

    def path_of(self, it: QTreeWidgetItem) -> str:
        return it.data(COL_NAME, Qt.UserRole + 1)

    def checked_files(self) -> list[FileItem]:
        out = []
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it.flags() & Qt.ItemIsUserCheckable and it.checkState(COL_NAME) == Qt.Checked:
                out.append(self._items[self.path_of(it)])
        return out

    def set_all_checked(self, checked: bool) -> None:
        self._mute = True
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it.flags() & Qt.ItemIsUserCheckable and not it.isHidden():
                it.setCheckState(COL_NAME, Qt.Checked if checked else Qt.Unchecked)
        self._mute = False
        self.checked_changed.emit()

    def check_paths(self, paths: set[str]) -> None:
        self._mute = True
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(COL_NAME, Qt.Checked if self.path_of(it) in paths else Qt.Unchecked)
        self._mute = False
        self.checked_changed.emit()

    def remove_paths(self, paths: set[str]) -> None:
        for i in reversed(range(self.topLevelItemCount())):
            it = self.topLevelItem(i)
            p = self.path_of(it)
            if p in paths:
                self.takeTopLevelItem(i)
                self._items.pop(p, None)
        self.checked_changed.emit()

    def filter_text(self, text: str) -> None:
        text = text.lower().strip()
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            it.setHidden(bool(text) and text not in self.path_of(it).lower())

    def _on_changed(self, _it, col):
        if col == COL_NAME and not self._mute:
            self.checked_changed.emit()

    def _open_location(self, it) -> None:
        if it:
            winshell.open_location(self.path_of(it))

    def _menu(self, pos) -> None:
        it = self.itemAt(pos)
        if not it:
            return
        path = self.path_of(it)
        m = QMenu(self)
        a = QAction("Открыть расположение", m)
        a.triggered.connect(lambda: winshell.open_location(path))
        m.addAction(a)
        a = QAction("Открыть файл", m)
        a.triggered.connect(lambda: self._open_file(path))
        m.addAction(a)
        a = QAction("Свойства", m)
        a.triggered.connect(lambda: self._properties(path))
        m.addAction(a)
        a = QAction("Скопировать путь", m)
        a.triggered.connect(lambda: QGuiApplication.clipboard().setText(path))
        m.addAction(a)
        m.addSeparator()
        a = QAction("Добавить файл в исключения", m)
        a.triggered.connect(lambda: self.exclude_requested.emit(path))
        m.addAction(a)
        a = QAction("Добавить папку в исключения", m)
        a.triggered.connect(lambda: self.exclude_requested.emit(os.path.dirname(path)))
        m.addAction(a)
        m.exec(self.viewport().mapToGlobal(pos))

    def _open_file(self, path: str) -> None:
        level = protection.classify(path)
        if level in (protection.SYSTEM, protection.PROGRAM) or path.lower().endswith(
                (".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr")):
            if QMessageBox.question(self, "Открыть файл",
                                    "Этот файл может быть программой или системным файлом. "
                                    "Запустить его?") != QMessageBox.Yes:
                return
        try:
            winshell.open_file(path)
        except OSError as exc:
            QMessageBox.warning(self, "Не удалось открыть", str(exc))

    def _properties(self, path: str) -> None:
        if not winshell.show_properties(path):
            try:
                st = os.stat(path)
                QMessageBox.information(
                    self, "Свойства",
                    f"{path}\n\nРазмер: {format_size(st.st_size)} ({num(st.st_size)} байт)\n"
                    f"Изменён: {format_datetime(st.st_mtime)}\n"
                    f"Защита: {protection.LEVEL_NAMES[protection.classify(path)]}")
            except OSError as exc:
                QMessageBox.warning(self, "Свойства", str(exc))
