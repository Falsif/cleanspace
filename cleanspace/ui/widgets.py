"""Общие виджеты CleanSpace: карточки, диаграммы, Treemap, панель прогресса и т.д.
Все графики рисуются вручную через QPainter — это быстро и не требует тяжёлых библиотек."""
from __future__ import annotations

import math

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QProgressBar, QPushButton, QSizePolicy, QToolTip,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.analyzer import squarify
from ..core.utils import CATEGORY_COLORS, category_name, format_size, num
from . import icons
from .theme import Theme


# --- простые элементы ------------------------------------------------------

def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    if wrap:
        lb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return lb


def set_role(widget: QWidget, role: str) -> None:
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def button(text: str, icon_name: str | None = None, kind: str | None = None,
           tooltip: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty(kind, True)
    if icon_name:
        b.setProperty("icon_name", icon_name)
        b.setProperty("icon_kind", kind or "")
        refresh_button_icon(b)
        b.setIconSize(QSize(16, 16))
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def refresh_button_icon(b: QPushButton) -> None:
    """Перекрасить иконку кнопки под текущую тему."""
    name = b.property("icon_name")
    if name:
        kind = b.property("icon_kind")
        color = "#FFFFFF" if kind in ("accent", "danger") else Theme.c["text"]
        b.setIcon(icons.icon(name, color, 16))


class Card(QFrame):
    clicked = Signal()

    def __init__(self, parent=None, hoverable: bool = False, margins: int = 16, spacing: int = 8):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("hoverable", hoverable)
        if hoverable:
            self.setCursor(Qt.PointingHandCursor)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(margins, margins, margins, margins)
        self.lay.setSpacing(spacing)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.property("hoverable"):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class IconBadge(QLabel):
    """Круглая подложка с иконкой в акцентном цвете."""

    def __init__(self, icon_name: str, color: str, size: int = 36):
        super().__init__()
        self.icon_name, self.color, self.sz = icon_name, color, size
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.color)
        c.setAlpha(40)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), 10, 10)
        p.setPen(QColor(self.color))
        p.setFont(icons.glyph_font(int(self.sz * 0.45)))
        p.drawText(self.rect(), Qt.AlignCenter, icons.glyph(self.icon_name))
        p.end()


class StatCard(Card):
    def __init__(self, title: str, icon_name: str, color: str):
        super().__init__(hoverable=True, margins=14, spacing=4)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(IconBadge(icon_name, color))
        self.title = label(title, "muted", wrap=True)
        top.addWidget(self.title, 1)
        self.lay.addLayout(top)
        self.value = label("Не проверено", "big")
        self.sub = label("", "faint", wrap=True)
        self.lay.addSpacing(4)
        self.lay.addWidget(self.value)
        self.lay.addWidget(self.sub)
        self.lay.addStretch(1)
        self.setMinimumHeight(128)

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)


