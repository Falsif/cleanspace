"""Защита от опасных действий: классификация путей по уровню риска.

Правила:
* SYSTEM  — файлы Windows, файлы подкачки, точки восстановления, корзина, драйверы.
            Удаление из CleanSpace запрещено всегда.
* PROGRAM — установленные программы (Program Files, ProgramData, AppData\\Local\\Programs …).
            Удаление запрещено по умолчанию, можно разрешить в настройках (с предупреждением).
* PERSONAL — личные папки (Документы, Изображения, Видео, Музыка, Рабочий стол, Загрузки).
            Только ручной выбор + перемещение в корзину после подтверждения.
* OTHER   — прочие места. Только ручной выбор, без автоматического выделения.
"""
from __future__ import annotations

import os
from functools import lru_cache

from .utils import IS_WINDOWS, is_under, known_folder, norm, real_norm, user_home

SYSTEM = "system"
PROGRAM = "program"
PERSONAL = "personal"
OTHER = "other"

LEVEL_NAMES = {
    SYSTEM: "Системный файл",
    PROGRAM: "Файл программы",
    PERSONAL: "Личная папка",
    OTHER: "Другое расположение",
}

# Имена в корне диска, которые трогать нельзя
_ROOT_SYSTEM_NAMES = {
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log", "dumpstack.log.tmp",
    "bootmgr", "bootnxt", "$recycle.bin", "system volume information", "recovery", "boot",
    "$windows.~bt", "$windows.~ws", "$winreagent", "windows", "config.msi", "msocache",
    "efi", "$sysreset", "documents and settings", "perflogs",
}

# Папки внутри профиля, считающиеся «программными»
_PROFILE_PROGRAM_PARTS = [
    ("appdata", "local", "programs"),
    ("appdata", "local", "microsoft", "windowsapps"),
    ("appdata", "local", "packages"),
    ("appdata", "roaming", "microsoft", "windows", "start menu"),
]

# Расширения, которые в любом месте считаются критичными для системы/программ
_PROGRAM_EXT = {".dll", ".sys", ".drv", ".ocx", ".cpl", ".mui", ".efi"}


@lru_cache(maxsize=1)
def _system_roots() -> tuple[str, ...]:
    roots = []
    if IS_WINDOWS:
        for var in ("SystemRoot", "windir"):
            v = os.environ.get(var)
            if v:
                roots.append(norm(v))
    else:  # для тестов в Linux/macOS
        roots += [norm(p) for p in ("/bin", "/sbin", "/usr", "/lib", "/lib64", "/boot", "/etc",
                                    "/proc", "/sys", "/dev", "/System")]
    return tuple(dict.fromkeys(roots))


@lru_cache(maxsize=1)
def _program_roots() -> tuple[str, ...]:
    roots = []
    if IS_WINDOWS:
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData",
                    "CommonProgramFiles", "CommonProgramFiles(x86)"):
            v = os.environ.get(var)
            if v:
                roots.append(norm(v))
    else:
        roots += [norm(p) for p in ("/opt", "/Applications", "/var/lib", "/snap")]
    home = norm(user_home())
    for parts in _PROFILE_PROGRAM_PARTS:
        roots.append(norm(os.path.join(home, *parts)))
    return tuple(dict.fromkeys(roots))


@lru_cache(maxsize=1)
def _personal_roots() -> tuple[str, ...]:
    roots = []
    for name in ("documents", "pictures", "videos", "music", "desktop", "downloads"):
        try:
            roots.append(norm(known_folder(name)))
        except Exception:
            pass
    return tuple(dict.fromkeys(roots))


def personal_roots() -> tuple[str, ...]:
    return _personal_roots()


def _drive_root_name(npath: str) -> str | None:
    """Если путь лежит прямо в корне диска (C:\\pagefile.sys) — вернуть первое имя."""
    drive, rest = os.path.splitdrive(npath)
    parts = [p for p in rest.replace("\\", "/").split("/") if p]
    return parts[0].lower() if parts else None


def classify(path: str) -> str:
    """Определить уровень защиты пути. Учитывает символические ссылки и точки соединения."""
    candidates = {norm(path), real_norm(path)}
    level = OTHER
    for npath in candidates:
        first = _drive_root_name(npath)
        if IS_WINDOWS and first in _ROOT_SYSTEM_NAMES:
            return SYSTEM
        if any(is_under(npath, r) for r in _system_roots()):
            return SYSTEM
        if any(is_under(npath, r) for r in _program_roots()):
            level = PROGRAM
        elif os.path.splitext(npath)[1] in _PROGRAM_EXT:
            level = PROGRAM
        elif level == OTHER and any(is_under(npath, r) for r in _personal_roots()):
            level = PERSONAL
    return level


def can_remove(path: str, allow_program_files: bool = False) -> tuple[bool, str]:
    """Можно ли вообще удалять/перемещать этот путь из CleanSpace. Возвращает (да/нет, причина)."""
    level = classify(path)
    if level == SYSTEM:
        return False, "Системные файлы Windows нельзя удалять из CleanSpace"
    if level == PROGRAM and not allow_program_files:
        return False, ("Файл программы. Удаление запрещено настройками "
                       "(используйте «Установка и удаление программ» Windows)")
    return True, ""


def auto_select_allowed(path: str) -> bool:
    """Можно ли автоматически отмечать файл (например, копию в наборе дубликатов).

    Разрешено только для личных папок пользователя. Системные, программные
    и неизвестные расположения никогда не выделяются автоматически.
    """
    return classify(path) == PERSONAL


def reset_cache() -> None:
    """Сбросить кэш корневых папок (используется в тестах)."""
    _system_roots.cache_clear()
    _program_roots.cache_clear()
    _personal_roots.cache_clear()
