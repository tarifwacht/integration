"""Expected quarter-hours per SMARD week in tools/source_check.py."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.tarifwacht.const import BERLIN
from tools.source_check import week_slots


@pytest.mark.parametrize(
    ("monday", "slots"),
    [
        (datetime(2026, 10, 12, tzinfo=BERLIN), 672),
        # 25.10.: clocks back, 100 quarter-hours
        (datetime(2026, 10, 19, tzinfo=BERLIN), 676),
        # 29.03.: clocks forward, 92 quarter-hours
        (datetime(2026, 3, 23, tzinfo=BERLIN), 668),
        (datetime(2026, 10, 26, tzinfo=BERLIN), 672),
    ],
)
def test_week_slots(monday: datetime, slots: int) -> None:
    assert week_slots(monday) == slots
