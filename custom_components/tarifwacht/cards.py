"""The Lovelace card (frontend/tarifwacht-card.js).

The integration serves the file itself and registers it with the frontend
as a dashboard resource (frontend_resource.py), so nobody has to add one; a
new version busts the cache by its query string (pattern of Wärmewacht).

The card is configured with one entity of an entry ("Cheapest tariff"). What
belongs to that entry - its tariffs, which one is current, their sensors and
whether PV and a battery are set up - only the entry knows: the websocket
command "tarifwacht/tariffs" hands it out. Entity ids are looked up in the
entity registry by unique id when the card asks, so renamed entities need no
change in the card; they stay out of the state attributes (and the recorder).
The card reads the values per day, month and year from the long-term
statistics itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, VERSION
from .runtime import has_battery

if TYPE_CHECKING:
    from .runtime import MeterRuntime

CARD_FILE = "tarifwacht-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
# The URL the frontend loads: a new version is a new URL (no stale cache).
CARD_RESOURCE_URL = f"{CARD_URL}?v={VERSION}"
# The sensors of a tariff the card shows (keys as in the unique ids).
TARIFF_KEYS = (
    "cost",
    "consumption_cost",
    "average_price",
    "difference",
    "saving_pv",
    "saving_battery",
)


async def async_setup_cards(hass: HomeAssistant) -> None:
    """Serve the card and register the websocket command; without http
    (tests) only the command. The frontend learns of the card per entry
    (frontend_resource.async_register_card)."""
    websocket_api.async_register_command(hass, ws_tariffs)
    if getattr(hass, "http", None) is None:
        return
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "frontend" / CARD_FILE
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), True)]
    )


def card_info(hass: HomeAssistant, entity_id: str) -> dict[str, Any] | None:
    """What the card shows for the entry of a Tarifwacht entity; None if the
    entity is not one of a loaded Tarifwacht entry."""
    registry = er.async_get(hass)
    entity = registry.async_get(entity_id)
    if entity is None or entity.platform != DOMAIN or not entity.config_entry_id:
        return None
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        return None
    runtime: MeterRuntime = entry.runtime_data

    def lookup(key: str) -> str | None:
        found = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}"
        )
        if found is None:
            return None
        registry_entry = registry.async_get(found)
        return None if registry_entry is None or registry_entry.disabled else found

    current = runtime.current
    tariffs: list[dict[str, Any]] = []
    for tariff in runtime.tariffs.values():
        entities = {
            key: found
            for key in TARIFF_KEYS
            if (found := lookup(f"{tariff.key}_{key}")) is not None
        }
        tariffs.append(
            {
                "key": tariff.key,
                "title": tariff.title,
                "current": current is not None and tariff.key == current.key,
                "entities": entities,
            }
        )
    solar = runtime.solar_data is not None
    return {
        "title": entry.title,
        "cheapest": lookup("cheapest"),
        "energy": lookup("energy"),
        "current": None if current is None else current.key,
        "solar": solar,
        "battery": solar and has_battery(runtime.solar_data),
        "tariffs": tariffs,
    }


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/tariffs", vol.Required("entity_id"): str}
)
@callback
def ws_tariffs(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Tariffs and sensors of the entry of a Tarifwacht entity, for the card."""
    info = card_info(hass, msg["entity_id"])
    if info is None:
        connection.send_error(msg["id"], "not_found", "No Tarifwacht entry")
        return
    connection.send_result(msg["id"], info)
