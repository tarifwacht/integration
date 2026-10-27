"""One meter's accounting under several tariffs.

The consumption per quarter hour and every price seen are kept for the whole
accounting period; the totals of each tariff are derived from them. They are
recomputed on start (so a changed or added tariff covers the whole period) and
then updated incrementally under the same rules.

Pure Python; the Home Assistant side (runtime.py) feeds it readings, price
forecasts and clock ticks, and stores `as_dict()`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from itertools import chain
from typing import Any

from .history import SlotSeries
from .lookback import Lookback
from .meter import MeterTracker, MeterUpdate
from .prices import ParsedPrices, PriceTable
from .tariffs import Tariff, TariffTotals
from .timeslots import QUARTER, slot_start

# How long energy waits for its price after its quarter hour ended; after that
# it is counted without a price (never as free).
PRICE_WAIT = timedelta(hours=24)

# Energy in kWh is stored with 0.1 mWh resolution.
ENERGY_DIGITS = 7


@dataclass
class PeriodCosts:
    """Costs of each tariff in a period (answer of the compare action)."""

    start: datetime
    end: datetime
    totals: dict[str, TariffTotals]
    energy: float = 0.0
    # Quarter hours with recorded consumption in the period.
    quarter_hours: int = 0
    # Of these, estimated from hourly statistics (before the setup).
    estimated_energy: float = 0.0
    estimated_quarter_hours: int = 0
    # The same per local calendar month ("YYYY-MM"), in order.
    months: dict[str, PeriodCosts] = field(default_factory=dict)


def month_bounds(
    start: datetime, end: datetime, tz: tzinfo
) -> Iterator[tuple[str, datetime, datetime]]:
    """Local calendar months touching [start, end), clipped to it (UTC)."""
    cursor = start
    while cursor < end:
        local = cursor.astimezone(tz)
        year, month = local.year + local.month // 12, local.month % 12 + 1
        next_month = datetime.combine(date(year, month, 1), time(), tz).astimezone(UTC)
        segment_end = min(end, next_month)
        yield f"{local.year:04d}-{local.month:02d}", cursor, segment_end
        cursor = segment_end


@dataclass
class Comparison:
    """Consumption cost of every tariff in the quarter hours priced in all of them.

    Differences and the cheapest tariff compare like with like: a quarter hour
    without a price in one tariff (price sensor failed) is left out for all,
    instead of making that tariff look cheaper.
    """

    consumption_cost: dict[str, float] = field(default_factory=dict)
    energy: float = 0.0
    energy_left_out: float = 0.0
    # slot -> energy while a tariff still waits for the slot's price
    pending: dict[datetime, float] = field(default_factory=dict)


@dataclass
class Engine:
    """Books every meter reading into each tariff."""

    meter: MeterTracker
    tariffs: dict[str, Tariff]
    tz: tzinfo
    # Price history per price sensor (entity id); tariffs read from these.
    prices: dict[str, PriceTable] = field(default_factory=dict)
    consumption: SlotSeries = field(default_factory=SlotSeries)
    # First quarter hour of the accounting period (base prices count from here).
    started: datetime | None = None
    # Consumption from `started` up to here is still to be read from the
    # recorder (set when migrating from 0.1.0b1).
    backfill_until: datetime | None = None
    # UTC days before this are stored in yearly archives, not in the live state.
    archived_until: date | None = None
    meter_events: Counter[str] = field(default_factory=Counter)
    last_parse: dict[str, ParsedPrices] = field(default_factory=dict)
    # Derived, not stored.
    energy: float = 0.0
    totals: dict[str, TariffTotals] = field(default_factory=dict)
    comparison: Comparison = field(default_factory=Comparison)
    _base_until: datetime | None = None

    def price_table(self, source: str) -> PriceTable:
        return self.prices.setdefault(source, PriceTable())

    def start(self, now: datetime) -> None:
        """Begin the period on first use, then compute all totals."""
        if self.started is None:
            self.started = slot_start(now)
        self.recompute(now)

    def recompute(self, now: datetime) -> None:
        """Totals of every tariff from the stored consumption and prices."""
        self.energy = 0.0
        self.totals = {key: TariffTotals() for key in self.tariffs}
        self.comparison = Comparison()
        self._book(self.consumption.items(), now)
        self._base_until = self.started
        self._book_base_prices(now)

    def late_prices(self, now: datetime, grace: timedelta) -> set[str]:
        """Tariffs with energy whose price is overdue (quarter ended > grace ago).

        Day-ahead prices are known the day before; a price still missing well
        after its quarter hour points to a failing price sensor.
        """
        return {
            key
            for key, totals in self.totals.items()
            if any(now - (slot + QUARTER) > grace for slot in totals.pending)
        }

    def costs_between(
        self,
        start: datetime,
        end: datetime,
        now: datetime,
        lookback: Lookback | None = None,
    ) -> PeriodCosts:
        """Costs of every tariff for the quarter hours in [start, end).

        Same rules as the running totals. Without `lookback` the period is
        clipped to the accounting period (`started` up to the running quarter
        hour); with it, the quarter hours before `started` come from there.
        """
        tariffs = lookback.tariffs if lookback is not None else self.tariffs
        first = slot_start(start)
        if lookback is None:
            first = max(first, self.started or slot_start(now))
        # A quarter hour that begins before `end` belongs to the period.
        end_slot = slot_start(end)
        if end_slot < end:
            end_slot += QUARTER
        last = max(first, min(end_slot, slot_start(now) + QUARTER))

        def costs(a: datetime, b: datetime) -> PeriodCosts:
            return PeriodCosts(a, b, {key: TariffTotals() for key in tariffs})

        result = costs(first, last)
        months = {key: costs(a, b) for key, a, b in month_bounds(first, last, self.tz)}
        result.months = months
        estimated = lookback.consumption.items() if lookback is not None else ()
        for slot, energy in chain(estimated, self.consumption.items()):
            if not first <= slot < last:
                continue
            is_estimate = lookback is not None and slot < lookback.until
            # A price missing before the setup will not come any more.
            booked_at = max(now, slot + QUARTER + PRICE_WAIT) if is_estimate else now
            month = months[slot.astimezone(self.tz).strftime("%Y-%m")]
            for part in (result, month):
                part.energy += energy
                part.quarter_hours += 1
                if is_estimate:
                    part.estimated_energy += energy
                    part.estimated_quarter_hours += 1
                for key, totals in part.totals.items():
                    _book(tariffs[key], totals, slot, energy, booked_at)
        # Base prices of the quarter hours that have ended.
        base_end = min(last, slot_start(now))
        for month in months.values():
            if month.start >= base_end:
                continue
            for key, tariff in tariffs.items():
                base = tariff.base_between(
                    month.start, min(month.end, base_end), self.tz
                )
                month.totals[key].base_cost = base
                result.totals[key].base_cost += base
        return result

    def backfill(
        self, readings: Iterable[tuple[float, datetime]], since: datetime
    ) -> None:
        """Add consumption from recorded meter readings (kWh, time) to the history.

        For a period the live meter did not book into the history (update
        from 0.1.0b1). The baseline is the last reading at or before `since`;
        earlier readings are ignored. Resets and jumps are skipped as in live
        operation. Call `start()` or `recompute()` afterwards.
        """
        ordered = sorted(readings, key=lambda reading: reading[1])
        baseline = max(
            (i for i, (_, at) in enumerate(ordered) if at <= since), default=0
        )
        tracker = MeterTracker(max_power_kw=self.meter.max_power_kw)
        for value, at in ordered[baseline:]:
            for slot, energy in tracker.update(value, at).pieces:
                self.consumption.add(slot, energy)
        self.backfill_until = None
        # Older days may have changed: the archives are written again.
        self.archived_until = None

    def on_meter(self, value_kwh: float, at: datetime, now: datetime) -> MeterUpdate:
        """A new meter reading in kWh."""
        update = self.meter.update(value_kwh, at)
        if update.event is not None:
            self.meter_events[update.event] += 1
        for slot, energy in update.pieces:
            self.consumption.add(slot, energy)
        self._book(update.pieces, now)
        return update

    def on_prices(self, source: str, parsed: ParsedPrices, now: datetime) -> None:
        """A new price forecast from a price sensor."""
        self.last_parse[source] = parsed
        table = self.price_table(source)
        new = [slot for slot in parsed.prices if table.get(slot) is None]
        table.merge(parsed.prices)
        # Energy already counted without a price may get it after all: a
        # tariff added with a new price sensor (its prices arrive after the
        # recomputation on start) or a sensor that was not ready at start.
        if any(t.energy_without_price for t in self.totals.values()) and any(
            self.consumption.get(slot) for slot in new
        ):
            self.recompute(now)
        self.tick(now)

    def tick(self, now: datetime) -> None:
        """Clock tick (every quarter hour) and after new prices."""
        for key, totals in self.totals.items():
            if totals.pending:
                pending, totals.pending = totals.pending, {}
                for slot, energy in sorted(pending.items()):
                    self._book_one(key, totals, slot, energy, now)
        if self.comparison.pending:
            pending, self.comparison.pending = self.comparison.pending, {}
            for slot, energy in sorted(pending.items()):
                self._compare(slot, energy)
        self._book_base_prices(now)

    def compared_cost(self, key: str) -> float | None:
        """Total cost of a tariff for comparisons (see `Comparison`).

        None if consumption was left out and none could be compared.
        """
        comparison = self.comparison
        if comparison.energy_left_out and not comparison.energy:
            return None
        return comparison.consumption_cost.get(key, 0.0) + self.totals[key].base_cost

    def _book(self, pieces: Iterable[tuple[datetime, float]], now: datetime) -> None:
        for slot, energy in pieces:
            self.energy += energy
            for key, totals in self.totals.items():
                self._book_one(key, totals, slot, energy, now)
            self._compare(slot, energy)

    def _compare(self, slot: datetime, energy: float) -> None:
        """Add a quarter hour's energy to the comparison once every tariff is done."""
        comparison = self.comparison
        if any(slot in totals.pending for totals in self.totals.values()):
            comparison.pending[slot] = comparison.pending.get(slot, 0.0) + energy
            return
        prices: dict[str, float] = {}
        for key, tariff in self.tariffs.items():
            if (price := tariff.price(slot)) is None:
                comparison.energy_left_out += energy
                return
            prices[key] = price
        comparison.energy += energy
        costs = comparison.consumption_cost
        for key, price in prices.items():
            costs[key] = costs.get(key, 0.0) + energy * price

    def _book_one(
        self,
        key: str,
        totals: TariffTotals,
        slot: datetime,
        energy: float,
        now: datetime,
    ) -> None:
        _book(self.tariffs[key], totals, slot, energy, now)

    def _book_base_prices(self, now: datetime) -> None:
        """Base prices of every quarter hour that ended by `now`.

        The base price is owed while Home Assistant is off, too: gaps are
        caught up.
        """
        current = slot_start(now)
        if self._base_until is None or self._base_until >= current:
            return
        for key, tariff in self.tariffs.items():
            self.totals[key].base_cost += tariff.base_between(
                self._base_until, current, self.tz
            )
        self._base_until = current

    def years(self) -> set[int]:
        """Calendar years (UTC days) with consumption or prices."""
        years = self.consumption.years()
        for table in self.prices.values():
            years |= table.years()
        return years

    def as_dict(self) -> dict[str, Any]:
        """The live state: everything except the archived days.

        Days before `archived_until` are kept in yearly archives (see
        `archive_dict`), so this stays small however long the period gets.
        """
        days_from = self.archived_until
        return {
            "meter": self.meter.as_dict(),
            "consumption": self.consumption.as_dict(ENERGY_DIGITS, start=days_from),
            "prices": {
                source: t.as_dict(start=days_from) for source, t in self.prices.items()
            },
            "started": self.started.isoformat() if self.started else None,
            "backfill_until": self.backfill_until.isoformat()
            if self.backfill_until
            else None,
            "archived_until": days_from.isoformat() if days_from else None,
            "meter_events": dict(self.meter_events),
        }

    def archive_dict(self, year: int, before: date) -> dict[str, Any]:
        """Consumption and prices of the UTC days of `year` before `before`."""
        start, end = date(year, 1, 1), min(before, date(year + 1, 1, 1))
        return {
            "consumption": self.consumption.as_dict(
                ENERGY_DIGITS, start=start, end=end
            ),
            "prices": {
                source: t.as_dict(start=start, end=end)
                for source, t in self.prices.items()
            },
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.meter.restore(data.get("meter", {}))
        self.consumption.restore(data.get("consumption", {}))
        # Fill the tables in place: tariffs hold references to them.
        for source, table_data in data.get("prices", {}).items():
            self.price_table(source).restore(table_data)
        started = data.get("started")
        self.started = datetime.fromisoformat(started) if started else None
        until = data.get("backfill_until")
        self.backfill_until = datetime.fromisoformat(until) if until else None
        archived = data.get("archived_until")
        self.archived_until = date.fromisoformat(archived) if archived else None
        self.meter_events = Counter(data.get("meter_events", {}))

    def restore_archive(self, data: dict[str, Any]) -> None:
        """Add an archived year; days in the live state take precedence."""
        self.consumption.restore(data.get("consumption", {}), merge=True)
        for source, table_data in data.get("prices", {}).items():
            self.price_table(source).restore(table_data, merge=True)


def migrate_v1(
    data: dict[str, Any], price_source: str, created: datetime
) -> dict[str, Any]:
    """Storage of 0.1.0b1 (running totals only) to version 2.

    Prices and the meter carry over. The consumption per quarter hour was not
    kept: it is read from the recorder from the setup of the entry up to the
    last reading 0.1.0b1 booked (`backfill_until`); later readings follow live.
    """
    meter = data.get("meter", {})
    return {
        "meter": meter,
        "consumption": {},
        "prices": {price_source: data.get("prices", {})},
        "started": slot_start(created).isoformat(),
        "backfill_until": meter.get("last_time"),
        "meter_events": data.get("meter_events", {}),
    }


def _book(
    tariff: Tariff,
    totals: TariffTotals,
    slot: datetime,
    energy: float,
    now: datetime,
) -> None:
    """Book a quarter hour's energy, or let it wait for its price."""
    price = tariff.price(slot)
    if price is not None:
        totals.energy += energy
        totals.consumption_cost += energy * price
    elif now - (slot + QUARTER) >= PRICE_WAIT:
        totals.energy_without_price += energy
    else:
        totals.pending[slot] = totals.pending.get(slot, 0.0) + energy
