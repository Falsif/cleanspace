"""Общие вспомогательные функции: размеры, даты, категории файлов, пути."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# --- Размеры ---------------------------------------------------------------

_UNITS = ["Б", "КБ", "МБ", "ГБ", "ТБ"]


def format_size(num: float | int | None) -> str:
    """1536 -> '1,5 КБ'. Используются двоичные единицы (как в Проводнике)."""
    if num is None:
        return "—"
    num = float(num)
    sign = "-" if num < 0 else ""
    num = abs(num)
    for unit in _UNITS:
        if num < 1024 or unit == _UNITS[-1]:
            if unit == "Б":
                return f"{sign}{int(num)} {unit}"
            text = f"{num:.1f}" if num < 100 else f"{num:.0f}"
            return f"{sign}{text.replace('.', ',')} {unit}"
        num /= 1024
    return f"{num} Б"


MB = 1024 ** 2
GB = 1024 ** 3


def format_datetime(ts: float | None) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except (OSError, OverflowError, ValueError):
        return "—"


def format_date(ts: float | None) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y")
    except (OSError, OverflowError, ValueError):
        return "—"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение: plural(5, 'файл', 'файла', 'файлов') -> 'файлов'."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def num(n: int) -> str:
    """1234567 -> '1 234 567'"""
    return f"{int(n):,}".replace(",", "\u00a0")


def count_files(n: int) -> str:
    return num(n) + " " + plural(n, "файл", "файла", "файлов")


def days_ago(ts: float) -> int:
    return max(0, int((time.time() - ts) // 86400))


# --- Категории файлов ------------------------------------------------------

CATEGORIES = {
    "video": ("Видео", {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg",
                        ".mpeg", ".3gp", ".ts", ".m2ts", ".vob"}),
    "image": ("Изображения", {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
                              ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw", ".dng", ".svg",
                              ".ico", ".psd"}),
    "audio": ("Музыка", {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".aiff",
                         ".mid", ".midi"}),
    "document": ("Документы", {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt",
                               ".ods", ".odp", ".txt", ".rtf", ".md", ".csv", ".epub", ".fb2",
                               ".djvu", ".xps"}),
    "archive": ("Архивы", {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".zst",
                           ".cab", ".iso", ".img"}),
    "installer": ("Установочные файлы", {".exe", ".msi", ".msix", ".msixbundle", ".appx",
                                         ".appxbundle", ".apk", ".msu"}),
    "other": ("Другие файлы", set()),
}

CATEGORY_ORDER = ["video", "image", "audio", "document", "archive", "installer", "other"]

CATEGORY_COLORS = {
    "video": "#3B82F6",      # синий
    "image": "#14B8A6",      # бирюзовый
    "audio": "#8B5CF6",      # фиолетовый
    "document": "#F59E0B",
    "archive": "#EC4899",
    "installer": "#22C55E",
    "other": "#64748B",
}

_EXT_TO_CAT = {ext: key for key, (_, exts) in CATEGORIES.items() for ext in exts}

IMAGE_PREVIEW_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico"}


def category_of(name: str) -> str:
    return _EXT_TO_CAT.get(os.path.splitext(name)[1].lower(), "other")


def category_name(key: str) -> str:
    return CATEGORIES.get(key, CATEGORIES["other"])[0]


def file_type_label(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    cat = category_name(category_of(name))
    return f"{cat} ({ext})" if ext else cat


# --- Пути ------------------------------------------------------------------

def norm(path: str | os.PathLike) -> str:
    """Нормализованный абсолютный путь для сравнения (регистр не важен на Windows)."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def real_norm(path: str | os.PathLike) -> str:
    """Как norm(), но с разворачиванием символических ссылок и точек соединения."""
    try:
        return os.path.normcase(os.path.realpath(os.fspath(path)))
    except (OSError, ValueError):
        return norm(path)


def is_under(path: str, parent: str) -> bool:
    """path лежит внутри parent (или совпадает). Оба аргумента — уже нормализованы."""
    if path == parent:
        return True
    parent = parent if parent.endswith(os.sep) else parent + os.sep
    return path.startswith(parent)


def user_home() -> Path:
    return Path.home()


def known_folder(name: str) -> Path:
    """Путь к известной папке пользователя (Загрузки, Документы ...).

    На Windows используется SHGetKnownFolderPath — так учитывается перенос папок.
    """
    guids = {
        "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
        "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
        "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
        "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
        "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
        "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    }
    fallback = {
        "downloads": "Downloads", "documents": "Documents", "pictures": "Pictures",
        "videos": "Videos", "music": "Music", "desktop": "Desktop",
    }
    if IS_WINDOWS and name in guids:
        try:
            import ctypes
            from ctypes import wintypes
            import uuid

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            u = uuid.UUID(guids[name])
            guid = GUID(u.time_low, u.time_mid, u.time_hi_version,
                        (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))
            ptr = ctypes.c_wchar_p()
            res = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                             ctypes.byref(ptr))
            if res == 0 and ptr.value:
                value = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                return Path(value)
        except Exception:
            pass
    return user_home() / fallback.get(name, name)


def env_path(var: str) -> Path | None:
    value = os.environ.get(var)
    return Path(value) if value else None


def app_data_dir() -> Path:
    """Папка данных CleanSpace (настройки, история).

    Портативный режим: если рядом с EXE лежит файл portable.txt — данные хранятся рядом.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / "portable.txt").exists():
            d = exe_dir / "CleanSpaceData"
            d.mkdir(exist_ok=True)
            return d
    base = env_path("APPDATA") if IS_WINDOWS else None
    if base is None:
        base = Path(os.environ.get("XDG_CONFIG_HOME", user_home() / ".config"))
    d = base / "CleanSpace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resource_path(relative: str) -> Path:
    """Путь к ресурсам (работает и из исходников, и из EXE PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / relative
