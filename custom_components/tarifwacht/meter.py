"""Turn readings of a cumulative energy meter into energy per quarter hour.

Derived from einspeisewacht/custom_components/einspeisewacht/meter.py (as of
1a69db8), adapted: no spreading of long gaps by a weight (GAP), no aliases of
a renamed meter (rename.py moves the stored state), limits described for grid
purchase, the bound of a plausible increase counts from the last change of
the value (`last_change`), not from the last reading. A bug there may be here
too; tools/check_shared.py in the parent folder reports changes to the
original.

Why the last change: after a restart of Home Assistant the meter's
integration writes its old value again with a new time stamp. Counted from
that reading, the next real increase a few seconds later looked like far more
than the house connection can deliver and was dropped as a jump (seen
2026-11-09: 0.86 kWh three seconds after the old value, bound 0.13 kWh).
The energy is still spread from the last reading on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .timeslots import split_interval

# Factor to kWh for the units an energy sensor may report.
UNIT_FACTORS = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}

# Peak power may briefly exceed the rated limit (PV: cold, bright days; grid
# purchase: fuse tolerance); readings in whole Wh add rounding noise on short
# intervals.
POWER_MARGIN = 1.5
ROUNDING_TOLERANCE_KWH = 0.002


class MeterEvent(StrEnum):
    """What a reading did besides delivering energy."""

    FIRST = "first"  # no previous reading: baseline only
    RESET = "reset"  # counter went backwards: new baseline, nothing booked
    JUMP = "jump"  # implausibly large increase: new baseline, nothing booked


def to_kwh(value: float, unit: str | None) -> float:
    """Convert a meter value to kWh; raises KeyError for unknown units."""
    return value * UNIT_FACTORS[unit or ""]


@dataclass
class MeterUpdate:
    """Result of one reading."""

    pieces: list[tuple[datetime, float]] = field(default_factory=list)
    event: MeterEvent | None = None
    delta: float = 0.0


@dataclass
class MeterTracker:
    """Track the last reading and split each increase into quarter hours.

    `max_power_kw` bounds plausible increases (for grid purchase: the rated
    power of the house connection). `source` names the meter (its entity);
    a stored reading of another meter is not restored, so a swapped meter
    starts with a new baseline.
    """

    max_power_kw: float
    last_value: float | None = None
    last_time: datetime | None = None
    source: str | None = None
    # When the value last changed (or the baseline began): the bound of a
    # plausible increase counts from here (see the module).
    last_change: datetime | None = None

    def update(self, value: float, at: datetime) -> MeterUpdate:
        """Process a reading in kWh taken at `at` (timezone-aware)."""
        previous_value, previous_time = self.last_value, self.last_time
        if previous_time is not None and at < previous_time:
            # Out-of-order reading: ignore, keep the newer baseline.
            return MeterUpdate()
        changed_at = self.last_change or previous_time
        self.last_value, self.last_time = value, at
        if previous_value is None or previous_time is None or changed_at is None:
            self.last_change = at
            return MeterUpdate(event=MeterEvent.FIRST)
        delta = value - previous_value
        if delta == 0:
            return MeterUpdate()
        self.last_change = at
        if delta < 0:
            return MeterUpdate(event=MeterEvent.RESET, delta=delta)
        hours = (at - changed_at).total_seconds() / 3600
        if delta > self.max_power_kw * POWER_MARGIN * hours + ROUNDING_TOLERANCE_KWH:
            return MeterUpdate(event=MeterEvent.JUMP, delta=delta)
        return MeterUpdate(pieces=split_interval(previous_time, at, delta), delta=delta)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_value": self.last_value,
            "last_time": self.last_time.isoformat() if self.last_time else None,
            "last_change": self.last_change.isoformat() if self.last_change else None,
            "source": self.source,
        }

    def restore(self, data: dict[str, Any]) -> None:
        stored = data.get("source")
        if stored is not None and self.source is not None and stored != self.source:
            # Another meter (swapped in the reconfiguration): its last reading
            # is no baseline for this one; the first reading starts afresh.
            return
        self.last_value = data.get("last_value")
        last_time = data.get("last_time")
        self.last_time = datetime.fromisoformat(last_time) if last_time else None
        # Stored before 0.2.6: the last reading is the best guess.
        last_change = data.get("last_change") or last_time
        self.last_change = datetime.fromisoformat(last_change) if last_change else None
