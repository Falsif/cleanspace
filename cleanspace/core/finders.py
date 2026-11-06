"""Поиск больших и старых файлов.

Результаты ограничиваются max_results самыми крупными файлами (контроль памяти),
при этом всегда сообщается, сколько всего файлов подошло под фильтр.
"""
from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field

from .cleaner import FileItem
from .scanner import Exclusions, ScanControl, ScanStats, scan_priority, walk


@dataclass
class FinderResult:
    files: list[FileItem] = field(default_factory=list)   # по убыванию размера
    matched: int = 0          # сколько всего файлов подошло
    matched_size: int = 0
    stats: ScanStats = field(default_factory=ScanStats)
    truncated: bool = False

    @property
    def shown_size(self) -> int:
        return sum(f.size for f in self.files)


def _collect(roots, control, exclusions, predicate, max_results) -> FinderResult:
    res = FinderResult()
    heap: list[tuple[int, str, float]] = []
    with scan_priority(control.economy):
        for fe in walk(roots, control, res.stats, exclusions):
            if not predicate(fe):
                continue
            res.matched += 1
            res.matched_size += fe.size
            item = (fe.size, fe.path, fe.mtime)
            if len(heap) < max_results:
                heapq.heappush(heap, item)
            else:
                heapq.heappushpop(heap, item)
    res.truncated = res.matched > len(heap)
    res.files = [FileItem(p, s, m) for s, p, m in sorted(heap, reverse=True)]
    return res


def find_large(roots: list[str], min_size: int, control: ScanControl,
               exclusions: Exclusions | None = None, max_results: int = 5000) -> FinderResult:
    return _collect(roots, control, exclusions, lambda fe: fe.size >= min_size, max_results)


def find_old(roots: list[str], older_than_days: float, control: ScanControl,
             exclusions: Exclusions | None = None, min_size: int = 0,
             max_results: int = 5000) -> FinderResult:
    cutoff = time.time() - older_than_days * 86400
    return _collect(roots, control, exclusions,
                    lambda fe: fe.mtime < cutoff and fe.size >= min_size, max_results)
