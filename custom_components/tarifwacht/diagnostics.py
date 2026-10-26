"""Diagnostics download (Settings > Devices & services > Tarifwacht > ⋮).

No personal data: no names, no meter readings, no energy or cost totals.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import TarifwachtConfigEntry
from .const import CONF_NAME, VERSION
from .history import SlotSeries
from .prices import attribute_shape
from .runtime import tariff_subentries
from .tariff_config import tariff_key


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
        "tariffs": {
            tariff_key(s.subentry_id, s.data): {
                "config": dict(s.data),
                "pending_quarter_hours": len(totals.pending),
                "has_energy_without_price": totals.energy_without_price > 0,
            }
            for s in tariff_subentries(entry)
            if (totals := engine.totals.get(tariff_key(s.subentry_id, s.data)))
        },
        "started": engine.started.isoformat() if engine.started else None,
        "consumption": _span(engine.consumption),
        "prices": {
            source: {
                **_span(table),
                "resolution_minutes": parsed.resolution.total_seconds() / 60
                if (parsed := engine.last_parse.get(source)) and parsed.resolution
                else None,
                "skipped_entries": parsed.skipped if parsed else None,
                "format": parsed.format if parsed else None,
                # Keys and types of list attributes (no values), to support
                # further price sources from what users send in.
                "attribute_shape": attribute_shape(state.attributes)
                if (state := hass.states.get(source))
                else None,
                "wrong_unit": runtime.wrong_price_unit.get(source),
            }
            for source, table in engine.prices.items()
        },
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
    }
