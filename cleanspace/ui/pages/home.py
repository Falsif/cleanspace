"""Главная страница: состояние дисков, итоги проверок, кнопка «Начать сканирование»."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ...core import disks, finders, smart_clean
from ...core.utils import GB, MB, format_datetime, format_size, plural
from ..theme import Theme
from ..widgets import Card, DonutChart, StatCard, button, label, usage_color
from .base import BasePage

QUICK_LARGE_THRESHOLD = 500 * MB


class DiskCard(Card):
    def __init__(self, d: disks.DiskInfo):
        super().__init__(hoverable=True, margins=14, spacing=6)
        self.disk = d
        row = QHBoxLayout()
        row.setSpacing(14)
        self.donut = DonutChart(96, 11)
        self.donut.set_value(d.percent, f"{d.percent:.0f}%", "занято")
        row.addWidget(self.donut)
        info = QVBoxLayout()
        info.setSpacing(3)
        title = f"Диск {d.name}" + (f" — {d.label}" if d.label else "")
        info.addWidget(label(title, "h2"))
        info.addWidget(label(f"Всего: {format_size(d.total)}", "muted"))
        info.addWidget(label(f"Занято: {format_size(d.used)}", "muted"))
        free = label(f"Свободно: {format_size(d.free)}")
        free.setStyleSheet(f"color: {usage_color(d.percent)}; font-weight: 600;")
        info.addWidget(free)
        info.addWidget(label(f"{d.fstype}{' · съёмный' if d.removable else ''}", "faint"))
        info.addStretch(1)
        row.addLayout(info, 1)
        self.lay.addLayout(row)
        self.setToolTip("Нажмите, чтобы посмотреть, чем занят диск")


class HomePage(BasePage):
    key = "home"
    title = "Главная"
    subtitle = "Состояние дисков и итоги последних проверок"
    scrollable = True

    def __init__(self, ctx):
        super().__init__(ctx)
        # --- Герой-блок со сканированием ---
        hero = Card(margins=22, spacing=10)
        hero.lay.setAlignment(Qt.AlignHCenter)
        t = label("Проверьте компьютер", "h2")
        t.setAlignment(Qt.AlignCenter)
        hero.lay.addWidget(t)
        d = label("Быстрая безопасная проверка: временные файлы, кэш браузеров, корзина и "
                  "файлы больше 500 МБ в выбранных папках. Ничего не удаляется без вашего "
                  "подтверждения.", "muted", wrap=True)
        d.setAlignment(Qt.AlignCenter)
        d.setFixedWidth(560)
        hero.lay.addWidget(d, 0, Qt.AlignHCenter)
        self.scan_btn = button("  Начать сканирование", "search", "accent")
        self.scan_btn.setProperty("hero", True)
        self.scan_btn.clicked.connect(self.start_scan)
        hero.lay.addSpacing(6)
        hero.lay.addWidget(self.scan_btn, 0, Qt.AlignHCenter)
        self.scan_note = label("", "faint")
        self.scan_note.setAlignment(Qt.AlignCenter)
        hero.lay.addWidget(self.scan_note)
        self.lay.insertWidget(2, hero)

        # --- Карточки итогов ---
        grid = QGridLayout()
        grid.setSpacing(12)
        c = Theme.c
        self.card_free = StatCard("Свободно на диске", "drive", c["accent"])
        self.card_temp = StatCard("Временные файлы", "smart", c["teal"])
        self.card_large = StatCard("Большие файлы", "large", c["purple"])
        self.card_dupes = StatCard("Найденные дубликаты", "dupes", "#EC4899")
        self.card_last = StatCard("Последняя очистка", "history", "#22C55E")
        cards = [(self.card_free, "analyze"), (self.card_temp, "smart"),
                 (self.card_large, "large"), (self.card_dupes, "dupes"),
                 (self.card_last, "history")]
        self._cards = cards
        for card, target in cards:
            card.clicked.connect(lambda t=target: self.ctx.navigate.emit(t))
        self.card_grid = grid
        wrap = QWidget()
        wrap.setLayout(grid)
        self.lay.addWidget(wrap)

        # --- Диски ---
        hdr = QHBoxLayout()
        hdr.addWidget(label("Диски", "h2"))
        hdr.addStretch(1)
        ref = button("Обновить", "refresh")
        ref.clicked.connect(self.refresh)
        hdr.addWidget(ref)
        self.lay.addLayout(hdr)
        self.disk_grid = QGridLayout()
        self.disk_grid.setSpacing(12)
        dw = QWidget()
        dw.setLayout(self.disk_grid)
        self.lay.addWidget(dw)
        self.lay.addStretch(1)

        self._columns = 0
        ctx.summary_changed.connect(self.update_cards)
        ctx.history_changed.connect(self.update_cards)
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_disks)
        self._timer.start(60_000)

    # --- раскладка под ширину окна (1366×768 и больше) ---
    def resizeEvent(self, e):
        super().resizeEvent(e)
        cols = 5 if self.width() >= 1100 else 3 if self.width() >= 760 else 2
        if cols != self._columns:
            self._columns = cols
            for i, (card, _) in enumerate(self._cards):
                self.card_grid.addWidget(card, i // cols, i % cols)
            self._layout_disks()

    def _layout_disks(self):
        cols = 3 if self.width() >= 1150 else 2 if self.width() >= 700 else 1
        widgets = []
        while self.disk_grid.count():
            w = self.disk_grid.takeAt(0).widget()
            if w:
                widgets.append(w)
        for i, w in enumerate(widgets):
            self.disk_grid.addWidget(w, i // cols, i % cols)
        for col in range(3):
            self.disk_grid.setColumnStretch(col, 1 if col < cols else 0)

    def on_show(self):
        self.refresh_disks()

    def refresh(self):
        self.refresh_disks()
        self.update_cards()

    def refresh_disks(self):
        while self.disk_grid.count():
            w = self.disk_grid.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._disks = disks.list_disks()
        for d in self._disks:
            card = DiskCard(d)
            card.clicked.connect(lambda dd=d: self.ctx.analyze_path.emit(dd.mountpoint))
            self.disk_grid.addWidget(card)
        self._layout_disks()
        sysd = disks.system_disk()
        if sysd:
            self.card_free.set(format_size(sysd.free),
                               f"на диске {sysd.name} из {format_size(sysd.total)} "
                               f"({sysd.free / sysd.total * 100:.0f}% свободно)")
            thr = float(self.ctx.setting("low_space_threshold_gb") or 0) * GB
            if thr and sysd.free < thr:
                self.card_free.sub.setText(self.card_free.sub.text() + " — мало места!")

    def update_cards(self):
        s = self.ctx.setting("last_summary") or {}
        if "temp_size" in s:
            self.card_temp.set(format_size(s["temp_size"]),
                               f"{s.get('temp_count', 0)} {plural(s.get('temp_count', 0), 'файл', 'файла', 'файлов')}"
                               f" · проверено {format_datetime(s.get('temp_ts'))}")
        else:
            self.card_temp.set("Не проверено", "Нажмите «Начать сканирование»")
        if "large_count" in s:
            n = s["large_count"]
            self.card_large.set(f"{n} {plural(n, 'файл', 'файла', 'файлов')}",
                                f"{format_size(s.get('large_size', 0))} · больше "
                                f"{format_size(s.get('large_threshold', QUICK_LARGE_THRESHOLD))}"
                                f" · {format_datetime(s.get('large_ts'))}")
        else:
            self.card_large.set("Не проверено", "Поиск файлов больше 500 МБ")
        if "dup_groups" in s:
            g = s["dup_groups"]
            self.card_dupes.set(f"{g} {plural(g, 'набор', 'набора', 'наборов')}",
                                f"можно освободить {format_size(s.get('dup_wasted', 0))} · "
                                f"{format_datetime(s.get('dup_ts'))}")
        else:
            self.card_dupes.set("Не проверено", "Откройте раздел «Дубликаты»")
        last = self.ctx.storage.last_cleanup()
        if last:
            parts = []
            if last.freed_bytes:
                parts.append(f"освобождено {format_size(last.freed_bytes)}")
            if last.recycled_bytes:
                parts.append(f"в корзину {format_size(last.recycled_bytes)}")
            if last.moved_bytes:
                parts.append(f"перемещено {format_size(last.moved_bytes)}")
            self.card_last.set(format_datetime(last.ts), f"{last.category}: " +
                               (", ".join(parts) or f"{last.processed} файлов"))
        else:
            self.card_last.set("Ещё не было", "История пуста")

    # --- быстрое сканирование ---
    def set_busy(self, busy: bool) -> None:
        self.scan_btn.setEnabled(not busy)

    def start_scan(self):
        ex = self.ctx.exclusions()
        roots = self.ctx.scan_roots()
        max_results = self.ctx.max_results

        def job(control):
            smart = smart_clean.scan_all(control, ex)
            if control.cancelled:
                return smart, None, True
            large = finders.find_large(roots, QUICK_LARGE_THRESHOLD, control, ex, max_results)
            return smart, large, control.cancelled

        self.scan_note.setText("")
        self.run_task(job, "Сканирование компьютера…", self._scan_done)

    def _scan_done(self, res):
        smart, large, cancelled = res
        now = time.time()
        if cancelled:
            self.scan_note.setText("Сканирование остановлено — результаты неполные и не сохранены.")
            return
        temp = [r for r in smart if r.rule.special != "recycle_bin"]
        size = sum(r.size for r in temp)
        count = sum(r.count for r in temp)
        values = dict(temp_size=size, temp_count=count, temp_ts=now)
        if large is not None:
            values.update(large_count=large.matched, large_size=large.matched_size,
                          large_threshold=QUICK_LARGE_THRESHOLD, large_ts=now,
                          large_complete=large.stats.complete)
        self.ctx.update_summary(**values)
        self.ctx.smart_results_ready.emit(smart)
        if large is not None:
            self.ctx.large_results_ready.emit((QUICK_LARGE_THRESHOLD, large))
        note = "Готово. Откройте «Умная очистка», чтобы выбрать, что удалить."
        if large is not None and large.stats.errors:
            note += f" Нет доступа к {large.stats.errors} папкам — они пропущены."
        self.scan_note.setText(note)
        self.ctx.notify("scan_done", "Сканирование завершено",
                        f"Временные файлы: {format_size(size)}. Больших файлов: "
                        f"{large.matched if large else 0}.")
        if large is not None and large.matched:
            self.ctx.notify("large_found", "Найдены большие файлы",
                            f"{large.matched} файлов больше 500 МБ, всего "
                            f"{format_size(large.matched_size)}")
