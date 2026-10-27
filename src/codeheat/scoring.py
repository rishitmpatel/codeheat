"""Rank/log normalisation and the hotspot score."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right


def pct_ranks(values: list[float]) -> list[float]:
    """Average-rank percentile in (0, 1]; ties share their mean rank."""
    n = len(values)
    if n == 0:
        return []
    order = sorted(range(n), key=values.__getitem__)
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = ((i + 1) + (j + 1)) / 2 / n
        for k in range(i, j + 1):
            out[order[k]] = r
        i = j + 1
    return out


def normalise(values: list[float]) -> list[float]:
    """Outlier-robust normalisation to [0, 1].

    ``0.5 * percentile_rank + 0.5 * log1p(x) / log1p(max)``.  The rank half keeps
    one monster file from flattening everybody else; the log half keeps the
    *magnitude* signal so that 200 commits still beats 20.  Zero stays zero.
    """
    if not values:
        return []
    ranks = pct_ranks(values)
    mx = max(values)
    denom = math.log1p(mx) if mx > 0 else 1.0
    return [0.0 if v <= 0 else 0.5 * r + 0.5 * math.log1p(v) / denom for v, r in zip(values, ranks)]


def top_percent(sorted_values: list[float], v: float) -> float:
    """Share (percent, 1..100) of the pool whose value is >= v (smaller = more extreme)."""
    n = len(sorted_values)
    if n == 0:
        return 100.0
    ge = n - bisect_left(sorted_values, v)
    return max(1.0, 100.0 * ge / n) if ge else 100.0


def bus_factor(contribs: list[float], threshold: float = 0.5) -> int:
    """Smallest number of people whose contributions cover >= threshold of the total."""
    total = sum(contribs)
    if total <= 0:
        return 0
    acc = 0.0
    for k, c in enumerate(sorted(contribs, reverse=True), 1):
        acc += c
        if acc / total >= threshold - 1e-12:
            return k
    return len(contribs)
