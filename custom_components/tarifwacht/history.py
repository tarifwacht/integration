"""Values per quarter hour, kept for the whole accounting period.

Stored compactly as one list per UTC day: a UTC day always has 96 quarter
hours, also when Germany changes the clocks (its local day then spans parts
of two UTC days).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any

from .timeslots import QUARTER

SLOTS_PER_DAY = 96


def _position(slot: datetime) -> tuple[date, int]:
    utc = slot.astimezone(UTC)
    return utc.date(), (utc.hour * 60 + utc.minute) // 15


@dataclass
class SlotSeries:
    """A value (or None) per UTC quarter-hour start."""

    days: dict[date, list[float | None]] = field(default_factory=dict)

    def get(self, slot: datetime) -> float | None:
        day, index = _position(slot)
        values = self.days.get(day)
        return values[index] if values else None

    def set(self, slot: datetime, value: float) -> None:
        day, index = _position(slot)
        self.days.setdefault(day, [None] * SLOTS_PER_DAY)[index] = value

    def add(self, slot: datetime, value: float) -> None:
        day, index = _position(slot)
        values = self.days.setdefault(day, [None] * SLOTS_PER_DAY)
        values[index] = (values[index] or 0.0) + value

    def merge(self, values: Mapping[datetime, float]) -> None:
        for slot, value in values.items():
            self.set(slot, value)

    def items(self) -> Iterator[tuple[datetime, float]]:
        """All known values in chronological order."""
        for day in sorted(self.days):
            start = datetime.combine(day, time(), UTC)
            for index, value in enumerate(self.days[day]):
                if value is not None:
                    yield start + index * QUARTER, value

    def __len__(self) -> int:
        return sum(v is not None for values in self.days.values() for v in values)

    def as_dict(self, digits: int) -> dict[str, list[float | None]]:
        return {
            day.isoformat(): [None if v is None else round(v, digits) for v in values]
            for day, values in sorted(self.days.items())
        }

    def restore(self, data: Mapping[str, Any]) -> None:
        self.days = {
            date.fromisoformat(day): [None if v is None else float(v) for v in values]
            for day, values in data.items()
            if len(values) == SLOTS_PER_DAY
        }