class Banner(QFrame):
    def __init__(self, text: str = "", kind: str = "warning"):
        super().__init__()
        self.setObjectName("Banner" if kind == "warning" else "InfoBanner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        ic = QLabel()
        ic.setPixmap(icons.icon("warning" if kind == "warning" else "info",
                                Theme.c["warning" if kind == "warning" else "accent"], 18)
                     .pixmap(18, 18))
        lay.addWidget(ic, 0, Qt.AlignTop)
        self.text = label(text, wrap=True)
        lay.addWidget(self.text, 1)

    def setText(self, text: str) -> None:
        self.text.setText(text)
        self.setVisible(bool(text))


class ChipGroup(QWidget):
    """Группа «таблеток»-фильтров с единственным выбором."""
    changed = Signal(object)

    def __init__(self, options: list[tuple[str, object]], default_index: int = 0):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.values = []
        for i, (text, value) in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("chip", True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            self.values.append(value)
            lay.addWidget(b)
            if i == default_index:
                b.setChecked(True)
        lay.addStretch(1)
        self.group.idClicked.connect(lambda i: self.changed.emit(self.values[i]))

    def value(self):
        return self.values[max(0, self.group.checkedId())]


class ProgressPanel(Card):
    """Прогресс фоновой операции с кнопкой «Остановить»."""
    cancel_requested = Signal()

    def __init__(self):
        super().__init__(margins=12, spacing=6)
        row = QHBoxLayout()
        self.title = label("Сканирование…", "h2")
        row.addWidget(self.title, 1)
        self.counter = label("", "muted")
        row.addWidget(self.counter)
        self.cancel_btn = button("Остановить", "stop")
        self.cancel_btn.clicked.connect(self._cancel)
        row.addWidget(self.cancel_btn)
        self.lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.lay.addWidget(self.bar)
        self.path = label("", "faint")
        self.path.setTextInteractionFlags(Qt.NoTextInteraction)
        self.path.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lay.addWidget(self.path)
        self.hide()

    def _cancel(self):
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Останавливаю…")
        self.cancel_requested.emit()

    def start(self, title: str, determinate: bool = False) -> None:
        self.title.setText(title)
        self.counter.setText("")
        self.path.setText("")
        self.bar.setRange(0, 100 if determinate else 0)
        self.bar.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Остановить")
        self.show()

    def update_files(self, current: str, files: int, size: int) -> None:
        self.counter.setText(f"{num(files)} файлов · {format_size(size)}")
        self._set_path(current)

    def update_steps(self, current: str, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(min(done, total))
            self.counter.setText(f"{done} из {total}")
        self._set_path(current)

    def _set_path(self, text: str) -> None:
        fm = QFontMetrics(self.path.font())
        self.path.setText(fm.elidedText(text, Qt.ElideMiddle, max(100, self.path.width() - 4)))

    def finish(self) -> None:
        self.hide()


class SizeItem(QTreeWidgetItem):
    """Элемент таблицы с правильной сортировкой по числам (размер, дата)."""

    def __lt__(self, other):
        tree = self.treeWidget()
        col = tree.sortColumn() if tree else 0
        a = self.data(col, Qt.UserRole)
        b = other.data(col, Qt.UserRole)
        if a is not None and b is not None:
            try:
                return a < b
            except TypeError:
                pass
        return self.text(col).lower() < other.text(col).lower()


def fade_in(widget: QWidget, duration: int = 180) -> None:
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeleteWhenStopped)


def usage_color(percent: float) -> str:
    if percent >= 90:
        return Theme.c["danger"]
    if percent >= 75:
        return Theme.c["warning"]
    return Theme.c["accent"]


# --- Диаграммы -------------------------------------------------------------

class DonutChart(QWidget):
    """Кольцевая диаграмма заполнения диска (анимируется при обновлении)."""

    def __init__(self, size: int = 120, thickness: int = 13):
        super().__init__()
        self.setFixedSize(size, size)
        self.thickness = thickness
        self.percent = 0.0
        self._shown = 0.0
        self.center_text = ""
        self.center_sub = ""
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(700)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v):
        self._shown = float(v)
        self.update()

    def set_value(self, percent: float, text: str = "", sub: str = "") -> None:
        self.percent = max(0.0, min(100.0, percent))
        self.center_text = text or f"{self.percent:.0f}%"
        self.center_sub = sub
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(self.percent)
        self._anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.thickness
        r = QRectF(t / 2 + 1, t / 2 + 1, self.width() - t - 2, self.height() - t - 2)
        pen = QPen(Theme.color("track"), t, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 0, 360 * 16)
        if self._shown > 0:
            col = QColor(usage_color(self.percent))
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            grad.setColorAt(0, col)
            grad.setColorAt(1, QColor(Theme.c["purple"]) if self.percent < 75 else col.darker(115))
            pen = QPen(QBrush(grad), t, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, -int(self._shown / 100 * 360 * 16))
        p.setPen(Theme.color("text"))
        f = QFont(self.font())
        f.setPointSizeF(13 if self.width() >= 110 else 10.5)
        f.setBold(True)
        p.setFont(f)
        if self.center_sub:
            p.drawText(QRectF(0, self.height() / 2 - 20, self.width(), 24), Qt.AlignCenter,
                       self.center_text)
            f.setBold(False)
            f.setPointSizeF(8)
            p.setFont(f)
            p.setPen(Theme.color("muted"))
            p.drawText(QRectF(0, self.height() / 2 + 2, self.width(), 18), Qt.AlignCenter,
                       self.center_sub)
        else:
            p.drawText(self.rect(), Qt.AlignCenter, self.center_text)
        p.end()


class StackedBar(QWidget):
    """Горизонтальная полоса из сегментов (распределение по категориям)."""

    def __init__(self, height: int = 14):
        super().__init__()
        self.setFixedHeight(height)
        self.segments: list[tuple[float, str, str]] = []  # (значение, цвет, подсказка)
        self.setMouseTracking(True)

    def set_segments(self, segments: list[tuple[float, str, str]]) -> None:
        self.segments = [s for s in segments if s[0] > 0]
        self.update()

    def _rects(self):
        total = sum(s[0] for s in self.segments) or 1
        x = 0.0
        out = []
        for v, c, tip in self.segments:
            w = self.width() * v / total
            out.append((QRectF(x, 0, w, self.height()), c, tip))
            x += w
        return out

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.height() / 2, self.height() / 2)
        p.setClipPath(path)
        p.fillRect(self.rect(), Theme.color("track"))
        for r, c, _ in self._rects():
            p.fillRect(r.adjusted(0, 0, -1 if r.width() > 3 else 0, 0), QColor(c))
        p.end()

    def mouseMoveEvent(self, e):
        for r, _, tip in self._rects():
            if r.contains(e.position()):
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()


