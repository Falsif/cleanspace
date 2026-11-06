"""Умная очистка: категории временных данных с уровнем риска и выбором."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QScrollArea, QFrame, QVBoxLayout, QWidget

from ...core import smart_clean, winshell
from ...core.cleaner import OperationResult
from ...core.smart_clean import RISK_NAMES, RISK_SAFE, CategoryResult
from ...core.utils import format_size, plural
from ..dialogs import FileListDialog
from ..theme import Theme
from ..widgets import Card, button, label
from .base import BasePage

RISK_COLORS = {"safe": "success", "low": "accent", "medium": "warning"}


class CategoryRow(Card):
    def __init__(self, res: CategoryResult, on_change, on_view):
        super().__init__(margins=12, spacing=4)
        self.res = res
        row = QHBoxLayout()
        row.setSpacing(12)
        self.check = QCheckBox()
        self.check.setEnabled(res.available)
        self.check.toggled.connect(lambda _: on_change())
        row.addWidget(self.check, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        head = QHBoxLayout()
        head.addWidget(label(res.rule.title, "h2"))
        risk = label(RISK_NAMES[res.rule.risk], "badge")
        risk.setStyleSheet(f"color: {Theme.c[RISK_COLORS[res.rule.risk]]};")
        head.addWidget(risk)
        head.addStretch(1)
        text.addLayout(head)
        text.addWidget(label(res.rule.description, "muted", wrap=True))
        if res.blocked_reason:
            text.addWidget(label("⚠ " + res.blocked_reason, "warning", wrap=True))
        if res.errors:
            text.addWidget(label(f"Нет доступа к {res.errors} объектам — пропущены", "faint"))
        row.addLayout(text, 1)
        right = QVBoxLayout()
        right.setSpacing(2)
        size = label(format_size(res.size) if res.count else "—", "h2")
        size.setAlignment(Qt.AlignRight)
        right.addWidget(size)
        cnt_word = "объект" if res.rule.special else "файл"
        cnt = label(f"{res.count} {plural(res.count, cnt_word, cnt_word + 'а', cnt_word + 'ов')}"
                    if res.count else "ничего не найдено", "muted")
        cnt.setAlignment(Qt.AlignRight)
        right.addWidget(cnt)
        if res.files:
            v = button("Посмотреть файлы", "eye")
            v.clicked.connect(lambda: on_view(res))
            right.addWidget(v, 0, Qt.AlignRight)
        row.addLayout(right)
        self.lay.addLayout(row)


class SmartCleanPage(BasePage):
    key = "smart"
    title = "Умная очистка"
    subtitle = ("Безопасный поиск временных данных. Документы, фото, видео, загрузки, сохранения "
                "игр и системные файлы Windows не затрагиваются.")

    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.check_btn = button("Проверить", "search", "accent")
        self.check_btn.clicked.connect(self.scan)
        self.safe_btn = button("Выбрать безопасное", "shield")
        self.safe_btn.clicked.connect(self.select_safe)
        self.none_btn = button("Снять выбор")
        self.none_btn.clicked.connect(lambda: self._set_all(False))
        self.clean_btn = button("Очистить выбранное", "clean", "danger")
        self.clean_btn.clicked.connect(self.clean)
        for b in (self.check_btn, self.safe_btn, self.none_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        self.total = label("", "muted")
        bar.addWidget(self.total)
        bar.addWidget(self.clean_btn)
        self.lay.addLayout(bar)
        self.summary = label("Нажмите «Проверить», чтобы найти временные файлы.", "muted")
        self.lay.addWidget(self.summary)

        self.list_host = QWidget()
        self.list_host.setObjectName("Page")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        sa = QScrollArea()
        sa.setObjectName("PageScroll")
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(self.list_host)
        self.lay.addWidget(sa, 1)
        self.rows: list[CategoryRow] = []
        ctx.smart_results_ready.connect(self.show_results)
        self._update_buttons()

    def on_safe_mode(self, safe: bool) -> None:
        self._update_buttons()

    def set_busy(self, busy: bool) -> None:
        for b in (self.check_btn, self.safe_btn, self.none_btn):
            b.setEnabled(not busy)
        self._busy = busy
        self._update_buttons()

    def _update_buttons(self):
        sel = [r for r in getattr(self, "rows", []) if r.check.isChecked()]
        size = sum(r.res.size for r in sel)
        self.total.setText(f"Выбрано: {format_size(size)}" if sel else "")
        self.clean_btn.setEnabled(bool(sel) and not self.ctx.safe_mode
                                  and not getattr(self, "_busy", False))

    def scan(self):
        ex = self.ctx.exclusions()
        self.run_task(lambda c: smart_clean.scan_all(c, ex), "Поиск временных файлов…",
                      self._scan_done)

    def _scan_done(self, results):
        if self.task and self.task.cancelled:
            self.summary.setText("Проверка остановлена — показаны только проверенные категории.")
        self.show_results(results, from_scan=True)
        temp = [r for r in results if r.rule.special != "recycle_bin"]
        if not (self.task and self.task.cancelled):
            self.ctx.update_summary(temp_size=sum(r.size for r in temp),
                                    temp_count=sum(r.count for r in temp), temp_ts=time.time())

    def show_results(self, results, from_scan: bool = False):
        for r in self.rows:
            r.setParent(None)
            r.deleteLater()
        self.rows = []
        results = sorted(results, key=lambda r: (not r.available, -r.size))
        for res in results:
            if not res.count and not res.blocked_reason and res.rule.special != "recycle_bin":
                continue  # пустые категории не показываем
            row = CategoryRow(res, self._update_buttons, self.view_files)
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)
            self.rows.append(row)
        found = sum(r.size for r in results if r.available)
        if not (self.task and self.task.cancelled and from_scan):
            empty = len(results) - len(self.rows)
            self.summary.setText(
                f"Найдено {format_size(found)} в {len([r for r in self.rows if r.res.available])} "
                f"категориях. Пустых категорий: {empty}. Отметьте нужное и нажмите «Очистить выбранное».")
        self._update_buttons()

    def select_safe(self):
        for r in self.rows:
            r.check.setChecked(r.res.available and r.res.rule.risk == RISK_SAFE)
        self._update_buttons()

    def _set_all(self, value: bool):
        for r in self.rows:
            if r.check.isEnabled():
                r.check.setChecked(value)

    def view_files(self, res: CategoryResult):
        FileListDialog(self, res.rule.title, res.files, res.rule.description).exec()

    def clean(self):
        sel = [r.res for r in self.rows if r.check.isChecked() and r.res.available]
        rows = []
        for res in sel:
            if res.rule.special == "recycle_bin":
                rows.append(("Корзина Windows (все диски)", res.size,
                             f"Очистить корзину ({res.count} объектов)"))
            else:
                rows += [(f.path, f.size, "Удалить навсегда") for f in res.files]
        note = ("Временные файлы удаляются окончательно — они не нужны для работы программ. "
                "Перед удалением каждый файл перепроверяется: если он изменился или занят "
                "программой, он будет пропущен.")
        if not self.confirm("Подтверждение очистки",
                            "Будут выполнены следующие операции:", rows,
                            "Очистить", note):
            return

        def job(control):
            total = OperationResult()
            n = sum(len(r.files) for r in sel) or 1
            done = 0
            for res in sel:
                if control.cancelled:
                    total.cancelled = True
                    break
                if res.rule.special == "recycle_bin":
                    before = winshell.recycle_bin_info()
                    ok, err = winshell.empty_recycle_bin()
                    after = winshell.recycle_bin_info()
                    if ok:
                        freed = max(0, (before[1] if before else res.size) -
                                    (after[1] if after else 0))
                        total.processed += before[0] if before else res.count
                        total.freed += freed
                    else:
                        total.fail("Корзина", err)
                    continue
                part = smart_clean_delete(res, control, done, n)
                done += len(res.files)
                total.merge(part)
            return total

        def smart_clean_delete(res, control, offset, n):
            from ...core.cleaner import delete_temp_files
            orig = control.progress

            def prog(cur, i, _t, _o=offset):
                if orig:
                    orig(cur, _o + i, n)
            control.progress = prog
            try:
                return delete_temp_files(res.files, smart_clean.allowed_roots(res.rule), control)
            finally:
                control.progress = orig

        names = ", ".join(r.rule.title for r in sel)
        self.run_task(job, "Очистка…", lambda r: self._clean_done(r, names), steps=True)

    def _clean_done(self, result: OperationResult, names: str):
        cat = f"Умная очистка: {names}"
        self.ctx.record(result, cat if len(cat) < 160 else cat[:157] + "…",
                        "Удаление временных файлов")
        self.show_result("Очистка завершена", result)
        self.summary.setText("Проверяю снова, чтобы показать актуальные данные…")
        self.scan()
