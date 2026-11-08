"""Recalculating the statistics after a tariff change, against a real
(in-memory) recorder: Home Assistant's own 5-minute and hourly compiles
before and after it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder, get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.models.statistics import StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.components.recorder.tasks import StatisticsTask
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.tarifwacht.const import DOMAIN
from custom_components.tarifwacht.outdated import issue_id
from custom_components.tarifwacht.runtime import MeterRuntime

from .conftest import (
    FIXED_SUBENTRY,
    METER,
    METER_ATTRIBUTES,
    PRICE,
    fixed_tariff,
    mock_entry,
    price_attributes,
)

HOUR = timedelta(hours=1)
# 25.10.2026 17:00:30 CET: the period starts at 16:00 UTC.
START = datetime(2026, 10, 25, 16, 0, 30, tzinfo=UTC)
# Base price 31 EUR/month: 0.01 EUR per quarter hour on 25.10. (100).
BASE = 0.01


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert found, key
    return found


def value(hass: HomeAssistant, statistic_id: str) -> float:
    state = hass.states.get(statistic_id)
    assert state is not None
    return float(state.state)


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def at(hass: HomeAssistant, freezer: FrozenDateTimeFactory, *t: int) -> None:
    freezer.move_to(utc(2026, 10, 25, *t))
    await hass.async_block_till_done()


def tick(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The quarter-hour tick (books the base price of the ended quarter)."""
    runtime: MeterRuntime = entry.runtime_data
    runtime._on_tick(datetime.now(UTC))


async def compile_period(hass: HomeAssistant, start: datetime) -> None:
    """Home Assistant's 5-minute compile of [start, start + 5 min); at :55
    also the hour."""
    await async_wait_recording_done(hass)
    get_instance(hass).queue_task(StatisticsTask(start, False))
    await async_wait_recording_done(hass)


async def rows(
    hass: HomeAssistant, statistic_id: str, period: str
) -> list[tuple[datetime, float, float]]:
    found = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        utc(2026, 10, 25),
        None,
        {statistic_id},
        period,
        None,
        {"state", "sum"},
    )
    return [
        (datetime.fromtimestamp(r["start"], UTC), r["state"], r["sum"])
        for r in found.get(statistic_id, [])
    ]


async def press(hass: HomeAssistant, entry: MockConfigEntry) -> tuple[str, str]:
    """Press "Recalculate statistics": the notification's title and text."""
    button = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_recalculate_statistics"
    )
    assert button
    with patch(
        "custom_components.tarifwacht.button.persistent_notification.async_create"
    ) as create:
        await hass.services.async_call(
            "button", "press", {"entity_id": button}, blocking=True
        )
    create.assert_called_once()
    assert create.call_args.kwargs["notification_id"] == (
        f"tarifwacht_recalculate_{entry.entry_id}"
    )
    await async_wait_recording_done(hass)
    return create.call_args.kwargs["title"], create.call_args.args[1]


