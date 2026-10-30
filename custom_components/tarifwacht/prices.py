"""Day-ahead prices per quarter hour, parsed from price sensor forecasts.

Copied from Einspeisewacht (commit e4fd5fc), developed independently since.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any

from .history import SlotSeries
from .timeslots import QUARTER, slot_start

# Price sensors report EUR/kWh with up to 6 decimals (EPEX Spot: 5 or 6).
PRICE_DIGITS = 6

# A recorded price state this soon after a quarter-hour boundary is an
# ordinary price change (EPEX Spot changes 0.1-0.4 s after it).
PRICE_CHANGE_DELAY = timedelta(seconds=10)


@dataclass
class ParsedPrices:
    """Prices in EUR/kWh by UTC quarter-hour start, plus what was found."""

    prices: dict[datetime, float] = field(default_factory=dict)
    # Most common entry length (15 or 60 minutes), None if nothing parsed.
    resolution: timedelta | None = None
    skipped: int = 0
    # Recognised attribute format ("epex_spot", "nordpool", "entsoe") or
    # "state" for a sensor without forecast.
    format: str | None = None


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


def parse_start_prices(
    entries: Iterable[Mapping[str, Any]],
    *,
    time_key: str = "time",
    price_key: str = "price",
) -> ParsedPrices:
    """Parse a list of {start, price} entries without an end (ENTSO-E).

    The length of an entry is the most common distance between consecutive
    starts (15 or 60 minutes; measured in UTC, so clock changes do not
    matter). A gap is not filled and the last entry gets the same length. If
    the length cannot be determined, nothing is parsed.
    """
    result = ParsedPrices()
    starts: dict[datetime, float] = {}
    for entry in entries:
        try:
            start = datetime.fromisoformat(str(entry[time_key]))
            price = float(entry[price_key])
        except KeyError, TypeError, ValueError:
            result.skipped += 1
            continue
        if start.tzinfo is None or slot_start(start) != start:
            result.skipped += 1
            continue
        starts[slot_start(start)] = price
    ordered = sorted(starts)
    distances = Counter(b - a for a, b in pairwise(ordered))
    length = distances.most_common(1)[0][0] if distances else None
    if length not in (QUARTER, timedelta(hours=1)):
        result.skipped += len(ordered)
        return result
    result.resolution = length
    for start in ordered:
        slot = start
        while slot < start + length:
            result.prices[slot] = starts[start]
            slot += QUARTER
    return result


def _first_entry(attributes: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    values = attributes.get(name)
    if isinstance(values, list) and values and isinstance(values[0], Mapping):
        return values[0]
    return None


def _entries(attributes: Mapping[str, Any], *names: str) -> list[Mapping[str, Any]]:
    return [
        entry
        for name in names
        if isinstance(values := attributes.get(name), list)
        for entry in values
        if isinstance(entry, Mapping)
    ]


def parse_price_attributes(attributes: Mapping[str, Any]) -> ParsedPrices | None:
    """Prices from a price sensor's forecast attributes; None if none is known.

    A format is only recognised by its exact keys: attribute names alone are
    ambiguous (several integrations use `data` with different contents).
    - EPEX Spot: `data` = [{start_time, end_time, price_per_kwh}] (fixture).
    - Nord Pool (HACS custom-components/nordpool): `raw_today`, `raw_tomorrow`
      = [{start, end, value}] (fixture derived from its code and API data).
    - ENTSO-E (HACS JaccoR/hass-entso-e): `prices`, `prices_today`,
      `prices_tomorrow` = [{time, price}] without an end (fixture derived).
    """
    first = _first_entry(attributes, "data")
    if first is not None and {"start_time", "end_time", "price_per_kwh"} <= set(first):
        parsed = parse_interval_prices(attributes["data"])
        parsed.format = "epex_spot"
        return parsed
    first = _first_entry(attributes, "raw_today") or _first_entry(
        attributes, "raw_tomorrow"
    )
    if first is not None and {"start", "end", "value"} <= set(first):
        parsed = parse_interval_prices(
            _entries(attributes, "raw_today", "raw_tomorrow"),
            start_key="start",
            end_key="end",
            price_key="value",
        )
        parsed.format = "nordpool"
        return parsed
    names = ("prices", "prices_today", "prices_tomorrow")
    first = next((e for n in names if (e := _first_entry(attributes, n))), None)
    if first is not None and {"time", "price"} <= set(first):
        parsed = parse_start_prices(_entries(attributes, *names))
        parsed.format = "entsoe"
        return parsed
    return None


def prices_from_states(
    states: Iterable[tuple[datetime, float | None]],
    start: datetime,
    end: datetime,
    restarts: Iterable[datetime] = (),
) -> dict[datetime, float]:
    """Prices of the quarter hours in [start, end) from a sensor's recorded states.

    For the past of a price sensor: the recorder keeps its state (the price of
    the running quarter hour), not its forecast attributes. Each state (time,
    price or None if unavailable) is the price of the quarter hour it was
    recorded in; the last one within a quarter hour wins, as in live
    operation. It also holds for the following quarter hours if the next
    state is an ordinary price change (right after a quarter-hour boundary).
    A next state at any other time may follow a restart of Home Assistant:
    the quarter hours in between stay without a price rather than get one
    that may have changed while it was off. `restarts` are the starts of the
    recorder's runs: a state never holds across one, also when the first
    state after the restart happens to come right after a boundary.
    """
    ordered = sorted(states, key=lambda state: state[0])
    starts = sorted(restarts)
    first = slot_start(start)
    prices: dict[datetime, float] = {}
    for i, (at, price) in enumerate(ordered):
        if price is None:
            continue
        own = slot_start(at)
        last = own
        if i + 1 < len(ordered):
            next_at = ordered[i + 1][0]
            next_slot = slot_start(next_at)
            restarted = any(at < run <= next_at for run in starts)
            if next_at - next_slot <= PRICE_CHANGE_DELAY and not restarted:
                last = max(own, next_slot - QUARTER)
        slot = max(own, first)
        while slot <= last and slot < end:
            prices[slot] = price
            slot += QUARTER
    return prices


def attribute_shape(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Structure of list attributes (names, keys, types; no values).

    For the diagnostics, so new price sources can be supported from what
    users send in.
    """
    shape: dict[str, Any] = {}
    for name, values in attributes.items():
        if isinstance(values, list) and values:
            first = values[0]
            shape[name] = {
                "entries": len(values),
                "entry": {k: type(v).__name__ for k, v in first.items()}
                if isinstance(first, Mapping)
                else type(first).__name__,
            }
    return shape


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
