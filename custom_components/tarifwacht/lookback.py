"""Quarter hours before the setup of an entry, for the compare action.

Home Assistant keeps the meter's energy per hour in its long-term statistics.
Each hour is spread evenly over its four quarter hours: exact for a fixed
price, an estimate for prices that change within the hour (day-ahead prices
are per quarter hour since 1 October 2025). Exchange prices of that time come
from SMARD.de, since the price sensors only know the time since the setup.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo

from .const import MAX_GRID_POWER_KW
from .meter import POWER_MARGIN
from .tariffs import PriceSource, Tariff
from .timeslots import QUARTER, slot_start

HOUR = timedelta(hours=1)
FIVE_MINUTES = timedelta(minutes=5)

# The largest plausible change of an energy meter per hour of the long-term
# statistics (per hour since the previous row, plausible_hours): the same
# bound the live meter applies to every reading (meter.py, MeterEvent.JUMP),
# 100 kW x 1.5 = 150 kWh.
MAX_HOURLY_KWH = MAX_GRID_POWER_KW * POWER_MARGIN


def hour_start(moment: datetime) -> datetime:
    """UTC start of the hour (German offsets are whole hours)."""
    return slot_start(moment).replace(minute=0)


def period_start(moment: datetime, width: timedelta) -> datetime:
    """UTC start of the period of `width` (5 minutes, 15 minutes, an hour)
    containing `moment`."""
    seconds = int(width.total_seconds())
    stamp = int(moment.timestamp())
    return datetime.fromtimestamp(stamp - stamp % seconds, UTC)


def plausible_hours(
    rows: Iterable[tuple[datetime, float, float | None]],
    max_kwh: float = MAX_HOURLY_KWH,
) -> tuple[list[tuple[datetime, float]], list[datetime]]:
    """Hourly changes of a meter (start, change in kWh, state of the row;
    in order) split into the plausible ones and the hours left out.

    The bound is `max_kwh` per hour since the previous row: while Home
    Assistant was off, the recorder writes no rows, and the first row
    afterwards holds the whole gap (the first row of the series: one hour).
    Left out:

    - more than the bound: a unit glitch of the source, e.g. Wh reported as
      kWh for a moment (state 107 -> 109851.5);
    - less than 0: the sum restarted (meter replaced or reset in the
      statistics);
    - the fall back after such a jump (109851.5 -> 110.131): Home Assistant
      takes the fall for a new meter cycle and adds the whole reading to the
      sum, which can stay under the bound. Also when the wrong reading lasted
      a few hours: until the state falls below the jump's, the fall back is
      still expected (a row without a state ends the wait).

    A state that falls without a jump before (meter reset to 0) stays. Same
    rule in Tarifwacht (lookback.plausible_hours), Wärmewacht
    (plausible.plausible_hours) and Einspeisewacht (report.plausible_hours);
    only the bound per hour differs.
    """
    kept: list[tuple[datetime, float]] = []
    left_out: list[datetime] = []
    jump_state: float | None = None
    previous: datetime | None = None
    for hour, change, state in rows:
        hours = 1.0 if previous is None else (hour - previous) / HOUR
        previous = hour
        bound = max_kwh * max(hours, 1.0)
        back = jump_state is not None and state is not None and state < jump_state
        if change < 0 or change > bound or back:
            left_out.append(hour)
            jump_state = state if change > bound else None
        else:
            kept.append((hour, change))
            # A wrong reading may last a few hours: the fall back comes later.
            if state is None:
                jump_state = None
    return kept, left_out


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
    # Hours of the meter's statistics left out as implausible (plausible_hours).
    implausible_hours: list[datetime] = field(default_factory=list)


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


@dataclass
class HourlyCosts:
    """Energy and costs per UTC hour: the rows of long-term statistics."""

    energy: dict[datetime, float]
    consumption_cost: dict[str, dict[datetime, float]]
    # Consumption cost plus base price.
    cost: dict[str, dict[datetime, float]]
    # Tariffs without the price of a quarter hour with energy.
    incomplete: set[str]


def period_costs(
    quarters: Iterable[tuple[datetime, float]],
    tariffs: Mapping[str, Tariff],
    start: datetime,
    end: datetime,
    tz: tzinfo,
    width: timedelta = HOUR,
) -> HourlyCosts:
    """Sum the quarter hours in [start, end) per period of `width`, every
    period of it listed (keys: UTC period starts).

    Periods shorter than a quarter hour (5 minutes, for short-term
    statistics) get an equal share of their quarter hour's energy, priced
    with its price. Periods without energy still carry the base price.
    """
    periods: list[datetime] = []
    period = period_start(start, width)
    while period < end:
        periods.append(period)
        period += width
    energy = dict.fromkeys(periods, 0.0)
    consumption = {key: dict.fromkeys(periods, 0.0) for key in tariffs}
    incomplete: set[str] = set()
    parts = max(1, QUARTER // width)
    for slot, kwh in quarters:
        if not start <= slot < end:
            continue
        prices: dict[str, float] = {}
        for key, tariff in tariffs.items():
            if (price := tariff.price(slot)) is None:
                if kwh:
                    incomplete.add(key)
                continue
            prices[key] = price
        share = kwh / parts
        for part in range(parts):
            bucket = period_start(slot + part * width, width)
            if bucket not in energy:
                continue
            energy[bucket] += share
            for key, price in prices.items():
                consumption[key][bucket] += share * price
    cost = {
        key: {
            period: consumption[key][period]
            + tariff.base_between(max(period, start), min(period + width, end), tz)
            for period in periods
        }
        for key, tariff in tariffs.items()
    }
    return HourlyCosts(energy, consumption, cost, incomplete)


def hourly_costs(
    quarters: Iterable[tuple[datetime, float]],
    tariffs: Mapping[str, Tariff],
    start: datetime,
    end: datetime,
    tz: tzinfo,
) -> HourlyCosts:
    """Sum the quarter hours in [start, end) per hour, every hour of it listed.

    Hours without energy still carry the base price.
    """
    return period_costs(quarters, tariffs, start, end, tz, HOUR)


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
