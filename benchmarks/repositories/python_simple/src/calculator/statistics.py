"""
statistics.py — Simple statistical helpers.

Part of the TestPilot AI python_simple benchmark.

Coverage note:
  - mean and median are tested.
  - mode and std_dev are INTENTIONALLY UNCOVERED (no tests exist).
"""

from __future__ import annotations

import math


def mean(values: list[float]) -> float:
    """Return the arithmetic mean of *values*.

    Raises
    ------
    ValueError
        When *values* is empty.
    """
    if not values:
        raise ValueError("Cannot compute mean of an empty list.")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    """Return the median of *values*.

    Raises
    ------
    ValueError
        When *values* is empty.
    """
    if not values:
        raise ValueError("Cannot compute median of an empty list.")
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]


def mode(values: list[float]) -> float:
    """
    Return the most frequent value in *values*.

    INTENTIONALLY UNCOVERED — no test exists for this function.

    Raises
    ------
    ValueError
        When *values* is empty.
    """
    if not values:
        raise ValueError("Cannot compute mode of an empty list.")
    counts: dict[float, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda k: counts[k])


def std_dev(values: list[float]) -> float:
    """
    Return the population standard deviation of *values*.

    INTENTIONALLY UNCOVERED — no test exists for this function.

    Raises
    ------
    ValueError
        When *values* has fewer than 2 elements.
    """
    if len(values) < 2:
        raise ValueError("Standard deviation requires at least 2 values.")
    m = mean(values)
    variance = sum((x - m) ** 2 for x in values) / len(values)
    return math.sqrt(variance)
