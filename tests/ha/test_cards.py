"""The card: the websocket command hands it the tariffs and their sensors."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifwacht.const import DOMAIN
from custom_components.tarifwacht.runtime import MeterRuntime

from .test_init import setup
from .test_solar import set_sources, solar_entry


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert found, key
    return found


async def ask(hass: HomeAssistant, hass_ws_client: Any, entity: str) -> dict:
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "tarifwacht/tariffs", "entity_id": entity})
    return await client.receive_json()


async def test_tariffs_for_the_card(hass: HomeAssistant, hass_ws_client) -> None:
    assert await async_setup_component(hass, "websocket_api", {})
    entry = await setup(hass)
    cheapest = entity_id(hass, entry, "cheapest")
    reply = await ask(hass, hass_ws_client, cheapest)
    assert reply["success"]
    result = reply["result"]
    assert result["title"] == "Haus"
    assert result["cheapest"] == cheapest
    assert result["energy"] == entity_id(hass, entry, "energy")
    assert result["current"] == "fixed"
    assert result["solar"] is False
    assert result["battery"] is False
    fixed, dynamic = result["tariffs"]
    assert fixed["key"] == "fixed"
    assert fixed["title"] == "Fixed price"
    assert fixed["current"] is True
    assert dynamic["current"] is False
    # The current tariff has no difference to itself.
    assert set(fixed["entities"]) == {"cost", "consumption_cost", "average_price"}
    assert dynamic["entities"] == {
        key: entity_id(hass, entry, f"dynamic_{key}")
        for key in ("cost", "consumption_cost", "average_price", "difference")
    }
    # "Cheapest tariff" names the current tariff for dashboards.
    assert hass.states.get(cheapest).attributes["current"] == "Fixed price"

    # Any entity of the entry will do; renamed entities are found anew.
    registry = er.async_get(hass)
    old = dynamic["entities"]["cost"]
    registry.async_update_entity(old, new_entity_id="sensor.renamed_cost")
    await hass.async_block_till_done()
    reply = await ask(hass, hass_ws_client, fixed["entities"]["cost"])
    assert reply["result"]["tariffs"][1]["entities"]["cost"] == "sensor.renamed_cost"

    for unknown in ("sensor.nope", "sun.sun"):
        reply = await ask(hass, hass_ws_client, unknown)
        assert not reply["success"]
        assert reply["error"]["code"] == "not_found"


async def test_tariffs_with_pv_and_battery(hass: HomeAssistant, hass_ws_client) -> None:
    assert await async_setup_component(hass, "websocket_api", {})
    set_sources(hass)
    entry = solar_entry()
    entry.add_to_hass(hass)
    no_statistics = AsyncMock(return_value={})
    with patch.object(MeterRuntime, "_async_hourly", no_statistics):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    reply = await ask(hass, hass_ws_client, entity_id(hass, entry, "cheapest"))
    result = reply["result"]
    assert result["solar"] is True
    assert result["battery"] is True
    for tariff in result["tariffs"]:
        assert tariff["entities"]["saving_pv"] == entity_id(
            hass, entry, f"{tariff['key']}_saving_pv"
        )
        assert tariff["entities"]["saving_battery"] == entity_id(
            hass, entry, f"{tariff['key']}_saving_battery"
        )

    # An unloaded entry has nothing to show.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    reply = await ask(hass, hass_ws_client, entity_id(hass, entry, "cheapest"))
    assert reply["error"]["code"] == "not_found"


async def test_card_file_is_served(hass: HomeAssistant, hass_client) -> None:
    """The integration serves its card file itself."""
    assert await async_setup_component(hass, "http", {})
    await setup(hass)
    client = await hass_client()
    response = await client.get("/tarifwacht/tarifwacht-card.js")
    assert response.status == 200
    text = await response.text()
    assert "tarifwacht-card-editor" in text
