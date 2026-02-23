# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence


def safe_int(value: Any) -> int | None:
    '''Return an int value or None when conversion fails.'''

    try:
        return None if value is None else int(value)
    except Exception:
        return None


def pct(covered: int | None, total: int | None) -> float | None:
    '''Return covered / total as percent.'''

    if covered is None or total is None or total <= 0:
        return None
    return 100.0 * covered / total


def clean_floats(values: Iterable[Any]) -> list[float]:
    '''Return finite numeric values as floats.'''

    out: list[float] = []
    for value in values:
        if value is None or not isinstance(value, (int, float)):
            continue
        f = float(value)
        if math.isnan(f):
            continue
        out.append(f)
    return out


def mean(values: Iterable[Any]) -> float | None:
    '''Return the arithmetic mean of finite numeric values.'''

    xs = clean_floats(values)
    if not xs:
        return None
    return float(sum(xs) / len(xs))


def median(values: Iterable[Any]) -> float | None:
    '''Return the median of finite numeric values.'''

    xs = clean_floats(values)
    if not xs:
        return None
    xs.sort()
    mid = len(xs) // 2
    if len(xs) % 2:
        return float(xs[mid])
    return float((xs[mid - 1] + xs[mid]) / 2.0)


def minimum(values: Iterable[Any]) -> float | None:
    '''Return the minimum finite numeric value.'''

    xs = clean_floats(values)
    return None if not xs else float(min(xs))


def maximum(values: Iterable[Any]) -> float | None:
    '''Return the maximum finite numeric value.'''

    xs = clean_floats(values)
    return None if not xs else float(max(xs))


def trapezoid_auc(points: Sequence[tuple[float, float]], *, duration_s: float | None = None) -> float | None:
    '''Return trapezoidal area under a time series curve.'''

    cleaned: list[tuple[float, float]] = []
    for x, y in points:
        if not math.isfinite(float(x)) or not math.isfinite(float(y)):
            continue
        xf = float(x)
        yf = float(y)
        if xf < 0:
            continue
        cleaned.append((xf, yf))
    if not cleaned:
        return None

    cleaned.sort(key=lambda item: item[0])
    collapsed: list[tuple[float, float]] = []
    for x, y in cleaned:
        if collapsed and x == collapsed[-1][0]:
            collapsed[-1] = (x, y)
        else:
            collapsed.append((x, y))

    if collapsed[0][0] > 0:
        collapsed.insert(0, (0.0, collapsed[0][1]))

    if duration_s is not None and math.isfinite(float(duration_s)):
        duration = max(0.0, float(duration_s))
        if duration > collapsed[-1][0]:
            collapsed.append((duration, collapsed[-1][1]))

    if len(collapsed) == 1:
        if duration_s is None:
            return 0.0
        return float(collapsed[0][1]) * max(0.0, float(duration_s))

    area = 0.0
    prev_x, prev_y = collapsed[0]
    for x, y in collapsed[1:]:
        dx = x - prev_x
        if dx > 0:
            area += dx * (prev_y + y) / 2.0
        prev_x, prev_y = x, y
    return float(area)


def rankdata_desc(values: Sequence[float | None]) -> list[float | None]:
    '''Return descending average ranks for numeric values.'''

    indexed = [(i, float(v)) for i, v in enumerate(values) if isinstance(v, (int, float))]
    if not indexed:
        return [None] * len(values)
    indexed.sort(key=lambda item: item[1], reverse=True)
    ranks: list[float | None] = [None] * len(values)
    pos = 1
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (pos + (pos + (j - i) - 1)) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        pos += j - i
        i = j
    return ranks


def mann_whitney_u_pvalue(x: Sequence[float], y: Sequence[float]) -> float | None:
    '''Return a normal-approximation two-sided Mann-Whitney U p-value.'''

    x = clean_floats(x)
    y = clean_floats(y)
    n1, n2 = len(x), len(y)
    if n1 < 2 or n2 < 2:
        return None
    combined = [(v, 0) for v in x] + [(v, 1) for v in y]
    combined.sort(key=lambda item: item[0])
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i + 1
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg
        i = j
    r1 = sum(ranks[i] for i, (_, grp) in enumerate(combined) if grp == 0)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    u = min(u1, u2)
    tie_sum = 0.0
    i = 0
    while i < len(combined):
        j = i + 1
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        t = j - i
        if t > 1:
            tie_sum += t ** 3 - t
        i = j
    mu = n1 * n2 / 2.0
    n = n1 + n2
    sigma_sq = (n1 * n2 / 12.0) * (n + 1 - tie_sum / (n * (n - 1)))
    if sigma_sq <= 0:
        return None
    z = (u - mu + 0.5) / math.sqrt(sigma_sq)
    p_one = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return float(max(0.0, min(1.0, 2.0 * min(p_one, 1.0 - p_one))))


def vargha_delaney_a12(x: Sequence[float], y: Sequence[float]) -> float | None:
    '''Return the Vargha-Delaney A12 effect size for x over y.'''

    x = clean_floats(x)
    y = clean_floats(y)
    if not x or not y:
        return None
    wins = 0.0
    for a in x:
        for b in y:
            if a > b:
                wins += 1.0
            elif a == b:
                wins += 0.5
    return float(wins / (len(x) * len(y)))


def cliffs_delta(x: Sequence[float], y: Sequence[float]) -> float | None:
    '''Return Cliff's delta effect size.'''

    x = clean_floats(x)
    y = clean_floats(y)
    if not x or not y:
        return None
    gt = lt = 0
    for a in x:
        for b in y:
            if a > b:
                gt += 1
            elif a < b:
                lt += 1
    return float((gt - lt) / (len(x) * len(y)))
