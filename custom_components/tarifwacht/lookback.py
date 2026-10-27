"""Quarter hours before the setup of an entry, for the compare action.

Home Assistant keeps the meter's energy per hour in its long-term statistics.
Each hour is spread evenly over its four quarter hours: exact for a fixed
price, an estimate for prices that change within the hour (day-ahead prices
are per quarter hour since 1 October 2025). Exchange prices of that time come
from SMARD.de, since the price sensors only know the time since the setup.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .tariffs import PriceSource, Tariff
from .timeslots import QUARTER, slot_start

HOUR = timedelta(hours=1)


def hour_start(moment: datetime) -> datetime:
    """UTC start of the hour (German offsets are whole hours)."""
    return slot_start(moment).replace(minute=0)


@dataclass(frozen=True)
class FallbackPrice:
    """A price sensor's prices, before `until` completed from another source."""

    primary: PriceSource
    secondary: PriceSource
    until: datetime

    def get(self, slot: datetime) -> float | None:
        price = self.primary.get(slot)
        if price is None and slot < self.until:
            return self.secondary.get(slot)
        return price


@dataclass
class Lookback:
    """Estimated consumption and tariffs for the quarter hours before `until`."""

    consumption: dict[datetime, float]
    tariffs: dict[str, Tariff]
    until: datetime
    # Hours in the period without a statistics row (meter missing or offline).
    hours_without_energy: int = 0
    # Exchange prices of SMARD.de were needed (attribution in the response).
    uses_smard: bool = False


def spread_hours(
    hourly: Iterable[tuple[datetime, float]], start: datetime, end: datetime
) -> dict[datetime, float]:
    """Energy per quarter hour in [start, end) from energy per hour (kWh)."""
    first, last = slot_start(start), end
    quarters: dict[datetime, float] = {}
    for hour, energy in hourly:
        for i in range(4):
            slot = hour + i * QUARTER
            if first <= slot < last:
                quarters[slot] = energy / 4
    return quarters


def hours_without_energy(
    hourly: Iterable[tuple[datetime, float]], start: datetime, end: datetime
) -> int:
    """Hours touching [start, end) that have no statistics row."""
    seen = {hour for hour, _ in hourly}
    missing = 0
    hour = hour_start(start)
    while hour < end:
        if hour not in seen:
            missing += 1
        hour += HOUR
    return missing
