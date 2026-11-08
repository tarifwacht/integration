"""The recalculation rewrites only what a change made stale, and only rows
whose values change (write load on small hardware), against a real
(in-memory) recorder with Home Assistant's own compiles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.tarifwacht.const import DOMAIN
from custom_components.tarifwacht.outdated import issue_id
from custom_components.tarifwacht.statistics_import import async_recalculate

from .conftest import (
    FIXED_SUBENTRY,
    METER,
    METER_ATTRIBUTES,
    PRICE,
    fixed_tariff,
    mock_entry,
    price_attributes,
)
from .test_statistics_recalculate import compile_period, entity_id, rows, tick

START = datetime(2026, 10, 25, 16, 0, 30, tzinfo=UTC)
# The price change from 26.10.: local midnight is 23:00 UTC.
CHANGE_AT = datetime(2026, 10, 25, 23, tzinfo=UTC)
SENSORS = (
    "energy",
    "fixed_cost",
    "fixed_consumption_cost",
    "dynamic_cost",
    "dynamic_consumption_cost",
    "dynamic_difference",
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


async def at(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, moment: datetime
) -> None:
    freezer.move_to(moment)
    await hass.async_block_till_done()


async def all_rows(hass: HomeAssistant, ids: dict[str, str]) -> dict[str, tuple]:
    return {
        key: (
            await rows(hass, statistic_id, "hour"),
            await rows(hass, statistic_id, "5minute"),
        )
        for key, statistic_id in ids.items()
    }


async def recalculate(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    result = await async_recalculate(hass, entry)
    await async_wait_recording_done(hass)
    return result


@pytest.mark.freeze_time(START)
async def test_only_stale_sensors_and_changed_rows(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ids = {key: entity_id(hass, entry, key) for key in SENSORS}

    # Eleven hours compiled (16:00 to 02:00 UTC), base price only.
    hour = datetime(2026, 10, 25, 16, tzinfo=UTC)
    while hour < datetime(2026, 10, 26, 3, tzinfo=UTC):
        await at(hass, freezer, hour + timedelta(hours=1, seconds=1))
        tick(hass, entry)
        await at(hass, freezer, hour + timedelta(hours=1, seconds=10))
        await compile_period(hass, hour + timedelta(minutes=55))
        hour += timedelta(hours=1)
    await at(hass, freezer, datetime(2026, 10, 26, 3, 15, 1, tzinfo=UTC))
    tick(hass, entry)
    await at(hass, freezer, datetime(2026, 10, 26, 3, 20, 10, tzinfo=UTC))
    await compile_period(hass, datetime(2026, 10, 26, 3, 15, tzinfo=UTC))

    # The current tariff gets a new base price from 26.10.
    change = {"from": "2026-10-26", "price": 30.0, "base_price": 62.0}
    hass.config_entries.async_update_subentry(
        entry,
        entry.subentries[FIXED_SUBENTRY],
        data=fixed_tariff(changes=[{**change, "base_period": "month"}]),
    )
    await hass.async_block_till_done()
    # Remembered across the reload: what from when.
    assert entry.runtime_data.engine.stale_statistics == {
        "fixed_consumption_cost": CHANGE_AT,
        "fixed_cost": CHANGE_AT,
        "fixed_difference": CHANGE_AT,
        "fixed_saving_pv": CHANGE_AT,
        "fixed_saving_battery": CHANGE_AT,
        "dynamic_difference": CHANGE_AT,
    }
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, issue_id(entry.entry_id)) is not None
    before = await all_rows(hass, ids)
    assert all(len(before[key][0]) == 11 for key in SENSORS)

    # The button: the stale sensors from 26.10. on, changed rows only.
    result = await recalculate(hass, entry)
    sensors = result["sensors"]
    assert set(sensors) == {
        ids["fixed_cost"],
        ids["fixed_consumption_cost"],
        ids["dynamic_difference"],
    }
    for key in ("fixed_cost", "dynamic_difference"):
        info = sensors[ids[key]]
        assert (info["hours"], info["hours_written"]) == (4, 4), key
        assert (info["short_term"], info["short_term_written"]) == (4, 4), key
    info = sensors[ids["fixed_consumption_cost"]]
    assert (info["hours_written"], info["short_term_written"]) == (0, 0)
    after = await all_rows(hass, ids)
    for key in SENSORS:
        old_hours, new_hours = before[key][0], after[key][0]
        assert [r for r in new_hours if r[0] < CHANGE_AT] == [
            r for r in old_hours if r[0] < CHANGE_AT
        ], key
        if key not in ("fixed_cost", "dynamic_difference"):
            assert after[key] == before[key], key
    old_rows, new_rows = before["fixed_cost"][0], after["fixed_cost"][0]
    changed = [new for old, new in zip(old_rows, new_rows, strict=True) if old != new]
    assert [r[0] for r in changed] == [r[0] for r in new_rows if r[0] >= CHANGE_AT]
    assert entry.runtime_data.engine.stale_statistics == {}
    assert issues.async_get_issue(DOMAIN, issue_id(entry.entry_id)) is None

    # Nothing known as stale: every sensor from its first row.
    result = await recalculate(hass, entry)
    assert set(result["sensors"]) == set(ids.values())
    assert sum(info["hours"] for info in result["sensors"].values()) == 66
    assert result["sensors"][ids["energy"]]["hours_written"] == 0
    # And again: not a single row written.
    result = await recalculate(hass, entry)
    written = [
        (info["hours_written"], info["short_term_written"])
        for info in result["sensors"].values()
    ]
    assert written == [(0, 0)] * len(SENSORS)
