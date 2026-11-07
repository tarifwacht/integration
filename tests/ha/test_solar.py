"""PV and battery: subentry flow and the saving sensors (made-up values)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifwacht.const import (
    CONF_CHARGED_ENTITY,
    CONF_DISCHARGED_ENTITY,
    CONF_FEED_IN_ENTITY,
    CONF_FEED_IN_RATE,
    CONF_NEGATIVE_UNPAID,
    CONF_PV_ENTITY,
    CONF_SAME_INVERTER,
    DOMAIN,
    SUBENTRY_SOLAR,
)
from custom_components.tarifwacht.runtime import MeterRuntime

from .conftest import METER, METER_ATTRIBUTES, PRICE, mock_entry, price_attributes

FEED_IN = "sensor.grid_export"
PV = "sensor.inverter_energy"
CHARGED = "sensor.battery_charged"
DISCHARGED = "sensor.battery_discharged"
HOUR = timedelta(hours=1)


def set_sources(hass: HomeAssistant) -> None:
    hass.states.async_set(METER, "1234567.0", METER_ATTRIBUTES)
    hass.states.async_set(PRICE, "0.10574", price_attributes())
    for entity in (FEED_IN, PV, CHARGED, DISCHARGED):
        hass.states.async_set(entity, "100.0", METER_ATTRIBUTES)


async def start_solar(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SOLAR), context={"source": SOURCE_USER}
    )


async def configure(hass: HomeAssistant, result: dict, user_input: dict) -> dict:
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


def solar_input(**changes: Any) -> dict[str, Any]:
    return {
        CONF_FEED_IN_ENTITY: FEED_IN,
        CONF_PV_ENTITY: PV,
        CONF_FEED_IN_RATE: 8.0,
        CONF_NEGATIVE_UNPAID: False,
        **changes,
    }


def suggested(result: dict, key: str) -> Any:
    for marker in result["data_schema"].schema:
        if str(marker) == key:
            return (marker.description or {}).get("suggested_value")
    raise KeyError(key)


async def test_add_pv_without_battery(hass: HomeAssistant) -> None:
    set_sources(hass)
    entry = mock_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.tarifwacht.async_setup_entry", return_value=True):
        result = await start_solar(hass, entry)
        assert result["step_id"] == "user"
        result = await configure(hass, result, solar_input())
    assert result["type"] is FlowResultType.CREATE_ENTRY
    added = next(
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_SOLAR
    )
    assert added.data[CONF_SAME_INVERTER] is False
    assert added.data[CONF_FEED_IN_RATE] == 8.0
    # At most one.
    result = await start_solar(hass, entry)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_solar"


async def test_battery_step_and_errors(hass: HomeAssistant) -> None:
    set_sources(hass)
    entry = mock_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.tarifwacht.async_setup_entry", return_value=True):
        result = await start_solar(hass, entry)
        result = await configure(
            hass, result, solar_input(**{CONF_CHARGED_ENTITY: CHARGED})
        )
        assert result["errors"] == {"base": "battery_both"}
        result = await configure(
            hass, result, solar_input(**{CONF_FEED_IN_ENTITY: METER})
        )
        assert result["errors"] == {CONF_FEED_IN_ENTITY: "same_as_purchase"}
        # The entry has no exchange price tariff and no sensor is chosen.
        result = await configure(
            hass, result, solar_input(**{CONF_NEGATIVE_UNPAID: True})
        )
        assert result["errors"] == {"market_entity": "market_required"}
        result = await configure(
            hass,
            result,
            solar_input(
                **{CONF_CHARGED_ENTITY: CHARGED, CONF_DISCHARGED_ENTITY: DISCHARGED}
            ),
        )
        # No statistics (no recorder): the data cannot tell the coupling.
        assert result["step_id"] == "battery_unknown"
        result = await configure(hass, result, {CONF_SAME_INVERTER: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    added = next(
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_SOLAR
    )
    assert added.data[CONF_SAME_INVERTER] is True
    assert added.data[CONF_DISCHARGED_ENTITY] == DISCHARGED


async def test_prefilled_from_einspeisewacht(hass: HomeAssistant) -> None:
    set_sources(hass)
    MockConfigEntry(
        domain="einspeisewacht",
        data={
            "meter_entity": FEED_IN,
            "rates": [7.94],
            "price_entity": PRICE,
            "commissioned": "2025-07-31",
            "smart_meter": True,
        },
    ).add_to_hass(hass)
    entry = mock_entry()
    entry.add_to_hass(hass)
    result = await start_solar(hass, entry)
    assert suggested(result, CONF_FEED_IN_ENTITY) == FEED_IN
    assert suggested(result, CONF_FEED_IN_RATE) == 7.94
    assert suggested(result, "market_entity") == PRICE


def solar_entry() -> MockConfigEntry:
    entry = mock_entry()
    entry.subentries_data = None
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=METER,
        title="Haus",
        data=dict(entry.data),
        version=2,
        subentries_data=[
            *[
                {
                    "data": dict(s.data),
                    "subentry_id": s.subentry_id,
                    "subentry_type": s.subentry_type,
                    "title": s.title,
                    "unique_id": None,
                }
                for s in entry.subentries.values()
            ],
            {
                "data": {
                    CONF_FEED_IN_ENTITY: FEED_IN,
                    CONF_PV_ENTITY: PV,
                    CONF_CHARGED_ENTITY: CHARGED,
                    CONF_DISCHARGED_ENTITY: DISCHARGED,
                    CONF_FEED_IN_RATE: 8.0,
                    CONF_NEGATIVE_UNPAID: False,
                    CONF_SAME_INVERTER: False,
                },
                "subentry_id": "01SOLARSUBENTRY00000000000",
                "subentry_type": SUBENTRY_SOLAR,
                "title": "PV",
                "unique_id": None,
            },
        ],
    )


async def test_saving_sensors(hass: HomeAssistant) -> None:
    """Noon: 3 kWh PV, 1 kWh used, 2 into the battery; evening: 1.8 kWh out,
    2 kWh used, 0.2 bought. Fixed tariff 30 ct, feed-in 8 ct."""
    set_sources(hass)
    entry = solar_entry()
    entry.add_to_hass(hass)
    noon = datetime(2026, 6, 1, 10, tzinfo=UTC)
    hourly = {
        METER: {noon: 0.0, noon + 8 * HOUR: 0.2},
        FEED_IN: {noon: 0.0, noon + 8 * HOUR: 0.0},
        PV: {noon: 3.0, noon + 8 * HOUR: 0.0},
        CHARGED: {noon: 2.0},
        DISCHARGED: {noon + 8 * HOUR: 1.8},
    }

    async def fake_hourly(self: MeterRuntime, *_: Any) -> dict:
        return hourly

    with patch.object(MeterRuntime, "_async_hourly", fake_hourly):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        runtime: MeterRuntime = entry.runtime_data
        await runtime.async_refresh_solar(datetime.now(UTC))
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    pv_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_fixed_saving_pv"
    )
    battery_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_fixed_saving_battery"
    )
    assert pv_id is not None and battery_id is not None
    pv = hass.states.get(pv_id)
    battery = hass.states.get(battery_id)
    # Without: 3 kWh x 0.30 = 0.90; PV only: 0.60 - 2 x 0.08 = 0.44;
    # actual: 0.2 x 0.30 = 0.06.
    assert float(pv.state) == 0.46
    assert float(battery.state) == 0.38
    assert pv.attributes["consumption_kwh"] == 3.0
    assert battery.attributes["discharged_kwh"] == 1.8
