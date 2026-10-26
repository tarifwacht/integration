"""One meter's accounting under several tariffs.

Pure Python; the Home Assistant side (runtime.py) feeds it readings, price
forecasts and clock ticks, and stores `as_dict()`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any

from .ledger import Ledger, PriceSource
from .meter import MeterTracker, MeterUpdate
from .prices import ParsedPrices, PriceTable
from .tariffs import TariffValuation, base_price_per_slot
from .timeslots import QUARTER, slot_start

# Prices older than this are dropped from storage (pending pieces give up
# after a day).
PRICE_RETENTION = timedelta(days=15)

VALUATION = TariffValuation()


@dataclass
class TariffAccount:
    """Costs of one tariff: energy booked per quarter hour plus base price."""

    prices: PriceSource
    base_per_month: float = 0.0
    ledger: Ledger = field(default_factory=Ledger)
    base_cost: float = 0.0

    @property
    def consumption_cost(self) -> float:
        return self.ledger.totals.get("consumption_cost", 0.0)

    @property
    def cost(self) -> float:
        return self.consumption_cost + self.base_cost

    def as_dict(self) -> dict[str, Any]:
        return {"ledger": self.ledger.as_dict(), "base_cost": self.base_cost}

    def restore(self, data: dict[str, Any]) -> None:
        self.ledger.restore(data.get("ledger", {}))
        self.base_cost = data.get("base_cost", 0.0)


@dataclass
class Engine:
    """Books every meter reading into each tariff."""

    meter: MeterTracker
    tariffs: dict[str, TariffAccount]
    tz: tzinfo
    # Forecast prices of the dynamic tariff(s); shared with their accounts.
    prices: PriceTable = field(default_factory=PriceTable)
    energy: float = 0.0
    # Next quarter hour whose base price is still to be booked.
    next_base_slot: datetime | None = None
    meter_events: Counter[str] = field(default_factory=Counter)
    last_parse: ParsedPrices | None = None

    def on_meter(self, value_kwh: float, at: datetime, now: datetime) -> MeterUpdate:
        """A new meter reading in kWh."""
        update = self.meter.update(value_kwh, at)
        if update.event is not None:
            self.meter_events[update.event] += 1
        self.energy += sum(energy for _, energy in update.pieces)
        for account in self.tariffs.values():
            account.ledger.book(update.pieces, account.prices, VALUATION, now)
        return update

    def on_prices(self, parsed: ParsedPrices, now: datetime) -> None:
        """A new price forecast from the dynamic price sensor."""
        self.last_parse = parsed
        self.prices.merge(parsed.prices)
        self.tick(now)

    def tick(self, now: datetime) -> None:
        """Clock tick (every quarter hour), after new prices and on start."""
        for account in self.tariffs.values():
            account.ledger.retry_pending(account.prices, VALUATION, now)
        self._book_base_prices(now)
        self.prices.prune(slot_start(now) - PRICE_RETENTION)

    def _book_base_prices(self, now: datetime) -> None:
        """Base prices of every quarter hour that ended by `now`.

        Counting starts with the running quarter hour of the first start. The
        base price is owed while Home Assistant is off, too: gaps are caught up.
        """
        current = slot_start(now)
        if self.next_base_slot is None:
            self.next_base_slot = current
            return
        while self.next_base_slot < current:
            slot = self.next_base_slot
            for account in self.tariffs.values():
                if account.base_per_month:
                    account.base_cost += base_price_per_slot(
                        slot, account.base_per_month, self.tz
                    )
            self.next_base_slot = slot + QUARTER

    def as_dict(self) -> dict[str, Any]:
        return {
            "meter": self.meter.as_dict(),
            "prices": self.prices.as_dict(),
            "energy": self.energy,
            "next_base_slot": self.next_base_slot.isoformat()
            if self.next_base_slot
            else None,
            "tariffs": {key: a.as_dict() for key, a in self.tariffs.items()},
            "meter_events": dict(self.meter_events),
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.meter.restore(data.get("meter", {}))
        self.prices.restore(data.get("prices", {}))
        self.energy = data.get("energy", 0.0)
        next_base_slot = data.get("next_base_slot")
        self.next_base_slot = (
            datetime.fromisoformat(next_base_slot) if next_base_slot else None
        )
        for key, account_data in data.get("tariffs", {}).items():
            if key in self.tariffs:
                self.tariffs[key].restore(account_data)
        self.meter_events = Counter(data.get("meter_events", {}))
