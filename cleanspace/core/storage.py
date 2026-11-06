"""Хранилище CleanSpace на SQLite: настройки и журнал действий."""
from __future__ import annotations

import csv
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .utils import app_data_dir

DEFAULT_SETTINGS: dict = {
    "theme": "dark",                 # dark | light
    "language": "ru",
    "exclusions": [],                # папки и файлы, которые не анализируются
    "scan_folders": [],              # пусто = папка пользователя
    "notifications_enabled": True,
    "notify_low_space": True,
    "notify_scan_done": True,
    "notify_large_found": True,
    "notify_clean_done": True,
    "low_space_threshold_gb": 10,
    "autostart": False,
    "background_monitoring": True,   # фоновая проверка свободного места
    "monitor_interval_min": 15,
    "minimize_to_tray": False,
    "economy_mode": True,            # пониженный приоритет сканирования
    "safe_mode": False,              # только просмотр, без удаления
    "allow_program_files": False,    # разрешить действия с файлами программ
    "max_results": 5000,             # ограничение длины списков (контроль памяти)
    "dup_min_size_kb": 1,
    "last_summary": {},              # итоги последнего сканирования для главной страницы
    "downloads_sort_root": "",       # куда раскладывать файлы из «Загрузок»
    "window_geometry": "",
}


class Storage:
    """Потокобезопасная обёртка над SQLite (одно соединение + блокировка)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else app_data_dir() / "cleanspace.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                category TEXT NOT NULL,
                action TEXT NOT NULL,
                processed INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                freed_bytes INTEGER NOT NULL,
                recycled_bytes INTEGER NOT NULL,
                moved_bytes INTEGER NOT NULL DEFAULT 0,
                errors TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts);
            """
        )
        self._conn.commit()
        self._cache: dict = {}
        self._load()

    # --- настройки ---------------------------------------------------------
    def _load(self) -> None:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        self._cache = dict(DEFAULT_SETTINGS)
        for key, value in rows:
            try:
                self._cache[key] = json.loads(value)
            except (ValueError, TypeError):
                pass

    def get(self, key: str, default=None):
        if key in self._cache:
            return self._cache[key]
        return DEFAULT_SETTINGS.get(key, default)

    def set(self, key: str, value) -> None:
        self._cache[key] = value
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._conn.commit()

    def reset_settings(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM settings")
            self._conn.commit()
        self._cache = dict(DEFAULT_SETTINGS)

    def update_summary(self, **values) -> None:
        summary = dict(self.get("last_summary") or {})
        for k, v in values.items():
            summary[k] = v
        self.set("last_summary", summary)

    # --- история -----------------------------------------------------------
    def add_history(self, category: str, action: str, processed: int, failed: int,
                    freed_bytes: int, recycled_bytes: int, errors: list[str],
                    moved_bytes: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO history(ts, category, action, processed, failed, freed_bytes, "
                "recycled_bytes, moved_bytes, errors) VALUES(?,?,?,?,?,?,?,?,?)",
                (time.time(), category, action, processed, failed, freed_bytes, recycled_bytes,
                 moved_bytes, json.dumps(errors[:200], ensure_ascii=False)),
            )
            self._conn.commit()

    def history(self, since: float | None = None, limit: int = 1000) -> list["HistoryRow"]:
        query = ("SELECT id, ts, category, action, processed, failed, freed_bytes, "
                 "recycled_bytes, moved_bytes, errors FROM history")
        args: tuple = ()
        if since is not None:
            query += " WHERE ts >= ?"
            args = (since,)
        query += " ORDER BY ts DESC LIMIT ?"
        args += (limit,)
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        out = []
        for r in rows:
            try:
                errors = json.loads(r[9])
            except ValueError:
                errors = []
            out.append(HistoryRow(*r[:9], errors=errors))
        return out

    def report(self, days: int) -> dict:
        since = time.time() - days * 86400
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(processed),0), COALESCE(SUM(failed),0), "
                "COALESCE(SUM(freed_bytes),0), COALESCE(SUM(recycled_bytes),0), "
                "COALESCE(SUM(moved_bytes),0) FROM history WHERE ts >= ?",
                (since,),
            ).fetchone()
        return {
            "operations": row[0], "processed": row[1], "failed": row[2],
            "freed": row[3], "recycled": row[4], "moved": row[5],
        }

    def daily_freed(self, days: int) -> list[tuple[float, int]]:
        """Освобождено по дням (для графика). Возвращает [(начало_дня, байт), ...]."""
        now = time.time()
        lt = time.localtime(now)
        today = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        buckets = [(today - (days - 1 - i) * 86400, 0) for i in range(days)]
        rows = self.history(since=buckets[0][0], limit=100000)
        totals = [0] * days
        for r in rows:
            idx = int((r.ts - buckets[0][0]) // 86400)
            if 0 <= idx < days:
                totals[idx] += r.freed_bytes
        return [(buckets[i][0], totals[i]) for i in range(days)]

    def last_cleanup(self) -> "HistoryRow | None":
        rows = self.history(limit=1)
        return rows[0] if rows else None

    def clear_history(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM history")
            self._conn.commit()

    def export_history_csv(self, path: str) -> int:
        rows = self.history(limit=1_000_000)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Дата и время", "Категория", "Действие", "Обработано файлов",
                        "Ошибок", "Освобождено (байт)", "Перемещено в корзину (байт)",
                        "Перемещено в папки (байт)", "Причины ошибок"])
            for r in rows:
                w.writerow([time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(r.ts)),
                            r.category, r.action, r.processed, r.failed, r.freed_bytes,
                            r.recycled_bytes, r.moved_bytes, " | ".join(r.errors[:20])])
        return len(rows)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


@dataclass
class HistoryRow:
    id: int
    ts: float
    category: str
    action: str
    processed: int
    failed: int
    freed_bytes: int
    recycled_bytes: int
    moved_bytes: int
    errors: list[str]
