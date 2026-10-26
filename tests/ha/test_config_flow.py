"""Tests for the config flow, reconfiguration and tariff subentries."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifwacht.const import CONF_CURRENT, DOMAIN

from .conftest import (
    DYNAMIC_SUBENTRY,
    FIXED_SUBENTRY,
    METER,
    METER_ATTRIBUTES,
    PRICE,
    dynamic_tariff,
    entry_data,
    fixed_tariff,
    mock_entry,
    price_attributes,
)

METER_STEP = {"name": "Haus", "meter_entity": METER}
TARIFFS = {
    "fixed_price": 30.0,
    "fixed_base": 31.0,
    "dynamic_price_entity": PRICE,
}
MARKET = "sensor.epex_spot_data_market_price"


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
    hass.states.async_set(MARKET, "0.10574", price_attributes())


async def start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def configure(hass: HomeAssistant, result: dict, user_input: dict) -> dict:
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def added_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = mock_entry()
    entry.add_to_hass(hass)
    return entry


async def start_tariff(hass: HomeAssistant, entry: MockConfigEntry, kind: str) -> dict:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "tariff"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": kind}
    )


async def configure_tariff(hass: HomeAssistant, result: dict, user_input: dict) -> dict:
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


# --- setup -------------------------------------------------------------------------


async def test_full_flow(hass: HomeAssistant) -> None:
    result = await start(hass)
    assert result["step_id"] == "user"
    result = await configure(hass, result, METER_STEP)
    assert result["step_id"] == "tariffs"
    result = await configure(hass, result, TARIFFS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Haus"
    assert result["data"] == entry_data()
    entry = result["result"]
    assert entry.unique_id == METER
    assert entry.version == 2
    tariffs = {s.title: dict(s.data) for s in entry.subentries.values()}
    # No dynamic base price entered: stored as 0.
    assert tariffs == {"Fixed price": fixed_tariff(), "Dynamic": dynamic_tariff()}


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
    added_entry(hass)
    result = await configure(hass, await start(hass), METER_STEP)
    assert result["errors"] == {"meter_entity": "meter_in_use"}


async def test_reconfigure_meter(hass: HomeAssistant) -> None:
    entry = added_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    # The own meter is not "in use"; tariffs are not asked again.
    result = await configure(hass, result, {**METER_STEP, "name": "Wohnung"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Wohnung"
    assert entry.data == entry_data(name="Wohnung")
    assert len(entry.subentries) == 2


# --- tariff subentries -----------------------------------------------------------


async def test_add_fixed_tariff_as_current(hass: HomeAssistant) -> None:
    entry = added_entry(hass)
    result = await start_tariff(hass, entry, "fixed")
    assert result["step_id"] == "fixed"
    result = await configure_tariff(
        hass,
        result,
        {
            "name": "Stadtwerke",
            "price": 28.5,
            "base_price": 150.0,
            "base_period": "year",
            "current": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    added = next(s for s in entry.subentries.values() if s.title == "Stadtwerke")
    assert dict(added.data) == {
        "kind": "fixed",
        "price": 28.5,
        "base_price": 150.0,
        "base_period": "year",
        "current": True,
    }
    # Only one current tariff.
    assert entry.subentries[FIXED_SUBENTRY].data[CONF_CURRENT] is False


async def test_add_exchange_price_tariff(hass: HomeAssistant) -> None:
    entry = added_entry(hass)
    result = await start_tariff(hass, entry, "dynamic_market")
    result = await configure_tariff(
        hass,
        result,
        {
            "name": "Börse",
            "price_entity": MARKET,
            "grid_fee": 8.0,
            "levies": 4.0,
            "margin": 2.0,
            "vat": 19.0,
            "base_period": "month",
            "current": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    added = next(s for s in entry.subentries.values() if s.title == "Börse")
    assert added.data["kind"] == "dynamic_market"
    assert added.data["grid_fee"] == 8.0
    assert added.data["base_price"] == 0
    assert entry.subentries[FIXED_SUBENTRY].data[CONF_CURRENT] is True


async def test_tariff_errors(hass: HomeAssistant) -> None:
    entry = added_entry(hass)
    hass.states.async_set("sensor.price_ct", "10.5", {"unit_of_measurement": "ct/kWh"})
    result = await start_tariff(hass, entry, "dynamic_total")
    base = {"base_period": "month", "current": False}
    result = await configure_tariff(
        hass, result, {"name": "fixed PRICE", "price_entity": PRICE, **base}
    )
    assert result["errors"] == {"name": "name_in_use"}
    result = await configure_tariff(
        hass, result, {"name": "Neu", "price_entity": "sensor.price_ct", **base}
    )
    assert result["errors"] == {"price_entity": "price_unit"}


async def test_reconfigure_tariff_keeps_key(hass: HomeAssistant) -> None:
    entry = added_entry(hass)
    result = await entry.start_subentry_reconfigure_flow(hass, DYNAMIC_SUBENTRY)
    assert result["step_id"] == "dynamic_total"
    result = await configure_tariff(
        hass,
        result,
        {
            "name": "Tibber",
            "price_entity": PRICE,
            "base_price": 5.99,
            "base_period": "month",
            "current": False,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = entry.subentries[DYNAMIC_SUBENTRY]
    assert subentry.title == "Tibber"
    assert dict(subentry.data) == dynamic_tariff(base_price=5.99)