class BarChart(QWidget):
    """Простая столбчатая диаграмма (история освобождённого места по дням)."""

    def __init__(self):
        super().__init__()
        self.data: list[tuple[str, float, str]] = []  # (подпись, значение, подсказка)
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self._bars: list[tuple[QRectF, str]] = []

    def set_data(self, data: list[tuple[str, float, str]]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._bars = []
        if not self.data:
            p.end()
            return
        bottom = self.height() - 22
        top = 10
        mx = max((d[1] for d in self.data), default=0) or 1
        n = len(self.data)
        slot = self.width() / n
        bw = max(4.0, min(28.0, slot * 0.6))
        p.setPen(QPen(Theme.color("border"), 1))
        p.drawLine(QPointF(0, bottom + 0.5), QPointF(self.width(), bottom + 0.5))
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        step = max(1, int(math.ceil(n / 15)))
        for i, (lbl, v, tip) in enumerate(self.data):
            x = slot * i + (slot - bw) / 2
            h = (bottom - top) * v / mx
            r = QRectF(x, bottom - max(h, 2 if v > 0 else 0), bw, max(h, 2 if v > 0 else 0))
            if v > 0:
                g = QLinearGradient(r.topLeft(), r.bottomLeft())
                g.setColorAt(0, QColor(Theme.c["teal"]))
                g.setColorAt(1, QColor(Theme.c["accent"]))
                path = QPainterPath()
                path.addRoundedRect(r, min(5, bw / 2), min(5, bw / 2))
                p.fillPath(path, g)
            self._bars.append((QRectF(slot * i, top, slot, bottom - top), tip))
            if i % step == 0:
                p.setPen(Theme.color("muted"))
                x0 = min(max(0.0, slot * i - 12), self.width() - slot - 24)
                p.drawText(QRectF(x0, bottom + 4, slot + 24, 16), Qt.AlignCenter, lbl)
        p.end()

    def mouseMoveEvent(self, e):
        for r, tip in self._bars:
            if r.contains(e.position()):
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()


class Legend(QWidget):
    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(5)

    def set_items(self, items: list[tuple[str, str, str]]) -> None:
        """items: (цвет, название, значение)"""
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for color, name, value in items:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{color}; border-radius:5px;")
            h.addWidget(dot)
            h.addWidget(label(name), 1)
            h.addWidget(label(value, "muted"))
            self.lay.addWidget(row)


# --- Treemap ---------------------------------------------------------------

class Treemap(QWidget):
    """Визуальная карта диска: площадь прямоугольника пропорциональна размеру."""
    item_clicked = Signal(dict)
    item_activated = Signal(dict)   # двойной щелчок — открыть папку

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self.rects: list[QRectF] = []
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_items(self, items: list[dict]) -> None:
        self.items = items
        self.hover = -1
        self._layout()
        self.update()

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    def _layout(self):
        vals = [max(1, i["size"]) for i in self.items]
        rects = squarify(vals, 0, 0, max(1, self.width()), max(1, self.height()))
        self.rects = [QRectF(*r) for r in rects]

    def _color(self, it: dict, idx: int) -> QColor:
        if it["kind"] == "dir":
            palette = [Theme.c["accent"], Theme.c["teal"], Theme.c["purple"], "#0EA5E9",
                       "#6366F1", "#06B6D4"]
            return QColor(palette[idx % len(palette)])
        if it["kind"] == "rest":
            return Theme.color("faint")
        return QColor(CATEGORY_COLORS.get(it.get("category") or "other", "#64748B"))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.items:
            p.setPen(Theme.color("muted"))
            p.drawText(self.rect(), Qt.AlignCenter, "Выберите диск или папку и нажмите «Сканировать»")
            p.end()
            return
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = QFontMetrics(f)
        dir_idx = 0
        for i, (it, r) in enumerate(zip(self.items, self.rects)):
            if r.width() < 1 or r.height() < 1:
                continue
            c = self._color(it, dir_idx)
            if it["kind"] == "dir":
                dir_idx += 1
            rr = r.adjusted(1.5, 1.5, -1.5, -1.5)
            g = QLinearGradient(rr.topLeft(), rr.bottomRight())
            base = QColor(c)
            if Theme.name == "dark":
                base = base.darker(135)
            if i == self.hover:
                base = base.lighter(125)
            g.setColorAt(0, base.lighter(112))
            g.setColorAt(1, base)
            path = QPainterPath()
            rad = min(6.0, rr.width() / 3, rr.height() / 3)
            path.addRoundedRect(rr, rad, rad)
            p.fillPath(path, g)
            if rr.width() > 54 and rr.height() > 30:
                p.setPen(QColor("#FFFFFF"))
                name = ("📁 " if it["kind"] == "dir" and not icons.icon_font_family() else "") + it["name"]
                p.drawText(rr.adjusted(6, 4, -6, 0), Qt.AlignLeft | Qt.AlignTop,
                           fm.elidedText(name, Qt.ElideRight, int(rr.width() - 12)))
                if rr.height() > 46:
                    c2 = QColor("#FFFFFF")
                    c2.setAlpha(190)
                    p.setPen(c2)
                    p.drawText(rr.adjusted(6, 20, -6, 0), Qt.AlignLeft | Qt.AlignTop,
                               format_size(it["size"]))
        p.end()

    def _index_at(self, pos) -> int:
        for i, r in enumerate(self.rects):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        if i != self.hover:
            self.hover = i
            self.update()
        if i >= 0:
            it = self.items[i]
            kind = {"dir": "Папка", "file": category_name(it.get("category") or "other"),
                    "rest": "Мелкие файлы"}[it["kind"]]
            hint = "\nДвойной щелчок — открыть" if it["kind"] == "dir" else ""
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"{it['name']}\n{kind} · {format_size(it['size'])}{hint}", self)

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._index_at(e.position())
        if i >= 0:
            self.item_clicked.emit(self.items[i])

    def mouseDoubleClickEvent(self, e):
        i = self._index_at(e.position())
        if i >= 0:
            self.item_activated.emit(self.items[i])


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(2)
        lay.addWidget(label(title, "title"))
        if subtitle:
            lay.addWidget(label(subtitle, "subtitle", wrap=True))
