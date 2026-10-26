"""Diagnostics download (Settings > Devices & services > Tarifwacht > ⋮).

No personal data: no name, no meter readings, no energy or cost totals.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import TarifwachtConfigEntry
from .const import CONF_NAME, VERSION
from .history import SlotSeries


def _span(series: SlotSeries) -> dict[str, Any]:
    slots = [slot for slot, _ in series.items()]
    return {
        "quarter_hours": len(slots),
        "first": slots[0].isoformat() if slots else None,
        "last": slots[-1].isoformat() if slots else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TarifwachtConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    runtime = entry.runtime_data
    engine = runtime.engine
    return {
        "version": VERSION,
        "config": {k: v for k, v in entry.data.items() if k != CONF_NAME},
        "started": engine.started.isoformat() if engine.started else None,
        "consumption": _span(engine.consumption),
        "prices": {
            source: {
                **_span(table),
                "resolution_minutes": parsed.resolution.total_seconds() / 60
                if (parsed := engine.last_parse.get(source)) and parsed.resolution
                else None,
                "skipped_entries": parsed.skipped if parsed else None,
            }
            for source, table in engine.prices.items()
        },
        "wrong_price_unit": runtime.wrong_price_unit,
        "meter": {
            "unknown_unit": runtime.unknown_unit,
            "events": dict(engine.meter_events),
            "last_reading": engine.meter.last_time.isoformat()
            if engine.meter.last_time
            else None,
        },
        "backfill": {
            "pending_until": engine.backfill_until.isoformat()
            if engine.backfill_until
            else None,
            "error": runtime.backfill_error,
        },
        "tariffs": {
            key: {
                "pending_quarter_hours": len(totals.pending),
                "has_energy_without_price": totals.energy_without_price > 0,
            }
            for key, totals in engine.totals.items()
        },
    }
