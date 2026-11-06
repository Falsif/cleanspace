"""Темы оформления в стиле Windows 11 / Fluent: тёмная (по умолчанию) и светлая."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from ..core.utils import resource_path

ACCENT = "#3B82F6"     # синий
TEAL = "#14B8A6"       # бирюзовый
PURPLE = "#8B5CF6"     # фиолетовый

PALETTES = {
    "dark": {
        "bg": "#0F1117", "sidebar": "#141821", "card": "#1A1F2B", "card2": "#212737",
        "hover": "#262D3F", "border": "#2A3142", "text": "#E7EAF1", "muted": "#9AA3B5",
        "faint": "#5D6679", "input": "#141924", "track": "#2A3142",
        "danger": "#F87171", "warning": "#FBBF24", "success": "#34D399",
        "accent": ACCENT, "teal": TEAL, "purple": PURPLE, "selection": "#2B4A7E",
        "shadow": "#000000",
    },
    "light": {
        "bg": "#F3F5F9", "sidebar": "#FFFFFF", "card": "#FFFFFF", "card2": "#F6F8FB",
        "hover": "#EAF0FA", "border": "#E1E6EF", "text": "#1A1F2B", "muted": "#5D6879",
        "faint": "#9AA3B5", "input": "#FFFFFF", "track": "#E3E8F0",
        "danger": "#DC2626", "warning": "#D97706", "success": "#059669",
        "accent": "#2563EB", "teal": "#0D9488", "purple": "#7C3AED", "selection": "#CFE0FF",
        "shadow": "#8090A8",
    },
}


class Theme:
    name = "dark"
    c = PALETTES["dark"]

    @classmethod
    def color(cls, key: str) -> QColor:
        return QColor(cls.c[key])


def ui_font_family() -> str:
    families = set(QFontDatabase.families())
    for fam in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Inter",
                "Noto Sans", "DejaVu Sans"):
        if fam in families:
            return fam
    return QApplication.font().family()


def build_qss(p: dict, font: str, check: str) -> str:
    return f"""
* {{ font-family: "{font}"; font-size: 10pt; color: {p['text']}; outline: none; }}
QMainWindow, QWidget#Root {{ background: {p['bg']}; }}
QWidget#Page, QScrollArea#PageScroll, QScrollArea#PageScroll > QWidget > QWidget {{
    background: {p['bg']}; }}
QWidget#Sidebar {{ background: {p['sidebar']}; border-right: 1px solid {p['border']}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 20pt; font-weight: 600; }}
QLabel[role="subtitle"] {{ color: {p['muted']}; font-size: 10pt; }}
QLabel[role="h2"] {{ font-size: 12.5pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p['muted']}; }}
QLabel[role="faint"] {{ color: {p['faint']}; font-size: 9pt; }}
QLabel[role="big"] {{ font-size: 18pt; font-weight: 600; }}
QLabel[role="brand"] {{ font-size: 14pt; font-weight: 700; }}
QLabel[role="warning"] {{ color: {p['warning']}; }}
QLabel[role="danger"] {{ color: {p['danger']}; }}
QLabel[role="success"] {{ color: {p['success']}; }}
QLabel[role="badge"] {{ background: {p['card2']}; border: 1px solid {p['border']};
    border-radius: 9px; padding: 1px 8px; font-size: 8.5pt; color: {p['muted']}; }}

QFrame#Card {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QFrame#Card:hover[hoverable="true"] {{ border-color: {p['accent']}; }}
QFrame#Banner {{ background: {p['card2']}; border: 1px solid {p['warning']}; border-radius: 10px; }}
QFrame#InfoBanner {{ background: {p['card2']}; border: 1px solid {p['border']}; border-radius: 10px; }}

QPushButton {{ background: {p['card2']}; border: 1px solid {p['border']}; border-radius: 8px;
    padding: 7px 14px; min-height: 18px; }}
