"""Constants for Tarifwacht. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from typing import Final
from zoneinfo import ZoneInfo

DOMAIN: Final = "tarifwacht"
VERSION: Final = "0.1.0.dev0"

# Days (pro-rata base prices) and months follow German local time.
BERLIN: Final = ZoneInfo("Europe/Berlin")
