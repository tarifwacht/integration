"""The import_statistics action against a real (in-memory) recorder."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from homeassistant.components.recorder import Recorder, get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.models.statistics import StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.tarifwacht.const import DOMAIN
from custom_components.tarifwacht.smard import INDEX_URL, week_url
from tests.conftest import load_fixture

from .test_lookback import WEEK_MS, import_meter_statistics, setup_entry

# Set up at 25.10.2026 17:20:30 CET: the period starts at 16:15 UTC, Home
# Assistant's first statistics hour of the sensors is 16:00 UTC.
NOW = datetime(2026, 10, 25, 16, 20, 30, tzinfo=UTC)
LIVE_HOUR = datetime(2026, 10, 25, 16, tzinfo=UTC)
# Meter statistics begin at 24.10. 12:00 UTC (hours 13, 14, 15: 1, 1, 2 kWh).
FIRST_METER_HOUR = datetime(2026, 10, 24, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert found, key
    return found


async def live_statistics(hass: HomeAssistant, statistic_ids: dict[str, str]) -> None:
    """One compiled hour per sensor, as Home Assistant writes from the setup on."""
    for statistic_id, unit in statistic_ids.items():
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
            [{"start": LIVE_HOUR, "state": 0.5, "sum": 0.5}],
        )
    await async_wait_recording_done(hass)


async def import_statistics(
    hass: HomeAssistant, entry: MockConfigEntry, start: str
) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN,
        "import_statistics",
        {"config_entry": entry.entry_id, "start": start},
        blocking=True,
        return_response=True,
    )


async def sums(hass: HomeAssistant, statistic_id: str) -> list[tuple[datetime, float]]:
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 10, 20, tzinfo=UTC),
        None,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    return [
        (datetime.fromtimestamp(r["start"], UTC), r["sum"]) for r in rows[statistic_id]
    ]


@pytest.mark.freeze_time(NOW)
async def test_import_statistics(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(INDEX_URL, json=load_fixture("smard_index_quarterhour.json"))
    aioclient_mock.get(
        week_url(WEEK_MS), json=load_fixture("smard_week_2026-10-19.json")
    )
    entry = await setup_entry(hass)
    await import_meter_statistics(hass)
    ids = {
        key: entity_id(hass, entry, key)
        for key in (
            "energy",
            "fixed_consumption_cost",
            "fixed_cost",
            "dynamic_cost",
            "market_cost",
            "market_difference",
        )
    }
    await live_statistics(
        hass, {sid: "kWh" if key == "energy" else "EUR" for key, sid in ids.items()}
    )

    # No statistics before the setup yet: sensors exist since it.
    with pytest.raises(ServiceValidationError) as err:
        await import_statistics(hass, entry, "2026-10-26")
    assert err.value.translation_key == "import_start_after_setup"

    result = await import_statistics(hass, entry, "2026-10-24")
    await async_wait_recording_done(hass)
    # The meter's statistics begin later than the requested day.
    assert result["start"].startswith("2026-10-24T14:00:00+02:00")
    # From 24.10. 16:00 UTC up to the setup hour the meter has no statistics.
    assert result["hours_without_energy"] == 25
    # The total price sensor has no prices before the setup: left out entirely.
    assert result["skipped"] == ["Dynamic"]
    assert ids["dynamic_cost"] not in result["sensors"]
    assert "SMARD.de" in result["exchange_prices"]

    hours = 28  # 24.10. 12:00 UTC up to 25.10. 16:00 UTC
    energy = result["sensors"][ids["energy"]]
    assert energy["hours"] == hours
    assert energy["added"] == pytest.approx(4.0)
    fixed = result["sensors"][ids["fixed_consumption_cost"]]
    assert fixed["added"] == pytest.approx(4 * 0.30)
    # Base price 31 €/month: 24.10. from 14:00 CEST (40 of 96 quarter hours),
    # 25.10. up to the setup (73 of 100, the last one in the first live hour).
    base = 40 / 96 + 0.73
    assert result["sensors"][ids["fixed_cost"]]["added"] == pytest.approx(
        1.2 + base, abs=1e-4
    )
    market, difference = (
        result["sensors"][ids["market_cost"]]["added"],
        result["sensors"][ids["market_difference"]]["added"],
    )
    assert difference == pytest.approx(
        market - result["sensors"][ids["fixed_cost"]]["added"], abs=1e-3
    )

    # Continuous: the first compiled hour moved up by everything before it.
    rows = await sums(hass, ids["fixed_cost"])
    assert rows[0][0] == FIRST_METER_HOUR
    assert len(rows) == hours + 1
    assert rows[-1] == (LIVE_HOUR, pytest.approx(0.5 + 1.2 + base, abs=1e-4))
    # The quarter hour 16:00 before the setup belongs to the first live hour.
    assert rows[-1][1] - rows[-2][1] == pytest.approx(0.5 + 0.01, abs=1e-4)
    assert (await sums(hass, ids["dynamic_cost"])) == [(LIVE_HOUR, 0.5)]

    # Nothing left to fill in.
    with pytest.raises(ServiceValidationError) as err:
        await import_statistics(hass, entry, "2026-10-24")
    assert err.value.translation_key == "import_nothing_to_import"
