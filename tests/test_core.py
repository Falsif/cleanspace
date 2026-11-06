"""Тесты логики CleanSpace. Работают ТОЛЬКО во временных папках с искусственными файлами.

Запуск:  python -m pytest -q
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleanspace.core import analyzer, cleaner, downloads, duplicates, finders, protection  # noqa: E402
from cleanspace.core.cleaner import FileItem  # noqa: E402
from cleanspace.core.scanner import Exclusions, ScanControl, ScanStats, walk  # noqa: E402
from cleanspace.core.storage import Storage  # noqa: E402
from cleanspace.core.utils import format_size, plural  # noqa: E402


def make(path: Path, size: int = 0, content: bytes | None = None, age_days: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if content is not None else os.urandom(size))
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


def item(p: Path) -> FileItem:
    st = p.stat()
    return FileItem(str(p), st.st_size, st.st_mtime)


def fake_trash(store: list):
    def _trash(path):
        store.append(path)
        os.remove(path)
    return _trash


@pytest.fixture
def personal(tmp_path, monkeypatch):
    """Подменяем «личные папки», чтобы тестовая папка считалась Документами."""
    monkeypatch.setattr(protection, "_personal_roots", lambda: (os.path.normcase(str(tmp_path)),))
    return tmp_path


# --- утилиты ---------------------------------------------------------------

def test_format_size():
    assert format_size(0) == "0 Б"
    assert format_size(1536) == "1,5 КБ"
    assert format_size(5 * 1024 ** 3) == "5,0 ГБ"
    assert plural(1, "файл", "файла", "файлов") == "файл"
    assert plural(3, "файл", "файла", "файлов") == "файла"
    assert plural(11, "файл", "файла", "файлов") == "файлов"
    assert plural(22, "файл", "файла", "файлов") == "файла"


# --- сканер ----------------------------------------------------------------

def test_walk_sizes_unicode_and_exclusions(tmp_path):
    make(tmp_path / "Документы" / "отчёт.txt", 1000)
    make(tmp_path / "Документы" / "фото 😀.jpg", 2000)
    make(tmp_path / "Секрет" / "a.bin", 5000)
    stats = ScanStats()
    ex = Exclusions([str(tmp_path / "Секрет")])
    files = list(walk([str(tmp_path)], ScanControl(), stats, ex))
    assert sum(f.size for f in files) == 3000
    assert stats.files == 2 and stats.skipped_excluded == 1


@pytest.mark.skipif(sys.platform == "win32", reason="символьные ссылки в Windows требуют прав")
def test_symlink_cannot_bypass_exclusion(tmp_path):
    make(tmp_path / "Секрет" / "a.bin", 5000)
    (tmp_path / "scan").mkdir()
    os.symlink(tmp_path / "Секрет", tmp_path / "scan" / "ссылка")
    stats = ScanStats()
    ex = Exclusions([str(tmp_path / "Секрет")])
    files = list(walk([str(tmp_path / "scan")], ScanControl(), stats, ex))
    assert files == [] and stats.skipped_links == 1
    # даже без исключений по ссылкам не ходим — размеры не удваиваются
    files = list(walk([str(tmp_path)], ScanControl(), ScanStats()))
    assert sum(f.size for f in files) == 5000


def test_cancel(tmp_path):
    for i in range(50):
        make(tmp_path / f"d{i}" / "f.bin", 10)
    c = ScanControl()
    stats = ScanStats()
    got = 0
    for _ in walk([str(tmp_path)], c, stats):
        got += 1
        if got == 5:
            c.cancel()
    assert stats.cancelled and got < 50


def test_access_denied_does_not_crash(tmp_path):
    if sys.platform == "win32" or os.geteuid() == 0:
        pytest.skip("нужен обычный пользователь Unix")
    d = tmp_path / "closed"
    make(d / "x.bin", 10)
    d.chmod(0)
    try:
        stats = ScanStats()
        list(walk([str(tmp_path)], ScanControl(), stats))
        assert stats.errors == 1
    finally:
        d.chmod(0o755)


# --- анализ ----------------------------------------------------------------

def test_analyzer_tree(tmp_path):
    make(tmp_path / "a" / "1.mp4", 3000)
    make(tmp_path / "a" / "b" / "2.zip", 2000)
    make(tmp_path / "c.txt", 100)
    res = analyzer.analyze(str(tmp_path), ScanControl())
    assert res.root.size == 5100 and res.root.total_files == 3
    a = res.root.sorted_children()[0]
    assert a.name == "a" and a.size == 5000
    assert res.categories["video"] == [3000, 1]
    assert res.categories["archive"] == [2000, 1]
    assert res.complete


def test_squarify_fills_area():
    rects = analyzer.squarify([50, 30, 10, 5, 5], 0, 0, 400, 200)
    area = sum(w * h for _, _, w, h in rects)
    assert abs(area - 400 * 200) < 1e-6
    for x, y, w, h in rects:
        assert x >= -1e-9 and y >= -1e-9 and x + w <= 400 + 1e-6 and y + h <= 200 + 1e-6


# --- большие / старые ------------------------------------------------------

def test_large_and_old(tmp_path):
    make(tmp_path / "big.bin", 3 * 1024 * 1024)
    make(tmp_path / "small.bin", 1024)
    make(tmp_path / "old.bin", 2048, age_days=400)
    r = finders.find_large([str(tmp_path)], 1024 * 1024, ScanControl())
    assert [Path(f.path).name for f in r.files] == ["big.bin"]
    r = finders.find_old([str(tmp_path)], 365, ScanControl())
    assert [Path(f.path).name for f in r.files] == ["old.bin"]
    r = finders.find_large([str(tmp_path)], 1, ScanControl(), max_results=1)
    assert r.truncated and r.matched == 3 and len(r.files) == 1


# --- дубликаты -------------------------------------------------------------

def test_duplicates_by_content_not_name(tmp_path):
    data = os.urandom(300_000)
    make(tmp_path / "a" / "photo.jpg", content=data, age_days=5)
    make(tmp_path / "b" / "копия.jpg", content=data, age_days=1)
    make(tmp_path / "c" / "photo.jpg", content=os.urandom(300_000))  # то же имя, другое содержимое
    # тот же размер и одинаковые начало/конец, но разная середина — отсекается полным SHA-256
    alt = bytearray(data)
    alt[150_000] ^= 0xFF
    make(tmp_path / "d" / "почти.jpg", content=bytes(alt))
    res = duplicates.find_duplicates([str(tmp_path)], ScanControl(), min_size=1)
    assert len(res.groups) == 1
    g = res.groups[0]
    assert {Path(f.path).name for f in g.files} == {"photo.jpg", "копия.jpg"}
    assert g.wasted == 300_000


def test_duplicates_keep_at_least_one(personal):
    data = os.urandom(10_000)
    a = make(personal / "a.bin", content=data, age_days=3)
    b = make(personal / "b.bin", content=data, age_days=2)
    res = duplicates.find_duplicates([str(personal)], ScanControl(), min_size=1)
    g = res.groups[0]
    trashed = []
    # пользователь выбрал ВСЕ копии — ничего не должно удалиться
    r = duplicates.remove_duplicates([g], {str(a), str(b)}, trash_func=fake_trash(trashed))
    assert trashed == [] and r.failed == 2 and a.exists() and b.exists()
    # автовыбор оставляет самую старую
    sel = duplicates.auto_select(g)
    assert [Path(f.path).name for f in sel] == ["b.bin"]
    r = duplicates.remove_duplicates([g], {f.path for f in sel}, trash_func=fake_trash(trashed))
    assert r.processed == 1 and a.exists() and not b.exists()
    assert r.freed == 0 and r.recycled == 10_000  # корзина ≠ освобождённое место


def test_auto_select_skips_unknown_locations(tmp_path, monkeypatch):
    monkeypatch.setattr(protection, "_personal_roots", lambda: ())
    data = os.urandom(5000)
    make(tmp_path / "a.bin", content=data, age_days=2)
    make(tmp_path / "b.bin", content=data)
    g = duplicates.find_duplicates([str(tmp_path)], ScanControl(), min_size=1).groups[0]
    assert duplicates.auto_select(g) == []


def test_duplicate_changed_keeper_blocks_removal(personal):
    data = os.urandom(10_000)
    a = make(personal / "a.bin", content=data, age_days=3)
    b = make(personal / "b.bin", content=data, age_days=2)
    g = duplicates.find_duplicates([str(personal)], ScanControl(), min_size=1).groups[0]
    a.write_bytes(os.urandom(10_000))  # оставляемая копия изменилась
    trashed = []
    r = duplicates.remove_duplicates([g], {str(b)}, trash_func=fake_trash(trashed))
    assert trashed == [] and b.exists() and r.failed == 1


# --- безопасное удаление ---------------------------------------------------

def test_recheck_before_delete(personal):
    f = make(personal / "file.bin", 100, age_days=1)
    it = item(f)
    f.write_bytes(os.urandom(200))  # файл изменился после сканирования
    trashed = []
    r = cleaner.recycle_files([it], trash_func=fake_trash(trashed))
    assert trashed == [] and f.exists() and r.failed == 1


def test_temp_delete_only_inside_roots(tmp_path):
    temp = tmp_path / "Temp"
    inside = make(temp / "sub" / "old.tmp", 500, age_days=3)
    outside = make(tmp_path / "Документы" / "важно.docx", 500, age_days=3)
    r = cleaner.delete_temp_files([item(inside), item(outside)], [str(temp)])
    assert not inside.exists() and outside.exists()
    assert r.processed == 1 and r.failed == 1 and r.freed == 500
    assert temp.exists() and not (temp / "sub").exists()  # пустая подпапка убрана, корень — нет


def test_protection_classes(monkeypatch):
    if sys.platform == "win32":
        win = os.environ.get("SystemRoot", r"C:\Windows")
        assert protection.classify(os.path.join(win, "System32", "kernel32.dll")) == protection.SYSTEM
        assert protection.classify(r"C:\pagefile.sys") == protection.SYSTEM
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        assert protection.classify(os.path.join(pf, "App", "app.exe")) == protection.PROGRAM
    else:
        assert protection.classify("/usr/bin/python3") == protection.SYSTEM
    ok, _ = protection.can_remove("/usr/lib/x.so" if sys.platform != "win32" else
                                  os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "x.dll"))
    assert not ok


def test_program_files_blocked_by_default(tmp_path, monkeypatch):
    f = make(tmp_path / "lib.dll", 100)
    trashed = []
    r = cleaner.recycle_files([item(f)], trash_func=fake_trash(trashed))
    assert trashed == [] and r.failed == 1
    r = cleaner.recycle_files([item(f)], allow_program_files=True, trash_func=fake_trash(trashed))
    assert r.processed == 1


def test_move_never_overwrites(personal):
    src = make(personal / "Загрузки" / "doc.pdf", 100)
    make(personal / "Загрузки" / "Документы" / "doc.pdf", 50)
    r = cleaner.move_files([(item(src), str(personal / "Загрузки" / "Документы"))])
    assert r.processed == 1 and r.moved == 100
    assert (personal / "Загрузки" / "Документы" / "doc (2).pdf").stat().st_size == 100
    assert (personal / "Загрузки" / "Документы" / "doc.pdf").stat().st_size == 50


# --- загрузки --------------------------------------------------------------

def test_downloads(tmp_path):
    data = os.urandom(4000)
    make(tmp_path / "setup.exe", content=data, age_days=60)
    make(tmp_path / "setup (1).exe", content=data, age_days=50)
    make(tmp_path / "архив.zip", 100)
    make(tmp_path / "фильм.mkv", 100)
    make(tmp_path / "качается.crdownload", 100)
    rep = downloads.scan_downloads(str(tmp_path), ScanControl())
    assert len(rep.files) == 4
    assert len(rep.old_installers) == 2 and len(rep.archives) == 1
    assert len(rep.redownloads) == 1 and rep.redownloads[0][2] is True
    plan = downloads.sort_plan(rep)
    dests = {Path(i.path).name: Path(d).name for i, d in plan}
    assert dests["архив.zip"] == "Архивы" and dests["фильм.mkv"] == "Видео"
    assert "качается.crdownload" not in dests
    assert downloads.base_name("Отчёт - копия (2).pdf") == "отчёт.pdf"


# --- хранилище -------------------------------------------------------------

def test_storage_persistence(tmp_path):
    db = tmp_path / "t.db"
    s = Storage(db)
    s.set("theme", "light")
    s.set("exclusions", ["C:\\Игры"])
    s.add_history("Тест", "Удаление", 3, 1, 1000, 0, ["x — нет доступа"])
    s.add_history("Тест", "Корзина", 2, 0, 0, 500, [])
    s.close()
    s = Storage(db)
    assert s.get("theme") == "light" and s.get("exclusions") == ["C:\\Игры"]
    rep = s.report(7)
    assert rep["freed"] == 1000 and rep["recycled"] == 500 and rep["failed"] == 1
    n = s.export_history_csv(str(tmp_path / "h.csv"))
    assert n == 2 and "Освобождено" in (tmp_path / "h.csv").read_text(encoding="utf-8-sig")
    s.reset_settings()
    assert s.get("theme") == "dark"
    s.close()
