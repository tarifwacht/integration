"""Sanity checks for the recorded price fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

from tests.conftest import load_fixture

QUARTER = timedelta(minutes=15)


def _slots(entries: list[dict]) -> list[tuple[datetime, datetime, float]]:
    return [
        (
            datetime.fromisoformat(e["start_time"]),
            datetime.fromisoformat(e["end_time"]),
            e["price_per_kwh"],
        )
        for e in entries
    ]


def test_epex_dst_day_is_contiguous() -> None:
    fixture = load_fixture("epex_spot_2026-10-25.json")
    slots = _slots(fixture["history_supplement"] + fixture["attributes"]["data"])
    for (start, end, _), (next_start, _, _) in pairwise(slots):
        assert end - start == QUARTER
        assert end == next_start


def test_epex_dst_day_contents() -> None:
    fixture = load_fixture("epex_spot_2026-10-25.json")
    slots = _slots(fixture["history_supplement"] + fixture["attributes"]["data"])
    # 25.10.2026 local time = 2026-10-24T22:00Z .. 2026-10-25T23:00Z (25 hours).
    day_start = datetime(2026, 10, 24, 22, tzinfo=UTC)
    day_end = datetime(2026, 10, 25, 23, tzinfo=UTC)
    day = [s for s in slots if day_start <= s[0] < day_end]
    assert len(day) == 100
    assert sum(1 for s in day if s[2] == 0) == 48
    negative = [s[0].astimezone(UTC).strftime("%H:%M") for s in day if s[2] < 0]
    # 04:00, 04:30, 06:00, 14:00, 14:15, 15:00 CET
    assert negative == ["03:00", "03:30", "05:00", "13:00", "13:15", "14:00"]
    # The repeated hour: 02:45 CEST ends at 02:00 CET.
    assert any(
        e["start_time"] == "2026-10-25T02:45:00+02:00"
        and e["end_time"] == "2026-10-25T02:00:00+01:00"
        for e in fixture["attributes"]["data"]
    )
