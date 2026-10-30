"""Renamed source entities: the entries follow without reconfiguring, and the
stored prices and meter reading move to the new ids."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.tarifwacht.const import (
    CONF_METER,
    CONF_PRICE_ENTITY,
    CONF_RENAMED,
    DOMAIN,
)

from .conftest import (
    DYNAMIC_SUBENTRY,
    METER,
    METER_ATTRIBUTES,
    PRICE,
    mock_entry,
    price_attributes,
)

# 25.10.2026 17:00:30 CET; prices as in test_init.py.
START = datetime(2026, 10, 25, 16, 0, 30, tzinfo=UTC)
P1, P2 = 0.04577, 0.06856
DYNAMIC = P1 + P1 / 30 + P2 * 29 / 30
NEW_PRICE = "sensor.dynamic_price"
NEW_METER = "sensor.smart_meter_import"
# A price sensor without forecast: only the running quarter hour.
PLAIN_PRICE = ("0.31", {"unit_of_measurement": "€/kWh"})


def value(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> float:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id, key
    current = hass.states.get(entity_id)
    assert current is not None, key
    return float(current.state)


async def wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    registry = er.async_get(hass)
    for entity_id in (METER, PRICE):
        _, object_id = entity_id.split(".")
        registry.async_get_or_create(
            "sensor", "test", object_id, suggested_object_id=object_id
        )
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def two_kwh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """17:00:30-17:14:30 1 kWh; 17:14:30-17:29:30 1 kWh (30 s in 17:00)."""
    freezer.move_to(datetime(2026, 10, 25, 16, 14, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1001000", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    freezer.move_to(datetime(2026, 10, 25, 16, 29, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1002000", METER_ATTRIBUTES)
    await hass.async_block_till_done()


def rename(hass: HomeAssistant, old: str, new: str) -> None:
    """As Home Assistant does it: the entity comes back under the new id."""
    state = hass.states.get(old)
    er.async_get(hass).async_update_entity(old, new_entity_id=new)
    hass.states.async_remove(old)
    if state is not None:
        hass.states.async_set(new, state.state, state.attributes)


@pytest.mark.freeze_time(START)
async def test_price_sensor_renamed(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Renamed twice before the reload: the tariff reads the new sensor and
    keeps the prices it saw under the old id."""
    entry = await setup(hass)
    await two_kwh(hass, freezer)
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(DYNAMIC)
    before = entry.runtime_data

    freezer.move_to(datetime(2026, 10, 25, 16, 31, tzinfo=UTC))
    rename(hass, PRICE, "sensor.price_b")
    await wait(hass, freezer, 1)
    rename(hass, "sensor.price_b", NEW_PRICE)
    # The new sensor knows only the running quarter hour (16:30, no energy):
    # the earlier prices can only come from the stored table.
    hass.states.async_set(NEW_PRICE, *PLAIN_PRICE)
    await hass.async_block_till_done()
    # The data follows at once, the reload waits for the end of the burst.
    assert entry.subentries[DYNAMIC_SUBENTRY].data[CONF_PRICE_ENTITY] == NEW_PRICE
    assert entry.data[CONF_RENAMED] == {PRICE: NEW_PRICE, "sensor.price_b": NEW_PRICE}
    assert entry.runtime_data is before

    await wait(hass, freezer, 5)
    assert entry.state is ConfigEntryState.LOADED
    runtime = entry.runtime_data
    assert runtime is not before
    assert runtime.price_entities == {NEW_PRICE}
    assert CONF_RENAMED not in entry.data
    assert PRICE not in runtime.engine.prices
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(DYNAMIC)
    live = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert NEW_PRICE in live["prices"]
    assert PRICE not in live["prices"]

    # No repair issue after the grace time.
    await wait(hass, freezer, 15 * 60)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"{entry.entry_id}_missing_entity") is None


@pytest.mark.freeze_time(START)
async def test_renamed_while_not_loaded_moves_archives(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Renamed while the entry is unloaded: the next setup moves the yearly
    archive as well."""
    entry = await setup(hass)
    await two_kwh(hass, freezer)
    assert await hass.config_entries.async_unload(entry.entry_id)
    # Two days later: 25.10. (UTC) goes to the 2026 archive.
    freezer.move_to(datetime(2026, 10, 27, 16, 30, tzinfo=UTC))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    archive_key = f"{DOMAIN}.{entry.entry_id}.2026"
    assert PRICE in hass_storage[archive_key]["data"]["prices"]

    rename(hass, PRICE, NEW_PRICE)
    hass.states.async_set(NEW_PRICE, *PLAIN_PRICE)
    await wait(hass, freezer, 5)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.data[CONF_RENAMED] == {PRICE: NEW_PRICE}

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert CONF_RENAMED not in entry.data
    archive = hass_storage[archive_key]["data"]
    assert "2026-10-25" in archive["prices"][NEW_PRICE]
    assert PRICE not in archive["prices"]
    assert value(hass, entry, "energy") == pytest.approx(2.0)
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(DYNAMIC)


@pytest.mark.freeze_time(START)
async def test_meter_renamed_keeps_its_reading(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The renamed meter is no new meter: its last reading stays the baseline."""
    entry = await setup(hass)
    await two_kwh(hass, freezer)

    rename(hass, METER, NEW_METER)
    await hass.async_block_till_done()
    assert entry.data[CONF_METER] == NEW_METER
    assert entry.unique_id == NEW_METER
    # 100 Wh more before the reload: booked against the stored reading.
    freezer.move_to(datetime(2026, 10, 25, 16, 29, 31, tzinfo=UTC))
    hass.states.async_set(NEW_METER, "1002100", METER_ATTRIBUTES)
    await wait(hass, freezer, 5)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.meter_entity == NEW_METER
    assert value(hass, entry, "energy") == pytest.approx(2.1)


@pytest.mark.freeze_time(START)
async def test_rename_onto_another_source(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The new id is already a source of the entry: nothing changes."""
    entry = await setup(hass)
    er.async_get(hass).async_remove(PRICE)
    hass.states.async_remove(PRICE)

    rename(hass, METER, PRICE)
    await wait(hass, freezer, 5)
    assert entry.data[CONF_METER] == METER
    assert CONF_RENAMED not in entry.data
    assert entry.unique_id == METER
    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.freeze_time(START)
async def test_repair_issue_for_missing_entity(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A deleted meter is reported after the grace time, not silently ignored."""
    entry = await setup(hass)
    hass.states.async_remove(METER)
    await hass.async_block_till_done()
    issues = ir.async_get(hass)
    issue_id = f"{entry.entry_id}_missing_entity"
    # Within the grace time (other integrations may still be starting).
    freezer.move_to(datetime(2026, 10, 25, 16, 5, tzinfo=UTC))
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    freezer.move_to(datetime(2026, 10, 25, 16, 15, 1, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["entities"] == METER

    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None
