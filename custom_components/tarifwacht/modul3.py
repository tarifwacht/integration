"""Time-variable grid fee under Modul 3 of § 14a EnWG. Pure Python.

BNetzA determination BK8-22/010-A (23.11.2023), tenor no. 3 and annex: three
levels - standard (the usual energy rate of the grid fee), high (HT) and low
(NT) - applied in at least two quarters of a year; outside them, and outside
the windows, the standard level applies. Windows are wall-clock times in
German local time (UTILTS AHB 1.1, § 8.4); price sheets show daily windows on
a quarter-hour grid, some across midnight. Sources and examples:
docs/ENTWICKLUNG.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, tzinfo
from itertools import pairwise
from typing import Any

LEVEL_HT = "ht"
LEVEL_NT = "nt"

_TIME = r"([01]?\d|2[0-4]):([0-5]\d)"
_WINDOW = re.compile(rf"^\s*{_TIME}\s*[-–]\s*{_TIME}\s*$")
DAY_MINUTES = 24 * 60


class WindowError(ValueError):
    """A window text that cannot be used; `key` names the reason."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def parse_windows(text: str) -> list[tuple[int, int]]:
    """ "10:00-14:00, 22:30-06:00" -> [(600, 840), (1350, 1440), (0, 360)].

    Minutes of the local day, end exclusive. A window ending at or before its
    start runs past midnight. Times must lie on the quarter-hour grid.
    """
    windows: list[tuple[int, int]] = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        match = _WINDOW.match(part)
        if match is None:
            raise WindowError("window_format")
        start = int(match[1]) * 60 + int(match[2])
        end = int(match[3]) * 60 + int(match[4])
        if start > DAY_MINUTES or end > DAY_MINUTES:
            raise WindowError("window_format")
        if start % 15 or end % 15:
            raise WindowError("window_grid")
        if start == end or (start == DAY_MINUTES and end == 0):
            raise WindowError("window_format")
        if end > start:
            windows.append((start, end))
        else:  # across midnight
            if start < DAY_MINUTES:
                windows.append((start, DAY_MINUTES))
            if end > 0:
                windows.append((0, end))
    return windows


def overlaps(*groups: list[tuple[int, int]]) -> bool:
    """Whether any two windows (of all groups) overlap."""
    spans = sorted(w for group in groups for w in group)
    return any(b[0] < a[1] for a, b in pairwise(spans))


@dataclass(frozen=True)
class Modul3:
    """Grid fee per quarter hour: HT/NT in their windows, else standard.

    Fees in EUR/kWh (net); `quarters` are the calendar quarters (1 to 4) in which
    the windows apply.
    """

    standard: float
    high: float
    low: float
    quarters: frozenset[int]
    high_windows: tuple[tuple[int, int], ...]
    low_windows: tuple[tuple[int, int], ...]
    tz: tzinfo

    def fee(self, slot: datetime) -> float:
        local = slot.astimezone(self.tz)
        if (local.month - 1) // 3 + 1 not in self.quarters:
            return self.standard
        minute = local.hour * 60 + local.minute
        if any(a <= minute < b for a, b in self.high_windows):
            return self.high
        if any(a <= minute < b for a, b in self.low_windows):
            return self.low
        return self.standard


def modul3_from_data(
    data: dict[str, Any], standard_ct: float, tz: tzinfo
) -> Modul3 | None:
    """From the stored values (ct/kWh, quarters, window texts); None if off."""
    if not data or not data.get("active"):
        return None
    return Modul3(
        standard=standard_ct / 100,
        high=float(data.get("ht") or 0) / 100,
        low=float(data.get("nt") or 0) / 100,
        quarters=frozenset(int(q) for q in data.get("quarters", [])),
        high_windows=tuple(parse_windows(data.get("ht_windows", ""))),
        low_windows=tuple(parse_windows(data.get("nt_windows", ""))),
        tz=tz,
    )
