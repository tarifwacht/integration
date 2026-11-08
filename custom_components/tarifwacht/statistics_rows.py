"""Rows of recalculated statistics. Pure Python, no Home Assistant imports.

Home Assistant keeps two tables for a sensor with a sum: short-term rows
(every 5 minutes, purged after some days) and hourly rows (kept). Each row
holds `state` (the sensor's value at the end of the period) and `sum` (the
running total the graphs and the energy dashboard use). Every 5 minutes the
recorder continues from the latest short-term row:
sum = last sum + (state now - last state) - so for a sensor whose state
never resets (Tarifwacht counts since the setup), `sum - state` stays the
same from row to row (the offset).

A recalculation writes, for each period from its start, the running total of
the recomputed values as `sum` and the recomputed sensor value as `state`
(`sum - offset`; before the setup the sensor had no value, there
`state = sum` as in an import). The rows after the recalculated range keep
their own changes; they are shifted so they continue from the new rows
(statistics_import.py).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, timedelta

from .lookback import HOUR, period_start

# The saving sensors update hourly at minute 12 (runtime.SOLAR_MINUTE) with
# the hours completed before: an hour's saving shows 70 minutes after its
# start.
SAVING_DELAY = timedelta(minutes=70)

# (start, state, sum)
Row = tuple[datetime, float, float]


def total_between(
    values: Mapping[datetime, float], start: datetime, end: datetime
) -> float:
    """Sum of the values whose period starts in [start, end)."""
    return sum(value for moment, value in values.items() if start <= moment < end)


def add_values(*parts: Mapping[datetime, float]) -> dict[datetime, float]:
    """Values per period of several parts added up."""
    total: dict[datetime, float] = {}
    for part in parts:
        for moment, value in part.items():
            total[moment] = total.get(moment, 0.0) + value
    return total


def place_savings(
    hourly: Mapping[datetime, float], setup_hour: datetime, width: timedelta
) -> dict[datetime, float]:
    """Savings per hour placed where the saving sensor shows them, per period
    of `width`.

    From the setup on, an hour shows in the sensor's value 70 minutes after
    its start (hourly update); before the setup (imported history) in its own
    hour, as the import writes it.
    """
    placed: dict[datetime, float] = {}
    for hour, value in hourly.items():
        moment = hour if hour < setup_hour else hour + SAVING_DELAY
        period = period_start(moment, width)
        placed[period] = placed.get(period, 0.0) + value
    return placed


def build_rows(
    values: Mapping[datetime, float],
    *,
    start: datetime,
    end: datetime,
    width: timedelta,
    base: float,
    offset: float,
    started: datetime,
    keep: Collection[datetime] | None = None,
) -> list[Row]:
    """Rows of every period of `width` in [start, end) with the running total
    of `values` on top of `base`.

    `keep`: only rows at these starts (the short-term rows that exist); the
    values of the other periods still add up. `offset`: sum - state from the
    setup on; rows ending before `started` get state = sum.
    """
    rows: list[Row] = []
    total = base
    period = period_start(start, width)
    while period < end:
        total += values.get(period, 0.0)
        if keep is None or period in keep:
            state = total - offset if period + width > started else total
            rows.append((period, state, total))
        period += width
    return rows


def sum_before(
    hourly: Mapping[datetime, float], base: float, start: datetime, moment: datetime
) -> float:
    """The running total at the start of the hour of `moment`, from `start`
    on (base for the short-term rows of the recalculated range)."""
    return base + total_between(hourly, start, period_start(moment, HOUR))
