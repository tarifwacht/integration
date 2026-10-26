"""Historical day-ahead prices from SMARD.de (Bundesnetzagentur).

Used by the compare action for periods before the setup of an entry. The
chart_data endpoints back the SMARD website and are not documented as an API;
formats are taken from tests/fixtures/smard_*.json. Filter 4169 is the
day-ahead price for the bidding zone DE-LU in EUR/MWh, delivered in weekly
files that start on Monday 00:00 local time. Before 1 October 2025 the
quarter-hour series repeats each hourly price four times.

Copied from Einspeisewacht (commit 65857dc), developed independently since.

Data: Bundesnetzagentur | SMARD.de, CC BY 4.0.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .timeslots import slot_start

ATTRIBUTION = "Bundesnetzagentur | SMARD.de (CC BY 4.0)"
BASE_URL = "https://www.smard.de/app/chart_data/4169/DE-LU"
INDEX_URL = f"{BASE_URL}/index_quarterhour.json"
WEEK = timedelta(days=7, hours=1)  # a week file spans 7 days, +1 h in October


def week_url(week_start_ms: int) -> str:
    return f"{BASE_URL}/4169_DE-LU_quarterhour_{week_start_ms}.json"


def week_start(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


def parse_index(data: Mapping[str, Any]) -> list[int]:
    """Week start timestamps (ms) in ascending order."""
    return sorted(int(t) for t in data["timestamps"])


def weeks_covering(index: list[int], start: datetime, end: datetime) -> list[int]:
    """Week files needed for the quarter hours from `start` to `end`."""
    return [t for t in index if week_start(t) < end and week_start(t) + WEEK > start]


def parse_week(data: Mapping[str, Any]) -> dict[datetime, float]:
    """Prices in EUR/kWh by UTC quarter-hour start; missing values (null) are skipped."""
    prices: dict[datetime, float] = {}
    for ms, value in data["series"]:
        if value is None:
            continue
        moment = week_start(int(ms))
        if slot_start(moment) == moment:
            prices[moment] = float(value) / 1000
    return prices
