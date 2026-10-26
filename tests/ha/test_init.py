"""Setup, booking through real state changes, restart and removal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.tarifwacht.const import DOMAIN
from custom_components.tarifwacht.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import METER, METER_ATTRIBUTES, PRICE, entry_data, price_attributes

# 25.10.2026 17:00:30 CET. Fixture prices: 0.04577 €/kWh (17:00-17:15),
# 0.06856 €/kWh (17:15-17:30).
START = datetime(2026, 10, 25, 16, 0, 30, tzinfo=UTC)
P1, P2 = 0.04577, 0.06856


def value(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> float:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id, key
    state = hass.states.get(entity_id)
    assert state is not None, key
    return float(state.state)


async def setup(hass: HomeAssistant, **changes) -> MockConfigEntry:
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=METER, title="Haus", data=entry_data(**changes)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.freeze_time(START)
async def test_booking_and_restart(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert value(hass, entry, "energy") == 0

    # 17:00:30-17:14:30: 1 kWh, all in the first quarter hour.
    freezer.move_to(datetime(2026, 10, 25, 16, 14, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1001000", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    assert value(hass, entry, "energy") == pytest.approx(1.0)
    assert value(hass, entry, "fixed_consumption_cost") == pytest.approx(0.30)
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(P1)

    # 17:14:30-17:29:30: 1 kWh, 30 s of it in the first quarter hour.
    freezer.move_to(datetime(2026, 10, 25, 16, 29, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1002000", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    dynamic = P1 + P1 / 30 + P2 * 29 / 30
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(dynamic)
    assert value(hass, entry, "fixed_consumption_cost") == pytest.approx(0.60)

    # Restart: totals come back; the ended quarter hour 17:00 gets its base
    # price (31 €/month in October, 100 quarter hours on 25.10.: 0.01 €).
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(dynamic)
    assert value(hass, entry, "fixed_cost") == pytest.approx(0.61)
    assert value(hass, entry, "dynamic_cost") == pytest.approx(dynamic)
    assert value(hass, entry, "dynamic_extra_cost") == pytest.approx(dynamic - 0.61)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "name" not in diagnostics["config"]
    assert diagnostics["prices"][PRICE]["resolution_minutes"] == 15
    assert diagnostics["wrong_price_unit"] is None
    assert diagnostics["consumption"]["quarter_hours"] == 2


@pytest.mark.freeze_time(START)
async def test_meter_reset_is_not_booked(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    freezer.move_to(datetime(2026, 10, 25, 16, 5, tzinfo=UTC))
    hass.states.async_set(METER, "0", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    freezer.move_to(datetime(2026, 10, 25, 16, 6, tzinfo=UTC))
    hass.states.async_set(METER, "1000010", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    assert value(hass, entry, "energy") == 0


@pytest.mark.freeze_time(START)
async def test_unavailable_meter_gap_is_booked_later(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Unlike a template sensor, a gap is not lost but spread over its time."""
    entry = await setup(hass)
    freezer.move_to(datetime(2026, 10, 25, 16, 10, tzinfo=UTC))
    hass.states.async_set(METER, "unavailable", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    freezer.move_to(datetime(2026, 10, 25, 16, 29, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1001740", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    # 1.74 kWh over 29 minutes: 14.5 min in the first, 14.5 in the second.
    assert value(hass, entry, "energy") == pytest.approx(1.74)
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(
        0.87 * P1 + 0.87 * P2
    )


@pytest.mark.freeze_time(START)
async def test_wrong_price_unit_is_ignored(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    # The price sensor was switched to ct/kWh after setup.
    attributes = price_attributes()
    attributes["unit_of_measurement"] = "ct/kWh"
    attributes["data"] = [
        {**e, "price_per_kwh": e["price_per_kwh"] * 100} for e in attributes["data"]
    ]
    hass.states.async_set(PRICE, "4.577", attributes)
    await hass.async_block_till_done()
    freezer.move_to(datetime(2026, 10, 25, 16, 14, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1001000", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    # Booked with the prices known before, not with the ct values.
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(P1)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["wrong_price_unit"] == "ct/kWh"


@pytest.mark.freeze_time(START)
async def test_remove_entry(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.freeze_time(START)
async def test_update_from_0_1_0b1(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """0.1.0b1 kept totals only: the consumption is read back from the recorder."""
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=METER, title="Haus", data=entry_data()
    )
    # The meter as recorded while 0.1.0b1 was running.
    freezer.move_to(datetime(2026, 10, 25, 16, 14, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1001000", METER_ATTRIBUTES)
    freezer.move_to(datetime(2026, 10, 25, 16, 29, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1002000", METER_ATTRIBUTES)
    await async_wait_recording_done(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "meter": {"last_value": 1002.0, "last_time": "2026-10-25T16:29:30+00:00"},
            "prices": {
                e["start_time"]: e["price_per_kwh"] for e in price_attributes()["data"]
            },
            "energy": 2.0,
            "next_base_slot": "2026-10-25T16:15:00+00:00",
            "tariffs": {},
            "meter_events": {"first": 1},
        },
    }

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert value(hass, entry, "energy") == pytest.approx(2.0)
    assert value(hass, entry, "fixed_consumption_cost") == pytest.approx(0.60)
    dynamic = P1 + P1 / 30 + P2 * 29 / 30
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(dynamic)
    # Base price since setup (16:00 UTC): the quarter hour 16:00 has ended.
    assert value(hass, entry, "fixed_cost") == pytest.approx(0.61)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["backfill"] == {"pending_until": None, "error": None}
    assert diagnostics["consumption"]["quarter_hours"] == 2
