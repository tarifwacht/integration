"""Book energy per quarter hour against the price of that quarter hour.

The ledger is the reusable core: it looks up prices, holds back pieces whose
price is not known yet and keeps running totals. What a booking means (purchase
cost under a tariff) is decided by a valuation.

Copied from Einspeisewacht (commit e4fd5fc, without its feed-in valuation),
developed independently since.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from .prices import PriceTable

# How long a piece waits for its price before it is booked without one.
PRICE_WAIT = timedelta(hours=24)


class Valuation(Protocol):
    """Adds one piece of energy to the totals."""

    def book(
        self,
        totals: dict[str, float],
        slot: datetime,
        energy: float,
        price: float | None,
    ) -> None: ...


@dataclass
class Ledger:
    """Running totals plus pieces still waiting for their price."""

    totals: dict[str, float] = field(default_factory=dict)
    # slot -> [energy, first seen]
    pending: dict[datetime, tuple[float, datetime]] = field(default_factory=dict)
    booked_without_price: int = 0

    def book(
        self,
        pieces: Iterable[tuple[datetime, float]],
        prices: PriceTable,
        valuation: Valuation,
        now: datetime,
    ) -> None:
        """Book pieces whose price is known; hold back the others."""
        for slot, energy in pieces:
            price = prices.get(slot)
            if price is None:
                held, since = self.pending.get(slot, (0.0, now))
                self.pending[slot] = (held + energy, since)
            else:
                valuation.book(self.totals, slot, energy, price)

    def retry_pending(
        self, prices: PriceTable, valuation: Valuation, now: datetime
    ) -> None:
        """Book held-back pieces once their price is known or the wait is over."""
        for slot, (energy, since) in sorted(self.pending.items()):
            price = prices.get(slot)
            if price is None and now - since < PRICE_WAIT:
                continue
            if price is None:
                self.booked_without_price += 1
            valuation.book(self.totals, slot, energy, price)
            del self.pending[slot]

    def as_dict(self) -> dict[str, Any]:
        return {
            "totals": dict(self.totals),
            "pending": [
                [slot.isoformat(), energy, since.isoformat()]
                for slot, (energy, since) in sorted(self.pending.items())
            ],
            "booked_without_price": self.booked_without_price,
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.totals = dict(data.get("totals", {}))
        self.pending = {
            datetime.fromisoformat(slot): (energy, datetime.fromisoformat(since))
            for slot, energy, since in data.get("pending", [])
        }
        self.booked_without_price = data.get("booked_without_price", 0)
