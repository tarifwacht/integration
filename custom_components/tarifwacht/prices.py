"""Day-ahead prices per quarter hour, parsed from price sensor forecasts.

Copied from Einspeisewacht (commit e4fd5fc), developed independently since.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .history import SlotSeries
from .timeslots import QUARTER, slot_start

# Price sensors report EUR/kWh with up to 6 decimals (EPEX Spot: 5 or 6).
PRICE_DIGITS = 6


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


class PriceTable(SlotSeries):
    """Quarter-hour prices seen so far, kept for recalculation.

    Forecast attributes drop past entries after a day or so, and the recorder
    does not keep them; the table remembers every price of the accounting
    period, so tariffs can be booked again when their definition changes.
    """

    def as_dict(
        self,
        digits: int = PRICE_DIGITS,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, list[float | None]]:
        return super().as_dict(digits, start=start, end=end)

    def restore(self, data: Mapping[str, Any], *, merge: bool = False) -> None:
        if any(not isinstance(v, list) for v in data.values()):
            # Version 0.1.0b1 stored {slot start (ISO): price}.
            self.days = {}
            self.merge({datetime.fromisoformat(s): float(p) for s, p in data.items()})
            return
        super().restore(data, merge=merge)
