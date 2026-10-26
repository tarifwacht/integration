"""Tests for the config flow and reconfiguration."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifwacht.const import CONF_FIXED_PRICE, DOMAIN

from .conftest import METER, METER_ATTRIBUTES, PRICE, entry_data, price_attributes

METER_STEP = {"name": "Haus", "meter_entity": METER}
TARIFFS = {
    "fixed_price": 30.0,
    "fixed_base": 31.0,
    "dynamic_price_entity": PRICE,
}


@pytest.fixture(autouse=True)
def no_setup() -> Iterator[AsyncMock]:
    """Flows are tested without actually setting up the entry."""
    with patch(
        "custom_components.tarifwacht.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def sources(hass: HomeAssistant) -> None:
    hass.states.async_set(METER, "1234567.0", METER_ATTRIBUTES)
    hass.states.async_set(PRICE, "0.10574", price_attributes())


async def start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def configure(hass: HomeAssistant, result: dict, user_input: dict) -> dict:
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_full_flow(hass: HomeAssistant) -> None:
    result = await start(hass)
    assert result["step_id"] == "user"
    result = await configure(hass, result, METER_STEP)
    assert result["step_id"] == "tariffs"
    # No dynamic base price entered: stored as 0.
    result = await configure(hass, result, TARIFFS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Haus"
    assert result["data"] == entry_data()
    assert result["result"].unique_id == METER


async def test_meter_errors(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.power", "500", {"unit_of_measurement": "W"})
    hass.states.async_set(
        "sensor.daily",
        "3.2",
        {"unit_of_measurement": "kWh", "state_class": "measurement"},
    )
    result = await start(hass)
    for meter, error in (
        ("sensor.missing", "entity_missing"),
        ("sensor.power", "meter_unit"),
        ("sensor.daily", "meter_state_class"),
    ):
        result = await configure(hass, result, {"name": "Haus", "meter_entity": meter})
        assert result["errors"] == {"meter_entity": error}
    result = await configure(hass, result, {"name": "  ", "meter_entity": METER})
    assert result["errors"] == {"name": "name_required"}


async def test_price_errors(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.price_ct", "10.5", {"unit_of_measurement": "ct/kWh"})
    hass.states.async_set("sensor.text", "cheap", {"unit_of_measurement": "€/kWh"})
    result = await configure(hass, await start(hass), METER_STEP)
    for price, error in (
        ("sensor.missing", "entity_missing"),
        ("sensor.price_ct", "price_unit"),
        ("sensor.text", "price_invalid"),
    ):
        result = await configure(
            hass, result, {**TARIFFS, "dynamic_price_entity": price}
        )
        assert result["errors"] == {"dynamic_price_entity": error}
    result = await configure(hass, result, {**TARIFFS, "fixed_price": 0})
    assert result["errors"] == {"fixed_price": "price_required"}


async def test_state_only_price_sensor(hass: HomeAssistant) -> None:
    """Without a forecast attribute the current state is the price."""
    hass.states.async_set("sensor.price_now", "0.31", {"unit_of_measurement": "€/kWh"})
    result = await configure(hass, await start(hass), METER_STEP)
    result = await configure(
        hass, result, {**TARIFFS, "dynamic_price_entity": "sensor.price_now"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_meter_already_configured(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=METER, title="Haus", data=entry_data()
    ).add_to_hass(hass)
    result = await configure(hass, await start(hass), METER_STEP)
    assert result["errors"] == {"meter_entity": "meter_in_use"}


async def test_reconfigure(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=METER, title="Haus", data=entry_data()
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    # The own meter is not "in use".
    result = await configure(hass, result, {**METER_STEP, "name": "Wohnung"})
    assert result["step_id"] == "tariffs"
    result = await configure(hass, result, {**TARIFFS, "fixed_price": 32.5})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Wohnung"
    assert entry.data[CONF_FIXED_PRICE] == 32.5
