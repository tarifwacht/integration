"""What grid purchase costs under a tariff: energy price and base price."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, tzinfo

from .timeslots import QUARTER


@dataclass(frozen=True)
class FixedPrice:
    """The same price in EUR/kWh for every quarter hour."""

    price: float

    def get(self, slot: datetime) -> float | None:
        return self.price


class TariffValuation:
    """Energy times the price of its quarter hour.

    Without a price (after the wait in the ledger) the energy is counted but
    not costed: a missing price must never look like free electricity.
    """

    def book(
        self,
        totals: dict[str, float],
        slot: datetime,
        energy: float,
        price: float | None,
    ) -> None:
        if price is None:
            _add(totals, "energy_without_price", energy)
            return
        _add(totals, "energy", energy)
        _add(totals, "consumption_cost", energy * price)


def _add(totals: dict[str, float], key: str, value: float) -> None:
    totals[key] = totals.get(key, 0.0) + value


def quarters_in_day(slot: datetime, tz: tzinfo) -> int:
    """Quarter hours of the local day containing `slot` (92, 96 or 100)."""
    day = slot.astimezone(tz).date()
    start = datetime.combine(day, time(), tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), tz).astimezone(UTC)
    return int((end - start) / QUARTER)


def base_price_per_slot(slot: datetime, per_month: float, tz: tzinfo) -> float:
    """Share of a monthly base price falling on one quarter hour.

    Each local day gets the monthly price divided by the days of its month,
    spread evenly over the day's quarter hours, so a month adds up to exactly
    the monthly price.
    """
    local = slot.astimezone(tz)
    days = calendar.monthrange(local.year, local.month)[1]
    return per_month / days / quarters_in_day(slot, tz)
