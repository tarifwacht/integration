"""Compare action before the setup: long-term statistics and SMARD.de."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.models.statistics import StatisticMetaData
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.config_entries import SOURCE_USER
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
from custom_components.tarifwacht.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.tarifwacht.runtime import MeterRuntime
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
from .test_init import START, two_kwh, value

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


async def setup_entry(hass: HomeAssistant, *, market: bool = True) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=METER,
        title="Haus",
        data=entry_data(),
        version=2,
        subentries_data=[*subentries_data(), *([market_subentry()] if market else [])],
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
    assert tariffs["Market"]["difference_to_current"] == pytest.approx(
        tariffs["Market"]["cost"] - tariffs["Fixed price"]["cost"], abs=1e-4
    )
    # The total price sensor has no prices from before the setup: no
    # difference, it would look cheaper than the current tariff.
    assert tariffs["Dynamic"]["energy_without_price_kwh"] == pytest.approx(4.0)
    assert tariffs["Dynamic"]["difference_to_current"] is None
    assert result["tariffs"][-1]["tariff"] == "Dynamic"
    assert result["cheapest"] in {"Fixed price", "Market"}
    assert [m["month"] for m in result["months"]] == ["2026-10"]
    month = {t["tariff"]: t for t in result["months"][0]["tariffs"]}
    assert month["Dynamic"]["difference_to_current"] is None
    assert month["Market"]["difference_to_current"] is not None

    # Prices are kept: a second comparison needs no download.
    assert "tarifwacht.smard.2026" in hass_storage
    calls = aioclient_mock.call_count
    await compare(hass, entry, start="2026-10-24 16:00:00")
    assert aioclient_mock.call_count == calls


@pytest.mark.freeze_time(START)
async def test_compare_before_setup_without_market_tariff(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """No exchange price tariff: no download, no SMARD.de attribution."""
    entry = await setup_entry(hass, market=False)
    await import_meter_statistics(hass)

    result = await compare(hass, entry, start="2026-10-24 15:00:00")
    assert aioclient_mock.call_count == 0
    assert result["estimate"]["energy_kwh"] == pytest.approx(4.0)
    assert "exchange_prices" not in result["estimate"]
    tariffs = {t["tariff"]: t for t in result["tariffs"]}
    assert tariffs["Fixed price"]["difference_to_current"] == 0
    assert tariffs["Dynamic"]["difference_to_current"] is None
    assert result["cheapest"] == "Fixed price"


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


# --- tariff added later ----------------------------------------------------------

NEW_MARKET = "sensor.new_market_price"
NEW_TOTAL = "sensor.new_total_price"
PRICE_UNIT = {"unit_of_measurement": "€/kWh"}
# The new exchange price tariff (+10 ct, 19 %) over the two quarter hours of
# `two_kwh`: 16:00 UTC from SMARD.de, 16:15 from the sensor (0.05 €/kWh).
SMARD_FILLED = (1 + 1 / 30) * (
    parse_week(load_fixture("smard_week_2026-10-19.json"))[
        datetime(2026, 10, 25, 16, tzinfo=UTC)
    ]
    + 0.10
) * 1.19 + 29 / 30 * (0.05 + 0.10) * 1.19


async def add_tariff(
    hass: HomeAssistant, entry: MockConfigEntry, kind: str, user_input: dict[str, Any]
) -> str:
    """Add a tariff through its subentry flow (reloads the entry)."""
    flows = hass.config_entries.subentries
    result = await flows.async_init(
        (entry.entry_id, "tariff"), context={"source": SOURCE_USER}
    )
    result = await flows.async_configure(result["flow_id"], {"next_step_id": kind})
    base = {"base_period": "month", "current": False}
    await flows.async_configure(result["flow_id"], {**user_input, **base})
    await hass.async_block_till_done(wait_background_tasks=True)
    added = next(s for s in entry.subentries.values() if s.title == user_input["name"])
    return added.subentry_id


@pytest.mark.freeze_time(START)
async def test_added_exchange_price_tariff_gets_smard_prices(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A tariff added later with a new sensor: the time since the setup before
    the sensor's first price is completed from SMARD.de."""
    aioclient_mock.get(INDEX_URL, json=load_fixture("smard_index_quarterhour.json"))
    aioclient_mock.get(
        week_url(WEEK_MS), json=load_fixture("smard_week_2026-10-19.json")
    )
    entry = await setup_entry(hass, market=False)
    await two_kwh(hass, freezer)
    # A new exchange price sensor without forecast: Tarifwacht reads it from
    # the quarter hour 16:15 UTC on.
    hass.states.async_set(NEW_MARKET, "0.05", PRICE_UNIT)
    fees = {"grid_fee": 6.0, "levies": 3.0, "margin": 1.0, "vat": 19.0}
    key = await add_tariff(
        hass,
        entry,
        "dynamic_market",
        {"name": "Börse", "price_entity": NEW_MARKET, "smard_fill": True, **fees},
    )
    assert entry.subentries[key].data["smard_fill"] is True

    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(SMARD_FILLED)
    assert "tarifwacht.smard.2026" in hass_storage
    # Restart: the stored SMARD.de prices are used, no download.
    calls = aioclient_mock.call_count
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert aioclient_mock.call_count == calls
    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(SMARD_FILLED)

    # The stored prices count from the start, not only once the background
    # work is done (review 0.1.2: "cheapest tariff" jumped after each start).
    with patch.object(MeterRuntime, "_async_fill_past_prices", AsyncMock()):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(SMARD_FILLED)

    # Background work still running when the runtime stops is cancelled
    # first, so it cannot write over the files of the next runtime.
    cancelled: list[bool] = []

    async def hang(self: MeterRuntime) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    with patch.object(MeterRuntime, "_async_fill_past_prices", hang):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    await entry.runtime_data.async_stop()
    assert cancelled == [True]


