"""Day-ahead prices per quarter hour, parsed from price sensor forecasts.

Copied from Einspeisewacht (commit e4fd5fc), developed independently since.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .timeslots import QUARTER, slot_start


@dataclass
class ParsedPrices:
    """Prices in EUR/kWh by UTC quarter-hour start, plus what was found."""

    prices: dict[datetime, float] = field(default_factory=dict)
    # Most common entry length (15 or 60 minutes), None if nothing parsed.
    resolution: timedelta | None = None
    skipped: int = 0


def parse_interval_prices(
    entries: Iterable[Mapping[str, Any]],
    *,
    start_key: str = "start_time",
    end_key: str = "end_time",
    price_key: str = "price_per_kwh",
) -> ParsedPrices:
    """Parse a list of {start, end, price} entries (EPEX Spot attribute `data`).

    Entries longer than a quarter hour (hourly prices) apply to every quarter
    hour they cover. Entries that are not whole, aligned quarter hours or have
    no numeric price are skipped and counted.
    """
    result = ParsedPrices()
    lengths: Counter[timedelta] = Counter()
    for entry in entries:
        try:
            start = datetime.fromisoformat(str(entry[start_key]))
            end = datetime.fromisoformat(str(entry[end_key]))
            price = float(entry[price_key])
        except KeyError, TypeError, ValueError:
            result.skipped += 1
            continue
        length = end - start
        if (
            start.tzinfo is None
            or slot_start(start) != start
            or length <= timedelta(0)
            or length % QUARTER
        ):
            result.skipped += 1
            continue
        lengths[length] += 1
        slot = slot_start(start)
        while slot < end:
            result.prices[slot] = price
            slot += QUARTER
    if lengths:
        result.resolution = lengths.most_common(1)[0][0]
    return result


@dataclass
class PriceTable:
    """Quarter-hour prices seen so far.

    Forecast attributes drop past entries after a day or so, and the recorder
    does not keep them; the table remembers prices for late bookings.
    """

    prices: dict[datetime, float] = field(default_factory=dict)

    def merge(self, prices: Mapping[datetime, float]) -> None:
        self.prices.update(prices)

    def get(self, slot: datetime) -> float | None:
        return self.prices.get(slot)

    def prune(self, before: datetime) -> None:
        """Forget prices of quarter hours starting before `before`."""
        self.prices = {s: p for s, p in self.prices.items() if s >= before}

    def as_dict(self) -> dict[str, float]:
        return {s.isoformat(): p for s, p in sorted(self.prices.items())}

    def restore(self, data: Mapping[str, float]) -> None:
        self.prices = {datetime.fromisoformat(s): p for s, p in data.items()}
