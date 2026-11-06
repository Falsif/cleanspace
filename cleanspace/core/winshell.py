"""Интеграция с Windows: корзина, Проводник, свойства файла, автозапуск.

Используются только официальные функции Windows (shell32 / реестр HKCU).
Права администратора не требуются. На других ОС функции работают в упрощённом режиме.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .utils import IS_WINDOWS

# --- Корзина ---------------------------------------------------------------

SHERB_NOCONFIRMATION = 0x1
SHERB_NOPROGRESSUI = 0x2
SHERB_NOSOUND = 0x4


def recycle_bin_info() -> tuple[int, int] | None:
    """(количество объектов, размер в байтах) для корзины всех дисков, или None."""
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        res = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if res != 0:
            return None
        return int(info.i64NumItems), int(info.i64Size)
    except Exception:
        return None


def empty_recycle_bin() -> tuple[bool, str]:
    """Очистить корзину официальной функцией Windows. Подтверждение спрашивает CleanSpace."""
    if not IS_WINDOWS:
        return False, "Очистка корзины доступна только в Windows"
    try:
        import ctypes
        flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        # 0x8000FFFF (E_UNEXPECTED) возвращается, если корзина уже пуста
        if res in (0, -2147418113):
            return True, ""
        return False, f"Windows вернула код 0x{res & 0xFFFFFFFF:08X}"
    except Exception as exc:
        return False, str(exc)


# --- Проводник -------------------------------------------------------------

def open_location(path: str) -> None:
    """Открыть папку в Проводнике и выделить файл."""
    path = os.path.normpath(path)
    if IS_WINDOWS:
        if os.path.isdir(path):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["explorer", "/select,", path])
        return
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, folder])
    except OSError:
        pass


def open_file(path: str) -> None:
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([opener, path])
        except OSError:
            pass


def show_properties(path: str) -> bool:
    """Открыть стандартное окно «Свойства» Windows для файла."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class SHELLEXECUTEINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
            ]

        SEE_MASK_INVOKEIDLIST = 0x0000000C
        info = SHELLEXECUTEINFO()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_INVOKEIDLIST
        info.lpVerb = "properties"
        info.lpFile = os.path.normpath(path)
        info.nShow = 1
        return bool(ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)))
    except Exception:
        return False


# --- Автозапуск --------------------------------------------------------------

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "CleanSpace"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pythonw if os.path.exists(pythonw) else sys.executable
    main = os.path.abspath(sys.argv[0])
    return f'"{exe}" "{main}" --minimized'


def set_autostart(enabled: bool) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "Автозапуск настраивается только в Windows"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, _RUN_NAME)
                except FileNotFoundError:
                    pass
        return True, ""
    except OSError as exc:
        return False, str(exc)


def autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_NAME)
            return True
    except OSError:
        return False


# --- Процессы ----------------------------------------------------------------

def running_process_names() -> set[str]:
    try:
        import psutil
        names = set()
        for p in psutil.process_iter(["name"]):
            n = p.info.get("name")
            if n:
                names.add(n.lower())
        return names
    except Exception:
        return set()