def suggested(result: dict[str, Any], field: str) -> Any:
    key = next(k for k in result["data_schema"].schema if str(k) == field)
    return (key.description or {}).get("suggested_value")


@pytest.mark.freeze_time(START)
async def test_added_exchange_price_tariff_without_consent(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """SMARD.de only when ticked: otherwise the time stays without a price;
    ticking it later in the tariff's form fills it."""
    aioclient_mock.get(INDEX_URL, json=load_fixture("smard_index_quarterhour.json"))
    aioclient_mock.get(
        week_url(WEEK_MS), json=load_fixture("smard_week_2026-10-19.json")
    )
    entry = await setup_entry(hass, market=False)
    await two_kwh(hass, freezer)
    hass.states.async_set(NEW_MARKET, "0.05", PRICE_UNIT)
    flows = hass.config_entries.subentries
    result = await flows.async_init(
        (entry.entry_id, "tariff"), context={"source": SOURCE_USER}
    )
    result = await flows.async_configure(
        result["flow_id"], {"next_step_id": "dynamic_market"}
    )
    # Offered ticked when adding.
    assert suggested(result, "smard_fill") is True
    form = {
        "name": "Börse",
        "price_entity": NEW_MARKET,
        "grid_fee": 6.0,
        "levies": 3.0,
        "margin": 1.0,
        "vat": 19.0,
        "base_period": "month",
        "current": False,
    }
    await flows.async_configure(result["flow_id"], {**form, "smard_fill": False})
    await hass.async_block_till_done(wait_background_tasks=True)
    added = next(s for s in entry.subentries.values() if s.title == "Börse")
    key = added.subentry_id
    assert aioclient_mock.call_count == 0
    # Only the quarter hour with the sensor's price; 16:00 has none (waits,
    # then counts without a price, as before).
    only_sensor = 29 / 30 * (0.05 + 0.10) * 1.19
    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(only_sensor)

    # Editing the tariff: unticked unless agreed before; ticking fills.
    result = await entry.start_subentry_reconfigure_flow(hass, key)
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "edit"})
    assert suggested(result, "smard_fill") is False
    await flows.async_configure(result["flow_id"], {**form, "smard_fill": True})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert aioclient_mock.call_count == 2
    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(SMARD_FILLED)


@pytest.mark.freeze_time(START)
async def test_added_total_price_tariff_gets_recorded_prices(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A total price comes from the sensor's own recorded states, never from
    SMARD.de."""
    # The new sensor's states, recorded before it belongs to a tariff.
    hass.states.async_set(NEW_TOTAL, "0.20", PRICE_UNIT)
    entry = await setup_entry(hass, market=False)
    for at, entity, state, attributes in (
        (utc(2026, 10, 25, 16, 14, 30), METER, "1001000", METER_ATTRIBUTES),
        (utc(2026, 10, 25, 16, 15, 0, 300000), NEW_TOTAL, "0.30", PRICE_UNIT),
        (utc(2026, 10, 25, 16, 29, 30), METER, "1002000", METER_ATTRIBUTES),
        (utc(2026, 10, 25, 16, 30, 0, 300000), NEW_TOTAL, "0.40", PRICE_UNIT),
    ):
        freezer.move_to(at)
        hass.states.async_set(entity, state, attributes)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    freezer.move_to(utc(2026, 10, 25, 16, 31))

    key = await add_tariff(
        hass, entry, "dynamic_total", {"name": "Gesamt", "price_entity": NEW_TOTAL}
    )
    expected = (1 + 1 / 30) * 0.20 + 29 / 30 * 0.30
    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(expected)
    assert aioclient_mock.call_count == 0
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["unpriced_until"] == {}
    assert diagnostics["past_prices_error"] is None
