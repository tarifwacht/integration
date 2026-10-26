"""Diagnostics download (Settings > Devices & services > Tarifwacht > ⋮).

No personal data: no name, no meter readings, no energy or cost totals.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import TarifwachtConfigEntry
from .const import CONF_NAME, VERSION


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TarifwachtConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    runtime = entry.runtime_data
    engine = runtime.engine
    parsed = engine.last_parse
    return {
        "version": VERSION,
        "config": {k: v for k, v in entry.data.items() if k != CONF_NAME},
        "prices": {
            "known_quarter_hours": len(engine.prices.prices),
            "first": min(engine.prices.prices).isoformat()
            if engine.prices.prices
            else None,
            "last": max(engine.prices.prices).isoformat()
            if engine.prices.prices
            else None,
            "resolution_minutes": parsed.resolution.total_seconds() / 60
            if parsed and parsed.resolution
            else None,
            "skipped_entries": parsed.skipped if parsed else None,
            "wrong_unit": runtime.wrong_price_unit,
        },
        "meter": {
            "unknown_unit": runtime.unknown_unit,
            "events": dict(engine.meter_events),
            "last_reading": engine.meter.last_time.isoformat()
            if engine.meter.last_time
            else None,
        },
        "tariffs": {
            key: {
                "pending_quarter_hours": len(account.ledger.pending),
                "booked_without_price": account.ledger.booked_without_price,
                "has_energy_without_price": "energy_without_price"
                in account.ledger.totals,
            }
            for key, account in engine.tariffs.items()
        },
        "next_base_slot": engine.next_base_slot.isoformat()
        if engine.next_base_slot
        else None,
    }
