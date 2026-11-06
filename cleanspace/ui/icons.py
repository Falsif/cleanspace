"""Иконки интерфейса. В Windows 10/11 используются системные шрифты значков
Segoe Fluent Icons / Segoe MDL2 Assets (выглядят как родные значки Windows);
на других системах — простые символы Unicode."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

from ..core.utils import resource_path

GLYPHS = {
    "home": ("", "⌂"), "smart": ("", "⚡"), "analyze": ("", "◔"),
    "large": ("", "▤"), "dupes": ("", "⧉"), "old": ("", "◷"),
    "downloads": ("", "⇩"), "history": ("", "↺"), "settings": ("", "⚙"),
    "folder": ("", "▭"), "refresh": ("", "⟳"), "delete": ("", "✕"),
    "drive": ("", "◫"), "search": ("", "⌕"), "up": ("", "↑"),
    "open": ("", "↗"), "info": ("", "ℹ"), "shield": ("", "⛨"),
    "stop": ("", "■"), "check": ("", "✓"), "warning": ("", "⚠"),
    "clean": ("", "✧"), "export": ("", "⇪"), "moon": ("", "☾"),
    "sun": ("", "☀"), "move": ("", "⇥"), "properties": ("", "≡"),
    "exclude": ("", "⊘"), "eye": ("", "◉"), "sort": ("", "⇅"),
}


@lru_cache(maxsize=1)
def icon_font_family() -> str | None:
    families = set(QFontDatabase.families())
    for fam in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if fam in families:
            return fam
    return None


def glyph(name: str) -> str:
    g = GLYPHS.get(name, ("", "•"))
    return g[0] if icon_font_family() else g[1]


def glyph_font(size: int = 14) -> QFont:
    fam = icon_font_family()
    f = QFont(fam) if fam else QFont()
    f.setPixelSize(size)
    return f


def icon(name: str, color: str = "#E7EAF1", size: int = 20) -> QIcon:
    return QIcon(_pixmap(name, color, size))


@lru_cache(maxsize=256)
def _pixmap(name: str, color: str, size: int) -> QPixmap:
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setPen(QColor(color))
    p.setFont(glyph_font(int(size * scale * (0.8 if icon_font_family() else 0.85))))
    p.drawText(QRectF(0, 0, size * scale, size * scale), Qt.AlignCenter, glyph(name))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def app_icon() -> QIcon:
    ico = QIcon()
    for f in ("assets/icon.ico", "assets/icon.png"):
        path = resource_path(f)
        if path.exists():
            ico.addFile(str(path))
    return ico