QPushButton:hover {{ background: {p['hover']}; border-color: {p['accent']}; }}
QPushButton:pressed {{ background: {p['border']}; }}
QPushButton:disabled {{ color: {p['faint']}; background: {p['card']}; border-color: {p['border']}; }}
QPushButton[accent="true"] {{ color: white; border: none; font-weight: 600;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent']}, stop:1 {p['purple']}); }}
QPushButton[accent="true"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4F8FF7, stop:1 #9B6FF7); }}
QPushButton[accent="true"]:disabled {{ background: {p['track']}; color: {p['faint']}; }}
QPushButton[danger="true"] {{ color: white; background: {p['danger']}; border: none; font-weight: 600; }}
QPushButton[danger="true"]:hover {{ background: #EF4444; }}
QPushButton[danger="true"]:disabled {{ background: {p['track']}; color: {p['faint']}; }}
QPushButton[hero="true"] {{ font-size: 13pt; padding: 14px 34px; border-radius: 24px; }}
QPushButton[chip="true"] {{ border-radius: 15px; padding: 5px 14px; }}
QPushButton[chip="true"]:checked {{ background: {p['accent']}; color: white; border-color: {p['accent']}; }}

QPushButton[nav="true"] {{ text-align: left; border: none; border-radius: 8px; padding: 9px 12px;
    background: transparent; font-size: 10.5pt; }}
QPushButton[nav="true"]:hover {{ background: {p['hover']}; }}
QPushButton[nav="true"]:checked {{ background: {p['hover']}; font-weight: 600; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {p['input']};
    border: 1px solid {p['border']}; border-radius: 7px; padding: 6px 8px; min-height: 18px;
    selection-background-color: {p['accent']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QDoubleSpinBox:focus {{ border-color: {p['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {p['card']}; border: 1px solid {p['border']};
    selection-background-color: {p['selection']}; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 16px; border: none; background: transparent; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {p['faint']}; background: {p['input']}; }}
QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']};
    image: url({check}); }}
QCheckBox::indicator:disabled {{ background: {p['track']}; border-color: {p['border']}; }}

QTreeWidget, QTreeView, QTableWidget, QListWidget {{ background: {p['card']};
    alternate-background-color: {p['card2']}; border: 1px solid {p['border']}; border-radius: 10px;
    selection-background-color: {p['selection']}; selection-color: {p['text']}; padding: 2px; }}
QTreeView::item, QListWidget::item {{ padding: 4px 2px; border: none; }}
QTreeView::item:hover {{ background: {p['hover']}; }}
QTreeView::item:selected {{ background: {p['selection']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {p['card']}; color: {p['muted']}; border: none;
    border-bottom: 1px solid {p['border']}; padding: 7px 8px; font-weight: 600; }}
QTreeView::indicator {{ width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {p['faint']}; background: {p['input']}; }}
QTreeView::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']};
    image: url({check}); }}
QTreeView::indicator:disabled {{ background: {p['track']}; border-color: {p['border']}; }}

QProgressBar {{ background: {p['track']}; border: none; border-radius: 4px; height: 8px;
    text-align: center; color: transparent; max-height: 8px; }}
QProgressBar::chunk {{ border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent']}, stop:0.5 {p['teal']}, stop:1 {p['purple']}); }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{ background: {p['card2']}; color: {p['text']}; border: 1px solid {p['border']};
    padding: 6px 8px; border-radius: 6px; }}
QMenu {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p['hover']}; }}
QMenu::item:disabled {{ color: {p['faint']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 4px 8px; }}
QDialog {{ background: {p['bg']}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: {p['muted']};
    border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {p['text']}; border-bottom-color: {p['accent']}; font-weight: 600; }}
QSplitter::handle {{ background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: {p['track']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
    background: {p['accent']}; }}
QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 2px; }}
"""


def apply_theme(app: QApplication, name: str) -> None:
    name = name if name in PALETTES else "dark"
    Theme.name = name
    Theme.c = PALETTES[name]
    p = Theme.c
    font = ui_font_family()
    f = QFont(font, 10)
    f.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(f)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(p["bg"]))
    pal.setColor(QPalette.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.Base, QColor(p["card"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["card2"]))
    pal.setColor(QPalette.Text, QColor(p["text"]))
    pal.setColor(QPalette.Button, QColor(p["card2"]))
    pal.setColor(QPalette.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(p["card2"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(p["faint"]))
    app.setPalette(pal)
    check = resource_path("assets/check.svg").as_posix()
    app.setStyleSheet(build_qss(p, font, check))
