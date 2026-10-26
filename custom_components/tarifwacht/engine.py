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
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .history import SlotSeries
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
        self, start: datetime, end: datetime, now: datetime
    ) -> PeriodCosts:
        """Costs of every tariff for the quarter hours in [start, end).

        Same rules as the running totals; the period is clipped to the
        accounting period (`started` up to the running quarter hour).
        """
        first = max(slot_start(start), self.started or slot_start(now))
        # A quarter hour that begins before `end` belongs to the period.
        end_slot = slot_start(end)
        if end_slot < end:
            end_slot += QUARTER
        last = min(end_slot, slot_start(now) + QUARTER)
        result = PeriodCosts(
            start=first,
            end=max(first, last),
            totals={key: TariffTotals() for key in self.tariffs},
        )
        for slot, energy in self.consumption.items():
            if first <= slot < last:
                result.energy += energy
                result.quarter_hours += 1
                for key, totals in result.totals.items():
                    self._book_one(key, totals, slot, energy, now)
        # Base prices of the quarter hours that have ended.
        base_end = min(last, slot_start(now))
        for key, tariff in self.tariffs.items():
            if first < base_end:
                result.totals[key].base_cost = tariff.base_between(
                    first, base_end, self.tz
                )
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
        self.price_table(source).merge(parsed.prices)
        self.tick(now)

    def tick(self, now: datetime) -> None:
        """Clock tick (every quarter hour) and after new prices."""
        for key, totals in self.totals.items():
            if totals.pending:
                pending, totals.pending = totals.pending, {}
                for slot, energy in sorted(pending.items()):
                    self._book_one(key, totals, slot, energy, now)
        self._book_base_prices(now)

    def _book(self, pieces: Iterable[tuple[datetime, float]], now: datetime) -> None:
        for slot, energy in pieces:
            self.energy += energy
            for key, totals in self.totals.items():
                self._book_one(key, totals, slot, energy, now)

    def _book_one(
        self,
        key: str,
        totals: TariffTotals,
        slot: datetime,
        energy: float,
        now: datetime,
    ) -> None:
        price = self.tariffs[key].price(slot)
        if price is not None:
            totals.energy += energy
            totals.consumption_cost += energy * price
        elif now - (slot + QUARTER) >= PRICE_WAIT:
            totals.energy_without_price += energy
        else:
            totals.pending[slot] = totals.pending.get(slot, 0.0) + energy

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
