"""Constants for Tarifwacht. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from typing import Final
from zoneinfo import ZoneInfo

DOMAIN: Final = "tarifwacht"
VERSION: Final = "0.1.0b1"

# Days (pro-rata base prices) and months follow German local time.
BERLIN: Final = ZoneInfo("Europe/Berlin")

CONF_NAME: Final = "name"
CONF_METER: Final = "meter_entity"
CONF_FIXED_PRICE: Final = "fixed_price"  # ct/kWh incl. VAT
CONF_FIXED_BASE: Final = "fixed_base"  # EUR/month incl. VAT
CONF_DYNAMIC_PRICE: Final = "dynamic_price_entity"  # total price, EUR/kWh
CONF_DYNAMIC_BASE: Final = "dynamic_base"  # EUR/month incl. VAT

TARIFF_FIXED: Final = "fixed"
TARIFF_DYNAMIC: Final = "dynamic"

# Units a price sensor may report; prices are used as they are, so only
# EUR/kWh (verified with EPEX Spot, see tests/fixtures) is accepted.
PRICE_UNITS: Final = ("€/kWh", "EUR/kWh")

# Upper bound for plausible grid purchase (larger than any household
# connection); larger increases are treated as meter glitches.
MAX_GRID_POWER_KW: Final = 100.0
