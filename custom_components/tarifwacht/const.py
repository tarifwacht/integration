"""Constants for Tarifwacht. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from typing import Final
from zoneinfo import ZoneInfo

DOMAIN: Final = "tarifwacht"
VERSION: Final = "0.1.0b3"

# Days (pro-rata base prices) and months follow German local time.
BERLIN: Final = ZoneInfo("Europe/Berlin")

# Config entry (one per meter).
CONF_NAME: Final = "name"
CONF_METER: Final = "meter_entity"

# Initial setup form; stored as two tariff subentries.
CONF_FIXED_PRICE: Final = "fixed_price"  # ct/kWh incl. VAT
CONF_FIXED_BASE: Final = "fixed_base"  # EUR/month incl. VAT
CONF_DYNAMIC_PRICE: Final = "dynamic_price_entity"  # total price, EUR/kWh
CONF_DYNAMIC_BASE: Final = "dynamic_base"  # EUR/month incl. VAT

# Tariff subentries.
SUBENTRY_TARIFF: Final = "tariff"
CONF_KIND: Final = "kind"
CONF_KEY: Final = "key"  # stable id in unique ids and storage
CONF_PRICE: Final = "price"  # fixed: ct/kWh incl. VAT
CONF_PRICE_ENTITY: Final = "price_entity"  # dynamic: total or exchange price
CONF_GRID_FEE: Final = "grid_fee"  # ct/kWh net
CONF_LEVIES: Final = "levies"  # taxes, levies, concession fee: ct/kWh net
CONF_MARGIN: Final = "margin"  # supplier surcharge: ct/kWh net
CONF_VAT: Final = "vat"  # percent
CONF_BASE_PRICE: Final = "base_price"  # EUR incl. VAT per period
CONF_BASE_PERIOD: Final = "base_period"  # "month" or "year"
CONF_CURRENT: Final = "current"  # the tariff the others are compared with

KIND_FIXED: Final = "fixed"
KIND_DYNAMIC_TOTAL: Final = "dynamic_total"
KIND_DYNAMIC_MARKET: Final = "dynamic_market"
KINDS: Final = (KIND_FIXED, KIND_DYNAMIC_TOTAL, KIND_DYNAMIC_MARKET)

# Keys of the two tariffs of version 0.1.0b1, kept for its entities.
TARIFF_FIXED: Final = "fixed"
TARIFF_DYNAMIC: Final = "dynamic"

DEFAULT_VAT: Final = 19.0

# Units a price sensor may report; prices are used as they are, so only
# EUR/kWh (verified with EPEX Spot, see tests/fixtures) is accepted.
PRICE_UNITS: Final = ("€/kWh", "EUR/kWh")

# Upper bound for plausible grid purchase (larger than any household
# connection); larger increases are treated as meter glitches.
MAX_GRID_POWER_KW: Final = 100.0