@pytest.mark.freeze_time(START)
async def test_recalculate_after_a_tariff_change(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Fixed price 30 ct, changed to 40 ct at 17:05: the past hours get the
    new price, the next compiles continue without a jump."""
    entry = await setup(hass)
    cost = entity_id(hass, entry, "fixed_cost")
    energy = entity_id(hass, entry, "energy")
    # 2 kWh in the quarter hours 16:00 and 16:15 UTC.
    await at(hass, freezer, 16, 14, 30)
    hass.states.async_set(METER, "1001000", METER_ATTRIBUTES)
    await at(hass, freezer, 16, 29, 30)
    hass.states.async_set(METER, "1002000", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    await at(hass, freezer, 16, 30, 1)
    tick(hass, entry)
    await at(hass, freezer, 16, 35, 10)
    await compile_period(hass, utc(2026, 10, 25, 16, 30))
    await at(hass, freezer, 16, 45, 1)
    tick(hass, entry)
    await at(hass, freezer, 17, 0, 1)
    tick(hass, entry)
    await at(hass, freezer, 17, 0, 10)
    await compile_period(hass, utc(2026, 10, 25, 16, 55))
    assert value(hass, cost) == pytest.approx(0.60 + 4 * BASE)

    # The tariff is corrected: the sensor shows the new total at once.
    await at(hass, freezer, 17, 5, 30)
    subentry = entry.subentries[FIXED_SUBENTRY]
    hass.config_entries.async_update_subentry(
        entry, subentry, data=fixed_tariff(price=40.0)
    )
    await hass.async_block_till_done()
    assert value(hass, cost) == pytest.approx(0.80 + 4 * BASE)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, issue_id(entry.entry_id)) is not None
    # Home Assistant books the jump into the next 5 minutes.
    await at(hass, freezer, 17, 10, 10)
    await compile_period(hass, utc(2026, 10, 25, 17, 5))
    old_hour = (await rows(hass, cost, "hour"))[-1]
    jump = (await rows(hass, cost, "5minute"))[-1][2] - old_hour[2]
    assert jump == pytest.approx(0.84 - old_hour[1])
    assert jump > 0.19

    title, message = await press(hass, entry)
    assert title == "Tarifwacht: statistics recalculated"
    assert "recalculated with the current tariffs" in message
    hours = await rows(hass, cost, "hour")
    assert hours[-1] == (
        utc(2026, 10, 25, 16),
        pytest.approx(0.84),
        pytest.approx(0.84),
    )
    short = await rows(hass, cost, "5minute")
    by_start = {start: (state, total) for start, state, total in short}
    # 16:30-16:35: 2 kWh x 0.40 + base of 2 1/3 quarter hours.
    assert by_start[utc(2026, 10, 25, 16, 30)][1] == pytest.approx(0.80 + BASE * 7 / 3)
    assert by_start[utc(2026, 10, 25, 16, 55)][1] == pytest.approx(0.84)
    # The row after the reload continues from the new rows: sum - state is
    # the same as in them (0: the sensor counts since the setup).
    latest = by_start[utc(2026, 10, 25, 17, 5)]
    assert latest == (pytest.approx(0.84), pytest.approx(0.84))
    energy_hours = await rows(hass, energy, "hour")
    assert energy_hours[-1][2] == pytest.approx(2.0)
    assert issues.async_get_issue(DOMAIN, issue_id(entry.entry_id)) is None

    # Idempotent: pressing again changes nothing.
    await press(hass, entry)
    assert await rows(hass, cost, "hour") == hours
    assert await rows(hass, cost, "5minute") == short

    # The next live compiles: only the base price of the quarter hour 17:00.
    await at(hass, freezer, 17, 15, 1)
    tick(hass, entry)
    await at(hass, freezer, 17, 20, 10)
    await compile_period(hass, utc(2026, 10, 25, 17, 15))
    assert (await rows(hass, cost, "5minute"))[-1][2] == pytest.approx(0.85)
    await at(hass, freezer, 18, 0, 10)
    await compile_period(hass, utc(2026, 10, 25, 17, 55))
    hours = await rows(hass, cost, "hour")
    assert hours[-1][0] == utc(2026, 10, 25, 17)
    assert hours[-1][2] - hours[-2][2] == pytest.approx(BASE)


async def live_row(
    hass: HomeAssistant, statistic_id: str, unit: str, hour: datetime
) -> None:
    metadata: dict[str, Any] = {
        "has_sum": True,
        "mean_type": StatisticMeanType.NONE,
        "name": None,
        "source": "recorder",
        "statistic_id": statistic_id,
        "unit_of_measurement": unit,
    }
    if "unit_class" in StatisticMetaData.__annotations__:
        metadata["unit_class"] = "energy" if unit == "kWh" else None
    async_import_statistics(
        hass,
        metadata,  # type: ignore[arg-type]
        [{"start": hour, "state": 0.5, "sum": 0.5}],
    )
    await async_wait_recording_done(hass)


@pytest.mark.freeze_time(datetime(2026, 10, 25, 17, 20, tzinfo=UTC))
async def test_replace_leaves_sensors_without_statistics_alone(
    hass: HomeAssistant,
) -> None:
    """The action with `replace`: only sensors with statistics; one hour
    compiled, no short-term rows (nothing to shift). Set up at 17:20 UTC:
    the period starts at 17:15."""
    entry = await setup(hass)
    energy = entity_id(hass, entry, "energy")
    cost = entity_id(hass, entry, "fixed_cost")
    await live_row(hass, energy, "kWh", utc(2026, 10, 25, 17))
    result = await hass.services.async_call(
        DOMAIN,
        "import_statistics",
        {"config_entry": entry.entry_id, "start": "2026-10-25", "replace": True},
        blocking=True,
        return_response=True,
    )
    await async_wait_recording_done(hass)
    assert list(result["sensors"]) == [energy]
    assert result["sensors"][energy]["hours"] == 1
    # Nothing booked since the setup: the row is recomputed to 0.
    assert (await rows(hass, energy, "hour")) == [
        (utc(2026, 10, 25, 17), pytest.approx(0.0), pytest.approx(0.0))
    ]
    assert await rows(hass, cost, "hour") == []


@pytest.mark.freeze_time(START)
async def test_nothing_to_recalculate_without_statistics(
    hass: HomeAssistant,
) -> None:
    entry = await setup(hass)
    title, message = await press(hass, entry)
    assert title == "Tarifwacht: statistics not recalculated"
    assert "no statistics yet" in message
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "import_statistics",
            {"config_entry": entry.entry_id, "start": "2026-10-25", "replace": True},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "import_no_statistics_yet"


async def meter_statistics(hass: HomeAssistant, rows: list[tuple[int, float]]) -> None:
    """Meter rows (Wh) on 24.10.: (hour UTC, state); the sum as Home
    Assistant compiles it, a fall of the state as a new cycle."""
    metadata: dict[str, Any] = {
        "has_sum": True,
        "mean_type": StatisticMeanType.NONE,
        "name": None,
        "source": "recorder",
        "statistic_id": METER,
        "unit_of_measurement": "Wh",
    }
    if "unit_class" in StatisticMetaData.__annotations__:
        metadata["unit_class"] = "energy"
    total, previous, data = 0.0, None, []
    for hour, state in rows:
        if previous is not None:
            total += state if state < 0.9 * previous else state - previous
        previous = state
        data.append({"start": utc(2026, 10, 24, hour), "state": state, "sum": total})
    async_import_statistics(hass, metadata, data)  # type: ignore[arg-type]
    await async_wait_recording_done(hass)


@pytest.mark.freeze_time(datetime(2026, 10, 25, 16, 20, 30, tzinfo=UTC))
async def test_compare_leaves_out_a_unit_glitch(hass: HomeAssistant) -> None:
    """The meter reported Wh as kWh for a moment: 107 -> 109851.5 -> 110.131
    kWh. Without the check the lookback would book about 110,000 kWh."""
    entry = await setup(hass)
    await meter_statistics(
        hass,
        [
            (10, 107_000.0),
            (11, 107_400.0),
            (12, 109_851_500.0),
            (13, 110_131.0),
            (14, 110_500.0),
            (15, 130_500.0),  # 20 kWh: a busy hour stays
        ],
    )
    response = await hass.services.async_call(
        DOMAIN,
        "compare",
        {"config_entry": entry.entry_id, "start": "2026-10-24 00:00:00"},
        blocking=True,
        return_response=True,
    )
    estimate = response["estimate"]
    assert estimate["hours_implausible"] == {
        "count": 2,
        "hours": ["2026-10-24T14:00:00+02:00", "2026-10-24T15:00:00+02:00"],
    }
    # 0.4 + 0.369 + 20 kWh before the setup.
    assert estimate["energy_kwh"] == pytest.approx(20.769)
