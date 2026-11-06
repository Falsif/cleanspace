"""Умная очистка: поиск безопасных для удаления временных данных.

Каждая категория описывает строго ограниченный набор папок внутри профиля
пользователя. Личные файлы, системные папки Windows, обновления, точки
восстановления и драйверы сюда не входят. Файлы браузеров не трогаются,
пока браузер запущен. Свежие временные файлы (младше min_age) пропускаются —
они могут использоваться прямо сейчас.
"""
from __future__ import annotations

import fnmatch
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import winshell
from .cleaner import FileItem
from .scanner import Exclusions, FileEntry, ScanControl, ScanStats, walk
from .utils import IS_WINDOWS, env_path, is_under, norm, user_home

RISK_SAFE = "safe"
RISK_LOW = "low"
RISK_MEDIUM = "medium"

RISK_NAMES = {RISK_SAFE: "Безопасно", RISK_LOW: "Низкий риск", RISK_MEDIUM: "Средний риск"}

DAY = 86400


@dataclass
class CategoryRule:
    key: str
    title: str
    description: str
    risk: str
    roots: list[Path]
    patterns: list[str] = field(default_factory=lambda: ["*"])
    min_age_days: float = 0
    processes: tuple[str, ...] = ()   # если процесс запущен — категория недоступна
    special: str = ""                 # "recycle_bin" — официальная очистка корзины
    recursive: bool = True


@dataclass
class CategoryResult:
    rule: CategoryRule
    files: list[FileItem] = field(default_factory=list)
    size: int = 0
    count: int = 0
    blocked_reason: str = ""      # почему категорию сейчас нельзя очистить
    errors: int = 0
    selected: bool = False

    @property
    def available(self) -> bool:
        return not self.blocked_reason and self.count > 0


def _local() -> Path:
    return env_path("LOCALAPPDATA") or (user_home() / "AppData" / "Local")


def _roaming() -> Path:
    return env_path("APPDATA") or (user_home() / "AppData" / "Roaming")


def _chromium_caches(base: Path) -> list[Path]:
    """Папки кэша для всех профилей Chromium-браузера (Chrome, Edge, Яндекс, Brave…)."""
    out: list[Path] = []
    try:
        profiles = [p for p in base.iterdir()
                    if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile "))]
    except OSError:
        return out
    for prof in profiles:
        for sub in ("Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage",
                    "Service Worker/ScriptCache"):
            out.append(prof / sub)
    for sub in ("ShaderCache", "GrShaderCache", "GraphiteDawnCache"):
        out.append(base / sub)
    return out


def _firefox_caches() -> list[Path]:
    base = _local() / "Mozilla" / "Firefox" / "Profiles"
    out: list[Path] = []
    try:
        for prof in base.iterdir():
            if prof.is_dir():
                out += [prof / "cache2", prof / "startupCache", prof / "thumbnails"]
    except OSError:
        pass
    return out


def build_rules() -> list[CategoryRule]:
    local, roaming = _local(), _roaming()
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or (local / "Temp"))
    browsers: list[tuple[str, Path, tuple[str, ...]]] = [
        ("Google Chrome", local / "Google" / "Chrome" / "User Data", ("chrome.exe",)),
        ("Microsoft Edge", local / "Microsoft" / "Edge" / "User Data", ("msedge.exe",)),
        ("Яндекс Браузер", local / "Yandex" / "YandexBrowser" / "User Data", ("browser.exe",)),
        ("Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data", ("brave.exe",)),
        ("Opera", roaming / "Opera Software" / "Opera Stable", ("opera.exe",)),
        ("Opera GX", roaming / "Opera Software" / "Opera GX Stable", ("opera.exe",)),
        ("Vivaldi", local / "Vivaldi" / "User Data", ("vivaldi.exe",)),
    ]
    rules = [
        CategoryRule(
            "user_temp", "Временные файлы пользователя",
            "Файлы из папки TEMP вашей учётной записи старше 1 дня. "
            "Свежие файлы пропускаются — их может использовать запущенная программа.",
            RISK_SAFE, [temp], min_age_days=1),
        CategoryRule(
            "app_cache", "Старые временные файлы приложений",
            "Кэш шейдеров DirectX и видеокарты, кэш pip/npm старше 30 дней. "
            "При необходимости приложения создадут его заново.",
            RISK_LOW, [local / "D3DSCache", local / "NVIDIA" / "DXCache",
                       local / "NVIDIA" / "GLCache", local / "AMD" / "DxCache",
                       local / "AMD" / "DxcCache", local / "Intel" / "ShaderCache",
                       local / "pip" / "cache", local / "npm-cache",
                       roaming / "npm-cache"],
            min_age_days=30),
    ]
    for title, base, procs in browsers:
        roots = _chromium_caches(base) if base.exists() else []
        rules.append(CategoryRule(
            f"browser_{title}", f"Кэш браузера {title}",
            "Временные файлы страниц и картинок. Пароли, закладки, история и вход "
            "на сайты не затрагиваются. Браузер нужно закрыть.",
            RISK_LOW, roots, processes=procs))
    ff = _firefox_caches()
    rules.append(CategoryRule(
        "browser_firefox", "Кэш браузера Mozilla Firefox",
        "Временные файлы страниц. Пароли, закладки и история не затрагиваются. "
        "Браузер нужно закрыть.", RISK_LOW, ff, processes=("firefox.exe",)))
    rules += [
        CategoryRule(
            "error_logs", "Журналы ошибок и отчёты о сбоях",
            "Дампы аварийных завершений программ и пользовательские отчёты Windows "
            "об ошибках (WER) старше 7 дней.",
            RISK_SAFE, [local / "CrashDumps",
                        local / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                        local / "Microsoft" / "Windows" / "WER" / "ReportQueue"],
            min_age_days=7),
        CategoryRule(
            "old_temp_data", "Неиспользуемые временные данные",
            "Старый кэш INetCache (Internet Explorer/WebView) и временные файлы "
            "установщиков Windows Store старше 14 дней.",
            RISK_LOW, [local / "Microsoft" / "Windows" / "INetCache" / "IE",
                       local / "Microsoft" / "Windows" / "INetCache" / "Low",
                       local / "Packages" / "Microsoft.WindowsStore_8wekyb3d8bbwe" / "LocalCache"],
            min_age_days=14),
        CategoryRule(
            "thumbnails", "Миниатюры Windows",
            "Кэш эскизов картинок и видео в Проводнике. Windows создаст его заново; "
            "используемые сейчас файлы будут пропущены.",
            RISK_LOW, [local / "Microsoft" / "Windows" / "Explorer"],
            patterns=["thumbcache_*.db", "iconcache_*.db"], recursive=False),
        CategoryRule(
            "recycle_bin", "Корзина",
            "Файлы, которые вы ранее удалили в корзину. После очистки их нельзя "
            "будет восстановить. Очищается официальной функцией Windows.",
            RISK_MEDIUM, [], special="recycle_bin"),
    ]
    return rules


