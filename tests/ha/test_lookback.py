"""Compare action before the setup: long-term statistics and SMARD.de."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.models.statistics import StatisticMetaData
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.tarifwacht.const import (
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_CURRENT,
    CONF_GRID_FEE,
    CONF_KEY,
    CONF_KIND,
    CONF_PRICE_ENTITY,
    CONF_VAT,
    DOMAIN,
    KIND_DYNAMIC_MARKET,
    SUBENTRY_TARIFF,
)
from custom_components.tarifwacht.smard import INDEX_URL, parse_week, week_url
from custom_components.tarifwacht.timeslots import QUARTER
from tests.conftest import load_fixture

from .conftest import (
    METER,
    METER_ATTRIBUTES,
    PRICE,
    entry_data,
    price_attributes,
    subentries_data,
)
from .test_init import START

# Week file with 25.10.2026 (Monday 19.10. 00:00 CEST).
WEEK_MS = 1792360800000


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def market_subentry() -> dict[str, Any]:
    """Exchange price + 10 ct grid fee, 19 % VAT, no base price."""
    return {
        "data": {
            CONF_KEY: "market",
            CONF_KIND: KIND_DYNAMIC_MARKET,
            CONF_PRICE_ENTITY: PRICE,
            CONF_GRID_FEE: 10.0,
            CONF_VAT: 19.0,
            CONF_BASE_PRICE: 0.0,
            CONF_BASE_PERIOD: "month",
            CONF_CURRENT: False,
        },
        "subentry_id": "01MARKETSUBENTRY00000000000",
        "subentry_type": SUBENTRY_TARIFF,
        "title": "Market",
        "unique_id": None,
    }


async def import_meter_statistics(hass: HomeAssistant) -> None:
    """Meter sums (Wh) on the day before the setup (25.10. 17:00 CET).

    24.10., hours 13, 14 and 15 UTC use 1, 1 and 2 kWh; the price sensor's
    forecast only goes back to 25.10. 00:00.
    """
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
    sums = [(utc(2026, 10, 24, 12), 0.0), (utc(2026, 10, 24, 13), 1000.0)]
    sums += [(utc(2026, 10, 24, 14), 2000.0), (utc(2026, 10, 24, 15), 4000.0)]
    async_import_statistics(
        hass,
        metadata,  # type: ignore[arg-type]
        [{"start": hour, "sum": total, "state": total} for hour, total in sums],
    )
    await async_wait_recording_done(hass)


async def setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=METER,
        title="Haus",
        data=entry_data(),
        version=2,
        subentries_data=[*subentries_data(), market_subentry()],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def compare(hass: HomeAssistant, entry: MockConfigEntry, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN,
        "compare",
        {"config_entry": entry.entry_id, **data},
        blocking=True,
        return_response=True,
    )


@pytest.mark.freeze_time(START)
async def test_compare_before_setup(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(INDEX_URL, json=load_fixture("smard_index_quarterhour.json"))
    aioclient_mock.get(
        week_url(WEEK_MS), json=load_fixture("smard_week_2026-10-19.json")
    )
    entry = await setup_entry(hass)
    await import_meter_statistics(hass)

    # 24.10. 15:00 CEST = 13:00 UTC.
    result = await compare(hass, entry, start="2026-10-24 15:00:00")
    assert result["start"].startswith("2026-10-24T15:00:00")
    assert result["energy_kwh"] == pytest.approx(4.0)
    estimate = result["estimate"]
    assert estimate["until"].startswith("2026-10-25T17:00:00")
    assert estimate["energy_kwh"] == pytest.approx(4.0)
    # 27 hours up to the setup, statistics for three of them.
    assert estimate["hours_without_energy"] == 24
    assert "SMARD.de" in estimate["exchange_prices"]

    tariffs = {t["tariff"]: t for t in result["tariffs"]}
    # 4 kWh at 30 ct. Base price 31 €/month, 1 €/day: 24.10. from 15:00
    # (36 of 96 quarter hours) and 25.10. up to 17:00 (72 of 100).
    assert tariffs["Fixed price"]["consumption_cost"] == pytest.approx(1.20)
    assert tariffs["Fixed price"]["base_cost"] == pytest.approx(0.375 + 0.72)
    smard = parse_week(load_fixture("smard_week_2026-10-19.json"))
    expected = 0.0
    slot = utc(2026, 10, 24, 13)
    while slot < utc(2026, 10, 24, 16):
        energy = 0.5 if slot.hour == 15 else 0.25
        expected += energy * (smard[slot] + 0.10) * 1.19
        slot += QUARTER
    assert tariffs["Market"]["cost"] == pytest.approx(expected, abs=1e-4)
    # The total price sensor has no prices from before the setup.
    assert tariffs["Dynamic"]["energy_without_price_kwh"] == pytest.approx(4.0)
    assert result["tariffs"][-1]["tariff"] == "Dynamic"
    assert result["cheapest"] in {"Fixed price", "Market"}
    assert [m["month"] for m in result["months"]] == ["2026-10"]

    # Prices are kept: a second comparison needs no download.
    assert "tarifwacht.smard.2026" in hass_storage
    calls = aioclient_mock.call_count
    await compare(hass, entry, start="2026-10-24 16:00:00")
    assert aioclient_mock.call_count == calls


@pytest.mark.freeze_time(START)
async def test_smard_failure_is_reported(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(INDEX_URL, exc=aiohttp.ClientError("unreachable"))
    entry = await setup_entry(hass)
    await import_meter_statistics(hass)
    with pytest.raises(HomeAssistantError):
        await compare(hass, entry, start="2026-10-24 15:00:00")
    # Without a start the period begins at the setup: nothing to download.
    result = await compare(hass, entry)
    assert "estimate" not in result
    assert START - timedelta(minutes=1) < datetime.fromisoformat(result["start"])
