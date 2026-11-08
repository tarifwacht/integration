"""PV and battery: subentry flow and the saving sensors (made-up values)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import patch

import voluptuous as vol
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
from custom_components.tarifwacht.lookback import Lookback
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


def add_einspeisewacht(hass: HomeAssistant, title: str = "Dach") -> None:
    MockConfigEntry(
        domain="einspeisewacht",
        title=title,
        data={
            "meter_entity": FEED_IN,
            "rates": [7.94],
            "price_entity": PRICE,
            "commissioned": "2025-07-31",
            "smart_meter": True,
        },
    ).add_to_hass(hass)


def add_speicherwacht(
    hass: HomeAssistant, title: str, charged: str, discharged: str
) -> None:
    MockConfigEntry(
        domain="speicherwacht",
        title=title,
        data={
            "name": title,
            "entities": {
                "charged": charged,
                "discharged": discharged,
                "soc": "sensor.battery_soc",
            },
            "capacity": 10.0,
        },
    ).add_to_hass(hass)


async def test_tip_without_sisters(hass: HomeAssistant) -> None:
    set_sources(hass)
    entry = mock_entry()
    entry.add_to_hass(hass)
    result = await start_solar(hass, entry)
    # "user" carries the tip with links to both sisters.
    assert result["step_id"] == "user"
    placeholders = result["description_placeholders"]
    assert placeholders["einspeisewacht_url"] == (
        "https://github.com/einspeisewacht/integration"
    )
    assert placeholders["speicherwacht_url"] == (
        "https://github.com/speicherwacht/integration"
    )
    assert suggested(result, CONF_FEED_IN_ENTITY) is None
    # An error shows the same step with its tip again.
    result = await configure(hass, result, solar_input(**{CONF_FEED_IN_ENTITY: METER}))
    assert result["step_id"] == "user"
    assert result["description_placeholders"]["speicherwacht_url"]


async def test_prefilled_from_einspeisewacht(hass: HomeAssistant) -> None:
    set_sources(hass)
    add_einspeisewacht(hass)
    entry = mock_entry()
    entry.add_to_hass(hass)
    result = await start_solar(hass, entry)
    assert result["step_id"] == "suggested_einspeisewacht"
    assert result["description_placeholders"]["einspeisewacht"] == "Dach"
    assert suggested(result, CONF_FEED_IN_ENTITY) == FEED_IN
    assert suggested(result, CONF_FEED_IN_RATE) == 7.94
    assert suggested(result, "market_entity") == PRICE
    assert suggested(result, CONF_CHARGED_ENTITY) is None
    with patch("custom_components.tarifwacht.async_setup_entry", return_value=True):
        result = await configure(
            hass, result, solar_input(**{CONF_FEED_IN_ENTITY: METER})
        )
        assert result["step_id"] == "suggested_einspeisewacht"
        assert result["errors"] == {CONF_FEED_IN_ENTITY: "same_as_purchase"}
        result = await configure(hass, result, solar_input())
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_prefilled_from_speicherwacht(hass: HomeAssistant) -> None:
    set_sources(hass)
    # An ignored Einspeisewacht entry has no data and is no source.
    MockConfigEntry(domain="einspeisewacht", source="ignore", data={}).add_to_hass(hass)
    # Two storages: the first one is used and named.
    add_speicherwacht(hass, "Speicher", CHARGED, DISCHARGED)
    add_speicherwacht(hass, "Balkon", "sensor.other_charged", "sensor.other_out")
    entry = mock_entry()
    entry.add_to_hass(hass)
    result = await start_solar(hass, entry)
    assert result["step_id"] == "suggested_speicherwacht"
    assert result["description_placeholders"]["speicherwacht"] == "Speicher"
    assert suggested(result, CONF_CHARGED_ENTITY) == CHARGED
    assert suggested(result, CONF_DISCHARGED_ENTITY) == DISCHARGED
    assert suggested(result, CONF_FEED_IN_ENTITY) is None
    result = await configure(
        hass,
        result,
        solar_input(
            **{CONF_CHARGED_ENTITY: CHARGED, CONF_DISCHARGED_ENTITY: DISCHARGED}
        ),
    )
    assert result["step_id"] == "battery_unknown"


async def test_prefilled_from_both(hass: HomeAssistant) -> None:
    set_sources(hass)
    add_einspeisewacht(hass)
    add_speicherwacht(hass, "Speicher", CHARGED, DISCHARGED)
    entry = mock_entry()
    entry.add_to_hass(hass)
    result = await start_solar(hass, entry)
    assert result["step_id"] == "suggested_both"
    assert result["description_placeholders"]["einspeisewacht"] == "Dach"
    assert result["description_placeholders"]["speicherwacht"] == "Speicher"
    assert suggested(result, CONF_FEED_IN_ENTITY) == FEED_IN
    assert suggested(result, CONF_CHARGED_ENTITY) == CHARGED


async def test_reconfigure_without_hint(hass: HomeAssistant) -> None:
    set_sources(hass)
    add_einspeisewacht(hass)
    entry = solar_entry()
    entry.add_to_hass(hass)
    solar = next(
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_SOLAR
    )
    result = await entry.start_subentry_reconfigure_flow(hass, solar.subentry_id)
    assert result["step_id"] == "reconfigure"
    assert not result["description_placeholders"]


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


async def test_compare_action_reports_the_saving(hass: HomeAssistant) -> None:
    """The compare action, here over a June day before the setup."""
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

    async def fake_lookback(self: MeterRuntime, start: datetime) -> Lookback:
        return Lookback(
            consumption={}, tariffs=self.engine.tariffs, until=self.engine.started
        )

    with (
        patch.object(MeterRuntime, "_async_hourly", fake_hourly),
        patch.object(MeterRuntime, "async_lookback", fake_lookback),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        response = await hass.services.async_call(
            DOMAIN,
            "compare",
            {
                "config_entry": entry.entry_id,
                "start": "2026-06-01 00:00:00",
                "end": "2026-06-02 00:00:00",
            },
            blocking=True,
            return_response=True,
        )
    rows = {row["tariff"]: row for row in response["pv_battery"]["tariffs"]}
    assert rows["Fixed price"]["saving_pv"] == 0.46
    assert rows["Fixed price"]["saving_battery"] == 0.38
    assert response["pv_battery"]["consumption_kwh"] == 3.0
    assert [m["month"] for m in response["pv_battery"]["months"]] == ["2026-06"]


async def test_purchase_in_a_collapsed_section(hass: HomeAssistant) -> None:
    """Purchase cost and commissioning in a collapsed section without a
    default; reconfigure shows the stored values in it, saving without the
    section keeps them, an emptied section removes them."""
    set_sources(hass)
    entry = solar_entry()
    entry.add_to_hass(hass)
    solar = next(
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_SOLAR
    )
    battery = {CONF_CHARGED_ENTITY: CHARGED, CONF_DISCHARGED_ENTITY: DISCHARGED}

    async def reconfigure(user_input: dict[str, Any]) -> dict:
        result = await entry.start_subentry_reconfigure_flow(hass, solar.subentry_id)
        result = await configure(hass, result, user_input)
        if result.get("step_id", "").startswith("battery_"):
            result = await configure(hass, result, {CONF_SAME_INVERTER: False})
        return result

    with patch("custom_components.tarifwacht.async_setup_entry", return_value=True):
        result = await entry.start_subentry_reconfigure_flow(hass, solar.subentry_id)
        schema = result["data_schema"].schema
        (key,) = [k for k in schema if str(k) == "purchase_section"]
        assert schema[key].options == {"collapsed": True}
        assert isinstance(key, vol.Optional) and key.default is vol.UNDEFINED
        # A cost without its day, a battery cost without battery meters.
        result = await configure(
            hass, result, solar_input(**battery, purchase_section={"pv_cost": 9000})
        )
        assert result["errors"] == {"base": "purchase_date_required"}
        result = await configure(
            hass,
            result,
            solar_input(
                purchase_section={"battery_cost": 4500, "pv_since": "2023-04-01"}
            ),
        )
        assert result["errors"] == {"base": "battery_cost_without_meters"}
        result = await reconfigure(
            solar_input(
                **battery,
                purchase_section={
                    "pv_cost": 9000,
                    "pv_since": "2023-04-01",
                    "battery_cost": 4500,
                    "battery_since": "2025-03-15",
                },
            )
        )
        assert result["type"] is FlowResultType.ABORT
        data = entry.subentries[solar.subentry_id].data
        assert data["pv_cost"] == 9000.0 and data["pv_since"] == "2023-04-01"
        assert data["battery_cost"] == 4500.0
        assert data["battery_since"] == "2025-03-15"
        assert "purchase_section" not in data

        # The stored values inside the section.
        result = await entry.start_subentry_reconfigure_flow(hass, solar.subentry_id)
        schema = result["data_schema"].schema
        (key,) = [k for k in schema if str(k) == "purchase_section"]
        shown = {
            str(k): (k.description or {}).get("suggested_value")
            for k in schema[key].schema.schema
        }
        assert shown == {
            "pv_cost": 9000.0,
            "pv_since": "2023-04-01",
            "battery_cost": 4500.0,
            "battery_since": "2025-03-15",
        }
        # Saved without the section: kept.
        await reconfigure(solar_input(**battery))
        assert entry.subentries[solar.subentry_id].data["pv_cost"] == 9000.0
        # The section emptied: gone.
        await reconfigure(solar_input(**battery, purchase_section={}))
        data = entry.subentries[solar.subentry_id].data
        assert not {"pv_cost", "pv_since", "battery_cost", "battery_since"} & set(data)


async def test_payback_attributes(hass: HomeAssistant) -> None:
    """The saving sensors show the payback: the days before the setup (from
    the statistics, faked here) and those of the hourly recomputation."""
    set_sources(hass)
    base = solar_entry()
    solar_id = "01SOLARSUBENTRY00000000000"
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=METER,
        title="Haus",
        data=dict(base.data),
        version=2,
        subentries_data=[
            {
                "data": dict(s.data)
                | (
                    {
                        "pv_cost": 1000.0,
                        "pv_since": "2026-05-01",
                        "battery_cost": 500.0,
                    }
                    if s.subentry_id == solar_id
                    else {}
                ),
                "subentry_id": s.subentry_id,
                "subentry_type": s.subentry_type,
                "title": s.title,
                "unique_id": None,
            }
            for s in base.subentries.values()
        ],
    )
    entry.add_to_hass(hass)
    noon = datetime(2026, 6, 1, 10, tzinfo=UTC)
    hourly = {
        METER: {noon: 0.0, noon + 8 * HOUR: 0.2},
        FEED_IN: {noon: 0.0, noon + 8 * HOUR: 0.0},
        PV: {noon: 3.0, noon + 8 * HOUR: 0.0},
        CHARGED: {noon: 2.0},
        DISCHARGED: {noon + 8 * HOUR: 1.8},
    }
    reads: list[datetime] = []

    async def fake_hourly(self: MeterRuntime, *_: Any) -> dict:
        return hourly

    async def fake_before(self: MeterRuntime, started: datetime) -> None:
        reads.append(started)
        self._payback_before = {"fixed": {"pv": {date(2026, 5, 1): 100.0}}}

    with (
        patch.object(MeterRuntime, "_async_hourly", fake_hourly),
        patch.object(MeterRuntime, "_async_payback_before", fake_before),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        runtime: MeterRuntime = entry.runtime_data
        await runtime.async_refresh_solar(datetime.now(UTC))
        await runtime.async_refresh_solar(datetime.now(UTC))
        await hass.async_block_till_done()
        response = await hass.services.async_call(
            DOMAIN,
            "compare",
            {"config_entry": entry.entry_id},
            blocking=True,
            return_response=True,
        )
    # Read once per start, not with every recomputation.
    assert len(reads) == 1
    registry = er.async_get(hass)
    pv = hass.states.get(
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_fixed_saving_pv"
        )
    )
    battery = hass.states.get(
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_fixed_saving_battery"
        )
    )
    assert pv.attributes["purchase_cost_eur"] == 1000.0
    assert pv.attributes["saved_since_commissioning_eur"] == 100.46
    assert pv.attributes["remaining_eur"] == 899.54
    assert pv.attributes["paid_back"] is False
    assert pv.attributes["counted_since"] == "2026-05-01"
    # The battery counts from the PV's day; 0.38 saved.
    assert battery.attributes["commissioned_on"] == "2026-05-01"
    assert battery.attributes["saved_since_commissioning_eur"] == 0.38
    rows = {row["tariff"]: row for row in response["pv_battery"]["payback"]}
    assert rows["Fixed price"]["pv"]["remaining_eur"] == 899.54
    assert rows["Fixed price"]["battery"]["purchase_cost_eur"] == 500.0