def _match(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns)


def scan_category(rule: CategoryRule, control: ScanControl, exclusions: Exclusions,
                  running: set[str]) -> CategoryResult:
    res = CategoryResult(rule)
    if rule.special == "recycle_bin":
        info = winshell.recycle_bin_info()
        if info is None:
            res.blocked_reason = "Недоступно в этой системе"
        else:
            res.count, res.size = info
        return res
    if rule.processes and running & set(rule.processes):
        res.blocked_reason = "Браузер запущен — закройте его и проверьте снова"
    existing = [str(r) for r in rule.roots if r.is_dir()]
    if not existing:
        return res
    cutoff = time.time() - rule.min_age_days * DAY
    stats = ScanStats()
    if rule.recursive:
        it = walk(existing, control, stats, exclusions)
    else:
        def _flat():
            for root in existing:
                try:
                    with os.scandir(root) as entries:
                        for e in entries:
                            if e.is_file(follow_symlinks=False) and not e.is_symlink():
                                try:
                                    st = e.stat(follow_symlinks=False)
                                except OSError:
                                    stats.errors += 1
                                    continue
                                yield FileEntry(e.path, st.st_size, st.st_mtime)
                except OSError:
                    stats.errors += 1
        it = _flat()
    own_dir = getattr(sys, "_MEIPASS", None)  # распакованные файлы самого CleanSpace.exe
    own_dir = norm(own_dir) if own_dir else None
    for fe in it:
        if own_dir and is_under(norm(fe.path), own_dir):
            continue
        if not _match(os.path.basename(fe.path), rule.patterns):
            continue
        if fe.mtime > cutoff:
            continue
        res.files.append(FileItem(fe.path, fe.size, fe.mtime))
        res.size += fe.size
        res.count += 1
    res.errors = stats.errors
    return res


def scan_all(control: ScanControl, exclusions: Exclusions,
             rules: list[CategoryRule] | None = None) -> list[CategoryResult]:
    rules = rules or build_rules()
    running = winshell.running_process_names() if IS_WINDOWS else set()
    results = []
    for rule in rules:
        if control.cancelled:
            break
        control.report(rule.title, len(results), 0, force=True)
        results.append(scan_category(rule, control, exclusions, running))
    return results


def allowed_roots(rule: CategoryRule) -> list[str]:
    return [str(r) for r in rule.roots]
