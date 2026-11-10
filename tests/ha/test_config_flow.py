"""Tests for the config flow, reconfiguration and tariff subentries."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifwacht.const import CONF_CURRENT, CONF_RENAMED, DOMAIN

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
    nest_sections,
    price_attributes,
    shown_values,
)

METER_STEP = {"name": "Haus", "meter_entity": METER}
FIXED_STEP = {"fixed_price": 30.0, "fixed_base": 31.0}
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
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], nest_sections(result, user_input)
    )


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
        result["flow_id"], nest_sections(result, user_input)
    )


# --- setup -------------------------------------------------------------------------


async def dynamic_step(hass: HomeAssistant, kind: str) -> dict:
    """Through meter and fixed price to the form of the dynamic tariff."""
    result = await configure(hass, await start(hass), METER_STEP)
    result = await configure(hass, result, FIXED_STEP)
    assert result["type"] is FlowResultType.MENU
    # The recommended kind comes first.
    assert result["menu_options"] == ["dynamic_market", "dynamic_total"]
    return await configure(hass, result, {"next_step_id": kind})


async def test_full_flow(hass: HomeAssistant) -> None:
    result = await start(hass)
    assert result["step_id"] == "user"
    result = await configure(hass, result, METER_STEP)
    assert result["step_id"] == "tariffs"
    result = await configure(hass, result, FIXED_STEP)
    assert result["step_id"] == "dynamic"
    result = await configure(hass, result, {"next_step_id": "dynamic_total"})
    assert result["step_id"] == "dynamic_total"
    result = await configure(hass, result, {"price_entity": PRICE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Haus"
    assert result["data"] == entry_data()
    entry = result["result"]
    assert entry.unique_id == METER
    assert entry.version == 2
    tariffs = {s.title: dict(s.data) for s in entry.subentries.values()}
    # No dynamic base price entered: stored as 0.
    assert tariffs == {"Fixed price": fixed_tariff(), "Dynamic": dynamic_tariff()}


async def test_setup_with_exchange_price(hass: HomeAssistant) -> None:
    """The recommended way: exchange price plus surcharges, VAT prefilled."""
    result = await dynamic_step(hass, "dynamic_market")
    assert result["step_id"] == "dynamic_market"
    fields = {str(key): key for key in result["data_schema"].schema}
    # VAT in the collapsed section "More".
    assert set(fields) == {
        "price_entity",
        "grid_fee",
        "levies",
        "margin",
        "base_price",
        "details_section",
    }
    assert shown_values(result)["vat"] == 19.0
    result = await configure(
        hass, result, {"price_entity": MARKET, "margin": 15.0, "vat": 19.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    tariffs = {s.title: dict(s.data) for s in result["result"].subentries.values()}
    assert tariffs["Fixed price"] == fixed_tariff()
    assert tariffs["Dynamic"] == {
        "key": "dynamic",
        "kind": "dynamic_market",
        "price_entity": MARKET,
        "grid_fee": 0.0,
        "levies": 0.0,
        "margin": 15.0,
        "vat": 19.0,
        "base_price": 0.0,
        "base_period": "month",
        "current": False,
    }


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
    result = await configure(hass, result, {**FIXED_STEP, "fixed_price": 0})
    assert result["errors"] == {"fixed_price": "price_required"}

    result = await dynamic_step(hass, "dynamic_total")
    for price, error in (
        ("sensor.missing", "entity_missing"),
        ("sensor.price_ct", "price_unit"),
        ("sensor.text", "price_invalid"),
    ):
        result = await configure(hass, result, {"price_entity": price})
        assert result["errors"] == {"price_entity": error}


async def test_state_only_price_sensor(hass: HomeAssistant) -> None:
    """Without a forecast attribute the current state is the price."""
    hass.states.async_set("sensor.price_now", "0.31", {"unit_of_measurement": "€/kWh"})
    result = await dynamic_step(hass, "dynamic_total")
    result = await configure(hass, result, {"price_entity": "sensor.price_now"})
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
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["edit", "add_change"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit"}
    )
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


async def test_price_changes(hass: HomeAssistant) -> None:
    entry = added_entry(hass)
    flows = hass.config_entries.subentries

    async def reconfigure(choice: str) -> dict:
        result = await entry.start_subentry_reconfigure_flow(hass, FIXED_SUBENTRY)
        assert result["type"] is FlowResultType.MENU
        return await flows.async_configure(result["flow_id"], {"next_step_id": choice})

    result = await reconfigure("add_change")
    assert result["step_id"] == "add_change"
    change = {
        "from": "2027-01-01",
        "price": 29.9,
        "base_price": 12.0,
        "base_period": "month",
    }
    result = await configure_tariff(hass, result, change)
    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[FIXED_SUBENTRY].data["changes"] == [change]

    # The same date again is refused.
    result = await reconfigure("add_change")
    result = await configure_tariff(hass, result, change)
    assert result["errors"] == {"from": "change_exists"}

    # Editing the tariff keeps its price changes and its key.
    result = await reconfigure("edit")
    assert result["step_id"] == "fixed"
    result = await configure_tariff(
        hass,
        result,
        {"name": "Fixed price", "price": 28.0, "base_period": "month", "current": True},
    )
    data = entry.subentries[FIXED_SUBENTRY].data
    assert data["price"] == 28.0
    assert data["key"] == "fixed"
    assert data["changes"] == [change]

    result = await reconfigure("remove_change")
    result = await configure_tariff(hass, result, {"from": "2027-01-01"})
    assert result["type"] is FlowResultType.ABORT
    assert "changes" not in entry.subentries[FIXED_SUBENTRY].data

    # A new contract with its own bonus: stored with the change, the date
    # is required.
    contract = {**change, "from": "2028-01-01", "bonus": 120.0}
    result = await reconfigure("add_change")
    result = await configure_tariff(hass, result, contract)
    assert result["errors"] == {"base": "bonus_date_required"}
    result = await configure_tariff(
        hass, result, {**contract, "bonus_date": "2028-12-31"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[FIXED_SUBENTRY].data["changes"] == [
        {**contract, "bonus_date": "2028-12-31"}
    ]


# 1 January 2027, 00:30 in Germany; still 31 December in the test time zone (US/Pacific).
@pytest.mark.freeze_time("2026-12-31 23:30:00+00:00")
async def test_price_change_prefill_uses_german_date(hass: HomeAssistant) -> None:
    entry = added_entry(hass)
    change = {"from": "2027-01-01", "price": 29.9, "base_period": "month"}
    result = await entry.start_subentry_reconfigure_flow(hass, FIXED_SUBENTRY)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "add_change"}
    )
    await configure_tariff(hass, result, change)

    result = await entry.start_subentry_reconfigure_flow(hass, FIXED_SUBENTRY)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "add_change"}
    )
    suggested = {
        str(key): (key.description or {}).get("suggested_value")
        for key in result["data_schema"].schema
    }
    assert suggested["price"] == 29.9


async def test_modul3(hass: HomeAssistant) -> None:
    entry = added_entry(hass)
    result = await start_tariff(hass, entry, "dynamic_market")
    await configure_tariff(
        hass,
        result,
        {
            "name": "Börse",
            "price_entity": MARKET,
            "grid_fee": 7.57,
            "levies": 4.0,
            "margin": 2.0,
            "vat": 19.0,
            "base_period": "month",
            "current": False,
        },
    )
    subentry = next(s for s in entry.subentries.values() if s.title == "Börse")
    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    assert result["menu_options"] == ["edit", "modul3", "add_change"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "modul3"}
    )
    assert result["step_id"] == "modul3"
    form = {
        "modul3_active": True,
        "nt": 3.03,
        "ht": 11.06,
        "quarters": ["1", "2", "3", "4"],
        "nt_windows": "10:00-14:00",
        "ht_windows": "13:00-22:00",
    }
    result = await configure_tariff(hass, result, form)
    assert result["errors"] == {"ht_windows": "window_overlap"}
    result = await configure_tariff(hass, result, {**form, "ht_windows": "17:10-22:00"})
    assert result["errors"] == {"ht_windows": "window_grid"}
    result = await configure_tariff(hass, result, {**form, "ht_windows": "17:00-22:00"})
    assert result["type"] is FlowResultType.ABORT
    modul3 = {
        "active": True,
        "nt": 3.03,
        "ht": 11.06,
        "quarters": [1, 2, 3, 4],
        "nt_windows": "10:00-14:00",
        "ht_windows": "17:00-22:00",
    }
    assert entry.subentries[subentry.subentry_id].data["modul3"] == modul3

    # Editing the tariff keeps Modul 3 (the edit form does not show it).
    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit"}
    )
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
    assert result["type"] is FlowResultType.ABORT
    data = entry.subentries[subentry.subentry_id].data
    assert data["grid_fee"] == 8.0
    assert data["modul3"] == modul3


async def test_modul3_of_a_fixed_price(hass: HomeAssistant) -> None:
    """A fixed-price supplier passing Modul 3 on: the form also asks for the
    standard grid fee contained in the price; a price change can bring a new
    price sheet (example values of Netzgesellschaft Düsseldorf 2026)."""
    entry = added_entry(hass)
    flows = hass.config_entries.subentries
    result = await entry.start_subentry_reconfigure_flow(hass, FIXED_SUBENTRY)
    assert result["menu_options"] == ["edit", "modul3", "add_change"]
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "modul3"})
    assert result["step_id"] == "modul3_fixed"
    form = {
        "modul3_active": True,
        "vat": 19.0,
        "nt": 3.16,
        "ht": 8.19,
        "quarters": ["1", "4"],
        "nt_windows": "04:30-05:00",
        "ht_windows": "18:00-20:00",
    }
    result = await configure_tariff(hass, result, form)
    assert result["errors"] == {"standard_fee": "price_required"}
    result = await configure_tariff(hass, result, {**form, "standard_fee": 7.91})
    assert result["type"] is FlowResultType.ABORT
    modul3 = {
        "active": True,
        "nt": 3.16,
        "ht": 8.19,
        "quarters": [1, 4],
        "nt_windows": "04:30-05:00",
        "ht_windows": "18:00-20:00",
        "standard": 7.91,
        "vat": 19.0,
    }
    assert entry.subentries[FIXED_SUBENTRY].data["modul3"] == modul3

    # A new price sheet from 1 January 2027 as a price change.
    result = await entry.start_subentry_reconfigure_flow(hass, FIXED_SUBENTRY)
    result = await flows.async_configure(
        result["flow_id"], {"next_step_id": "add_change"}
    )
    suggested = shown_values(result)
    assert suggested["standard_fee"] == 7.91
    assert suggested["modul3_active"] is True
    # Modul 3 in use: its section opens.
    schema = result["data_schema"].schema
    (key,) = [k for k in schema if str(k) == "modul3_section"]
    assert schema[key].options == {"collapsed": False}
    change = {
        "from": "2027-01-01",
        "price": 32.0,
        "base_period": "month",
        **form,
        "standard_fee": 8.0,
        "nt_windows": "02:00-05:00",
    }
    result = await configure_tariff(hass, result, change)
    assert result["type"] is FlowResultType.ABORT
    (stored,) = entry.subentries[FIXED_SUBENTRY].data["changes"]
    assert stored["price"] == 32.0
    assert stored["modul3"] == {
        **modul3,
        "standard": 8.0,
        "nt_windows": "02:00-05:00",
    }


async def test_reconfigure_meter_renamed_while_open(hass: HomeAssistant) -> None:
    """The meter is renamed while the form is open: submitting the shown (old)
    id keeps the new one and the pending rename note (review 0.1.2)."""
    entry = added_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    new = "sensor.smart_meter_import"
    hass.states.async_set(new, "1234567.0", METER_ATTRIBUTES)
    hass.states.async_remove(METER)
    # As the rename listener does it.
    hass.config_entries.async_update_entry(
        entry,
        unique_id=new,
        data={**entry.data, "meter_entity": new, CONF_RENAMED: {METER: new}},
    )
    result = await configure(hass, result, {**METER_STEP, "name": "Wohnung"})
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {
        **entry_data(name="Wohnung", meter_entity=new),
        CONF_RENAMED: {METER: new},
    }
    assert entry.unique_id == new


async def test_reconfigure_tariff_renamed_while_open(hass: HomeAssistant) -> None:
    """The price sensor is renamed while the edit form is open: submitting the
    shown (old) id keeps the new one."""
    entry = added_entry(hass)
    result = await entry.start_subentry_reconfigure_flow(hass, DYNAMIC_SUBENTRY)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit"}
    )
    new = "sensor.dynamic_price"
    hass.states.async_set(new, "0.10574", price_attributes())
    hass.states.async_remove(PRICE)
    hass.config_entries.async_update_subentry(
        entry,
        entry.subentries[DYNAMIC_SUBENTRY],
        data=dynamic_tariff(price_entity=new),
    )
    result = await configure_tariff(
        hass,
        result,
        {
            "name": "Dynamic",
            "price_entity": PRICE,
            "base_price": 0.0,
            "base_period": "month",
            "current": False,
        },
    )
    assert result["reason"] == "reconfigure_successful"
    assert dict(entry.subentries[DYNAMIC_SUBENTRY].data) == dynamic_tariff(
        price_entity=new
    )


async def test_price_field_starts_empty(hass: HomeAssistant) -> None:
    """A required number field would show 0; the price field is optional and
    the step asks for the price itself."""
    entry = added_entry(hass)
    result = await start_tariff(hass, entry, "fixed")
    key = next(k for k in result["data_schema"].schema if str(k) == "price")
    assert isinstance(key, vol.Optional)
    assert (key.description or {}).get("suggested_value") is None
    result = await configure_tariff(
        hass, result, {"name": "Neu", "base_period": "month", "current": False}
    )
    assert result["errors"] == {"price": "price_required"}


# --- own entities as sources -------------------------------------------------------


def own_sensor(
    hass: HomeAssistant, unique_id: str, state: str, attributes: dict
) -> str:
    """A sensor of Tarifwacht itself (another entry's result) with a state that
    passes every other check."""
    own = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, unique_id, suggested_object_id=unique_id
    )
    hass.states.async_set(own.entity_id, state, attributes)
    return own.entity_id


async def test_own_sensor_as_meter_is_refused(hass: HomeAssistant) -> None:
    """Its own "grid purchase" sensor as the meter (seen 2026-11 in the sister
    project Wärmewacht): the entry would read its own results."""
    own = own_sensor(
        hass,
        "wohnung_energy",
        "12.5",
        {
            "unit_of_measurement": "kWh",
            "state_class": "total_increasing",
            "device_class": "energy",
        },
    )
    result = await configure(
        hass, await start(hass), {**METER_STEP, "meter_entity": own}
    )
    assert result["errors"] == {"meter_entity": "own_entity"}
    result = await configure(hass, result, METER_STEP)
    assert result["step_id"] == "tariffs"

    entry = added_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await configure(hass, result, {**METER_STEP, "meter_entity": own})
    assert result["errors"] == {"meter_entity": "own_entity"}
    assert entry.data == entry_data()


def own_price(hass: HomeAssistant) -> str:
    """Its own average price, as if it reported €/kWh (it reports ct/kWh,
    which the unit check refuses as well)."""
    return own_sensor(
        hass, "haus_dynamic_average_price", "0.31", {"unit_of_measurement": "€/kWh"}
    )


async def test_own_sensor_as_price_is_refused_at_setup(hass: HomeAssistant) -> None:
    own = own_price(hass)
    result = await dynamic_step(hass, "dynamic_total")
    result = await configure(hass, result, {"price_entity": own})
    assert result["errors"] == {"price_entity": "own_entity"}
    result = await configure(hass, result, {"price_entity": PRICE})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_own_sensor_as_price_is_refused_in_tariff(hass: HomeAssistant) -> None:
    """When adding and when editing a tariff."""
    own = own_price(hass)
    entry = added_entry(hass)
    tariff = {"name": "Neu", "base_period": "month", "current": False}
    result = await start_tariff(hass, entry, "dynamic_total")
    result = await configure_tariff(hass, result, {**tariff, "price_entity": own})
    assert result["errors"] == {"price_entity": "own_entity"}
    result = await configure_tariff(hass, result, {**tariff, "price_entity": PRICE})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await entry.start_subentry_reconfigure_flow(hass, DYNAMIC_SUBENTRY)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit"}
    )
    result = await configure_tariff(
        hass, result, {**tariff, "name": "Dynamic", "price_entity": own}
    )
    assert result["errors"] == {"price_entity": "own_entity"}
    assert dict(entry.subentries[DYNAMIC_SUBENTRY].data) == dynamic_tariff()


async def test_bonus_in_a_collapsed_section(hass: HomeAssistant) -> None:
    """The bonus is entered in a collapsed section; reconfigure shows the
    stored values inside it, and saving without the section keeps them."""
    entry = added_entry(hass)
    flows = hass.config_entries.subentries

    async def edit() -> dict:
        result = await entry.start_subentry_reconfigure_flow(hass, FIXED_SUBENTRY)
        return await flows.async_configure(result["flow_id"], {"next_step_id": "edit"})

    fields = {"name": "Fixed price", "price": 30.0, "base_period": "month"}
    result = await edit()
    schema = result["data_schema"].schema
    (key,) = [k for k in schema if str(k) == "bonus_section"]
    assert schema[key].options == {"collapsed": True}
    # A bonus without its date is refused.
    result = await configure_tariff(
        hass, result, {**fields, "current": True, "bonus_section": {"bonus": 250}}
    )
    assert result["errors"] == {"base": "bonus_date_required"}
    result = await configure_tariff(
        hass,
        result,
        {
            **fields,
            "current": True,
            "bonus_section": {"bonus": 250, "bonus_date": "2027-02-01"},
        },
    )
    assert result["type"] is FlowResultType.ABORT
    data = entry.subentries[FIXED_SUBENTRY].data
    assert data["bonus"] == 250.0 and data["bonus_date"] == "2027-02-01"

    # Reconfigure: the stored values inside the section, no section default.
    result = await edit()
    schema = result["data_schema"].schema
    (key,) = [k for k in schema if str(k) == "bonus_section"]
    assert isinstance(key, vol.Optional) and key.default is vol.UNDEFINED
    suggested = {
        str(k): (k.description or {}).get("suggested_value")
        for k in schema[key].schema.schema
    }
    assert suggested == {"bonus": 250.0, "bonus_date": "2027-02-01"}
    # Saved without opening the section: the bonus stays.
    result = await configure_tariff(hass, result, {**fields, "current": True})
    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[FIXED_SUBENTRY].data["bonus"] == 250.0
    # The section emptied: the bonus is gone.
    result = await edit()
    result = await configure_tariff(
        hass, result, {**fields, "current": True, "bonus_section": {}}
    )
    data = entry.subentries[FIXED_SUBENTRY].data
    assert "bonus" not in data and "bonus_date" not in data


async def test_rare_fields_in_collapsed_sections(hass: HomeAssistant) -> None:
    """VAT and base price period sit in the collapsed section "More": no
    section default, the stored values inside it, kept when the section does
    not come back; adding without it takes the defaults."""
    entry = added_entry(hass)
    flows = hass.config_entries.subentries
    result = await start_tariff(hass, entry, "dynamic_market")
    schema = result["data_schema"].schema
    assert {str(k) for k in schema} == {
        "name",
        "price_entity",
        "grid_fee",
        "levies",
        "margin",
        "base_price",
        "current",
        "smard_fill",
        "details_section",
        "bonus_section",
    }
    (key,) = [k for k in schema if str(k) == "details_section"]
    assert schema[key].options == {"collapsed": True}
    assert isinstance(key, vol.Optional) and key.default is vol.UNDEFINED
    assert shown_values(result)["vat"] == 19.0
    assert shown_values(result)["base_period"] == "month"
    # Without the section: VAT 19 %, per month.
    result = await flows.async_configure(
        result["flow_id"],
        {"name": "Börse", "price_entity": MARKET, "margin": 2.0, "current": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    added = next(s for s in entry.subentries.values() if s.title == "Börse")
    assert added.data["vat"] == 19.0 and added.data["base_period"] == "month"

    async def edit() -> dict:
        result = await entry.start_subentry_reconfigure_flow(hass, added.subentry_id)
        return await flows.async_configure(result["flow_id"], {"next_step_id": "edit"})

    shown = {"name": "Börse", "price_entity": MARKET, "margin": 2.0, "current": False}
    result = await edit()
    await flows.async_configure(
        result["flow_id"],
        {**shown, "details_section": {"vat": 7.0, "base_period": "year"}},
    )
    data = entry.subentries[added.subentry_id].data
    assert data["vat"] == 7.0 and data["base_period"] == "year"
    # Reconfigure shows them in the section; saved without it, they stay.
    result = await edit()
    assert shown_values(result)["vat"] == 7.0
    assert shown_values(result)["base_period"] == "year"
    await flows.async_configure(result["flow_id"], shown)
    data = entry.subentries[added.subentry_id].data
    assert data["vat"] == 7.0 and data["base_period"] == "year"


async def test_price_change_without_modul3(hass: HomeAssistant) -> None:
    """A price change shows the prices; VAT, base price period and Modul 3
    in collapsed sections (Modul 3 closed while the tariff does not use it).
    Without the Modul 3 section the values before stay; its errors show on
    top."""
    entry = added_entry(hass)
    flows = hass.config_entries.subentries
    result = await start_tariff(hass, entry, "dynamic_market")
    await configure_tariff(
        hass,
        result,
        {
            "name": "Börse",
            "price_entity": MARKET,
            "grid_fee": 7.57,
            "vat": 19.0,
            "base_period": "month",
            "current": False,
        },
    )
    subentry = next(s for s in entry.subentries.values() if s.title == "Börse")

    async def add_change() -> dict:
        result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
        return await flows.async_configure(
            result["flow_id"], {"next_step_id": "add_change"}
        )

    result = await add_change()
    schema = result["data_schema"].schema
    assert {str(k) for k in schema} == {
        "from",
        "grid_fee",
        "levies",
        "margin",
        "base_price",
        "details_section",
        "modul3_section",
        "bonus_section",
    }
    (key,) = [k for k in schema if str(k) == "modul3_section"]
    assert schema[key].options == {"collapsed": True}
    assert shown_values(result)["vat"] == 19.0
    # Modul 3 switched on without windows: the error on top.
    result = await flows.async_configure(
        result["flow_id"],
        {
            "from": "2027-01-01",
            "grid_fee": 8.0,
            "modul3_section": {"modul3_active": True, "nt": 3.0, "ht": 11.0},
        },
    )
    assert result["errors"] == {"base": "window_required"}
    result = await flows.async_configure(
        result["flow_id"],
        {
            "from": "2027-01-01",
            "grid_fee": 8.0,
            "modul3_section": {"modul3_active": True, "ht": 11.0},
        },
    )
    assert result["errors"]["base"] in ("window_required", "modul3_price_required")
    # Without the sections: VAT and period as today, no Modul 3 key.
    result = await add_change()
    result = await flows.async_configure(
        result["flow_id"], {"from": "2027-01-01", "grid_fee": 8.0}
    )
    assert result["type"] is FlowResultType.ABORT
    (change,) = entry.subentries[subentry.subentry_id].data["changes"]
    assert change["grid_fee"] == 8.0
    assert change["vat"] == 19.0 and change["base_period"] == "month"
    assert "modul3" not in change
