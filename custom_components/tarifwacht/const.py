"""Constants for Tarifwacht. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from typing import Final
from zoneinfo import ZoneInfo

DOMAIN: Final = "tarifwacht"
VERSION: Final = "0.2.5"
USER_AGENT: Final = f"Tarifwacht/{VERSION} (+https://github.com/tarifwacht/integration)"

# Days (pro-rata base prices) and months follow German local time.
BERLIN: Final = ZoneInfo("Europe/Berlin")

# Config entry (one per meter).
CONF_NAME: Final = "name"
CONF_METER: Final = "meter_entity"
# Source entities renamed since the last start, {stored id: current id}: the
# next start moves the stored state to the current ids (rename.py).
CONF_RENAMED: Final = "renamed"

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
CONF_CHANGES: Final = "changes"  # later price states: [{"from": date, ...}]
CONF_FROM: Final = "from"  # ISO date, valid from local midnight
CONF_MODUL3: Final = "modul3"  # time-variable grid fee (§ 14a EnWG Modul 3)
# One-off bonus of a tariff (new-customer or switching bonus): EUR incl. VAT,
# credited at local midnight of its ISO date. In the form in a collapsed
# section.
CONF_BONUS: Final = "bonus"
CONF_BONUS_DATE: Final = "bonus_date"
SECTION_BONUS: Final = "bonus_section"
# Form sections only (nothing stored under these keys): VAT and base price
# period ("More"), Modul 3 in a price change.
SECTION_DETAILS: Final = "details_section"
SECTION_MODUL3: Final = "modul3_section"
# Exchange price tariff added later: the user agreed to fill the time since
# the setup that its sensor does not know with prices from SMARD.de.
CONF_SMARD_FILL: Final = "smard_fill"

# PV and battery subentry (at most one): what they saved (solar.py).
SUBENTRY_SOLAR: Final = "solar"
CONF_FEED_IN_ENTITY: Final = "feed_in_entity"  # energy fed into the grid
CONF_PV_ENTITY: Final = "pv_entity"  # PV, or the hybrid inverter's AC output
CONF_CHARGED_ENTITY: Final = "charged_entity"  # optional battery meters
CONF_DISCHARGED_ENTITY: Final = "discharged_entity"
CONF_SAME_INVERTER: Final = "same_inverter"  # battery behind the PV inverter
CONF_FEED_IN_RATE: Final = "feed_in_rate"  # ct/kWh
CONF_NEGATIVE_UNPAID: Final = "negative_unpaid"  # § 51 EEG
CONF_MARKET_ENTITY: Final = "market_entity"  # exchange price for § 51
# Purchase of PV and battery (payback.py), in the form in a collapsed
# section: cost in EUR, commissioning as ISO date. Without its own date the
# battery counts from the PV's.
CONF_PV_COST: Final = "pv_cost"
CONF_PV_SINCE: Final = "pv_since"
CONF_BATTERY_COST: Final = "battery_cost"
CONF_BATTERY_SINCE: Final = "battery_since"
SECTION_PURCHASE: Final = "purchase_section"
# Form section only: the exchange price sensor for section 51.
SECTION_MARKET: Final = "market_section"
# They change no past hour: no repair issue, no stale statistics.
PURCHASE_KEYS: Final = (
    CONF_PV_COST,
    CONF_PV_SINCE,
    CONF_BATTERY_COST,
    CONF_BATTERY_SINCE,
)

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
