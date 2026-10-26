"""What grid purchase costs under a tariff: energy price and base price."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Protocol

from .timeslots import QUARTER


class PriceSource(Protocol):
    """Price in EUR/kWh of a quarter hour, None if not known (yet)."""

    def get(self, slot: datetime) -> float | None: ...


@dataclass(frozen=True)
class FixedPrice:
    """The same price in EUR/kWh for every quarter hour."""

    price: float

    def get(self, slot: datetime) -> float | None:
        return self.price


@dataclass(frozen=True)
class ComposedPrice:
    """Exchange price plus net surcharges, then VAT.

    (market + surcharge) * (1 + vat), the same formula as the total price of
    the EPEX Spot integration. `surcharge` in EUR/kWh, `vat` as a fraction.
    """

    market: PriceSource
    surcharge: float
    vat: float

    def get(self, slot: datetime) -> float | None:
        price = self.market.get(slot)
        return None if price is None else (price + self.surcharge) * (1 + self.vat)


class BasePeriod(StrEnum):
    """What a base price is quoted for."""

    MONTH = "month"
    YEAR = "year"


@dataclass(frozen=True)
class Tariff:
    """Energy price per quarter hour plus an optional base price."""

    prices: PriceSource
    base_price: float = 0.0
    base_period: BasePeriod = BasePeriod.MONTH


@dataclass
class TariffTotals:
    """Costs of one tariff over the accounting period."""

    energy: float = 0.0
    consumption_cost: float = 0.0
    base_cost: float = 0.0
    # Energy whose price never came: counted, not costed (never free).
    energy_without_price: float = 0.0
    # slot -> energy waiting for its price
    pending: dict[datetime, float] = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return self.consumption_cost + self.base_cost

    @property
    def average_price(self) -> float | None:
        """Total cost per costed kWh (EUR/kWh), None before the first kWh."""
        return self.cost / self.energy if self.energy else None


def _local_midnight_utc(day: datetime, tz: tzinfo, days: int = 0) -> datetime:
    local = day.astimezone(tz).date() + timedelta(days=days)
    return datetime.combine(local, time(), tz).astimezone(UTC)


def quarters_in_day(slot: datetime, tz: tzinfo) -> int:
    """Quarter hours of the local day containing `slot` (92, 96 or 100)."""
    start = _local_midnight_utc(slot, tz)
    end = _local_midnight_utc(slot, tz, days=1)
    return int((end - start) / QUARTER)


def _days_in_period(local: date, period: BasePeriod) -> int:
    if period is BasePeriod.YEAR:
        return 366 if calendar.isleap(local.year) else 365
    return calendar.monthrange(local.year, local.month)[1]


def base_price_between(
    start: datetime,
    end: datetime,
    amount: float,
    period: BasePeriod,
    tz: tzinfo,
) -> float:
    """Share of a base price falling on the quarter hours [start, end).

    Each local day gets the price divided by the days of its month (or year),
    spread evenly over the day's quarter hours, so a month (or year) adds up
    to exactly the quoted price. Computed day by day, not per quarter hour.
    """
    total = 0.0
    cursor = start
    while cursor < end:
        days = _days_in_period(cursor.astimezone(tz).date(), period)
        day_end = _local_midnight_utc(cursor, tz, days=1)
        segment_end = min(end, day_end)
        share = (segment_end - cursor) / QUARTER / quarters_in_day(cursor, tz)
        total += amount / days * share
        cursor = segment_end
    return total
