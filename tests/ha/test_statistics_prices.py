"""A total-price sensor's history read from its long-term statistics.

Backfilled price statistics (as written by hand or by another tool) fill
the time before Tarifwacht read the sensor: the compare action and the
import of statistics book a dynamic total-price tariff through them,
without SMARD.de.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder, get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.models.statistics import StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.tarifwacht.const import DOMAIN
from custom_components.tarifwacht.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.tarifwacht.outdated import TARIFF_SERIES, issue_id
from custom_components.tarifwacht.runtime import MeterRuntime

from .conftest import PRICE
from .test_init import START, two_kwh, value
from .test_lookback import (
    NEW_TOTAL,
    PRICE_UNIT,
    add_tariff,
    compare,
    import_meter_statistics,
    setup_entry,
)
from .test_statistics_import import (
    LIVE_HOUR,
    entity_id,
    import_statistics,
    live_statistics,
)

FIRST_PRICE_HOUR = datetime(2026, 10, 24, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


async def import_price_statistics(hass: HomeAssistant, unit: str = "€/kWh") -> None:
    """Backfilled hourly prices of the day before the setup (€/kWh), written
    after Tarifwacht was set up, as by hand or by another tool.

    Hours 12, 13, 14 and 15 UTC: 20, 20, 25 and 30 ct. The meter statistics
    (import_meter_statistics) have energy for 13, 14 and 15 UTC.
    """
    metadata: dict[str, Any] = {
        "has_sum": False,
        "mean_type": StatisticMeanType.ARITHMETIC,
        "name": None,
        "source": "recorder",
        "statistic_id": PRICE,
        "unit_of_measurement": unit,
    }
    if "unit_class" in StatisticMetaData.__annotations__:
        metadata["unit_class"] = None
    prices = [0.20, 0.20, 0.25, 0.30]
    async_import_statistics(
        hass,
        metadata,  # type: ignore[arg-type]
        [
            {"start": FIRST_PRICE_HOUR + timedelta(hours=i), "mean": price}
            for i, price in enumerate(prices)
        ],
    )
    await async_wait_recording_done(hass)


@pytest.mark.freeze_time(START)
async def test_backfill_price_fills_only_missing_slots(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup_entry(hass, market=False)
    start = datetime(2026, 10, 25, 16, 30, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    table = entry.runtime_data.engine.price_table(PRICE)
    table.days.clear()
    table.merge({start: 0.25})
    freezer.move_to(START + timedelta(hours=4))

    result = await hass.services.async_call(
        "tarifwacht",
        "backfill_price",
        {
            "config_entry": entry.entry_id,
            "price_entity": PRICE,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price": 0.1654,
        },
        blocking=True,
        return_response=True,
    )

    assert result["slots_filled"] == 1
    assert result["already_priced_slots"] == 1
    assert table.get(start) == pytest.approx(0.25)
    assert table.get(start + timedelta(minutes=15)) == pytest.approx(0.1654)
    assert result["statistics_recalculation_required"] is True

    # The sensors of the tariff that reads PRICE are stale from the first
    # filled quarter hour: the button rewrites exactly those.
    assert entry.runtime_data.engine.stale_statistics == {
        f"dynamic_{name}": start for name in TARIFF_SERIES
    }
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry.entry_id)) is not None
    )


@pytest.mark.freeze_time(START)
async def test_compare_prices_from_statistics(hass: HomeAssistant) -> None:
    """The time before the setup books from the sensor's statistics:
    13 UTC 1 kWh at 20 ct, 14 UTC 1 kWh at 25 ct, 15 UTC 2 kWh at 30 ct."""
    entry = await setup_entry(hass, market=False)
    await import_meter_statistics(hass)
    # Written after the setup: read anew, not cached from the start.
    await import_price_statistics(hass)

    result = await compare(hass, entry, start="2026-10-24 15:00:00")
    assert result["energy_kwh"] == pytest.approx(4.0)
    tariffs = {t["tariff"]: t for t in result["tariffs"]}
    dynamic = tariffs["Dynamic"]
    assert dynamic["energy_without_price_kwh"] == pytest.approx(0.0)
    assert dynamic["consumption_cost"] == pytest.approx(1 * 0.20 + 1 * 0.25 + 2 * 0.30)
    assert dynamic["difference_to_current"] == pytest.approx(
        dynamic["consumption_cost"] - tariffs["Fixed price"]["cost"]
    )
    # All prices known: the dynamic tariff counts as cheapest.
    assert isinstance(result["cheapest"], str)


@pytest.mark.freeze_time(START)
async def test_compare_without_statistics_leaves_prices_out(
    hass: HomeAssistant,
) -> None:
    """Without backfilled statistics the total price sensor has no prices
    before the setup: the dynamic tariff is left out, nothing booked."""
    entry = await setup_entry(hass, market=False)
    await import_meter_statistics(hass)

    result = await compare(hass, entry, start="2026-10-24 15:00:00")
    assert result["energy_kwh"] == pytest.approx(4.0)
    tariffs = {t["tariff"]: t for t in result["tariffs"]}
    assert tariffs["Dynamic"]["energy_without_price_kwh"] == pytest.approx(4.0)
    assert tariffs["Dynamic"]["difference_to_current"] is None


@pytest.mark.freeze_time(START)
async def test_compare_ignores_statistics_in_another_unit(
    hass: HomeAssistant,
) -> None:
    """Hourly statistics recorded in another unit (ct/kWh) are not used as
    prices: the dynamic tariff is left out, like without statistics."""
    entry = await setup_entry(hass, market=False)
    await import_meter_statistics(hass)
    await import_price_statistics(hass, unit="ct/kWh")

    result = await compare(hass, entry, start="2026-10-24 15:00:00")
    assert result["energy_kwh"] == pytest.approx(4.0)
    tariffs = {t["tariff"]: t for t in result["tariffs"]}
    assert tariffs["Dynamic"]["energy_without_price_kwh"] == pytest.approx(4.0)
    assert tariffs["Dynamic"]["difference_to_current"] is None


@pytest.mark.freeze_time(START)
async def test_import_statistics_prices(hass: HomeAssistant) -> None:
    """Import statistics writes the time before the setup from the sensor's
    statistics: 3 hours with energy, 1.05 €."""
    entry = await setup_entry(hass, market=False)
    await import_meter_statistics(hass)
    await import_price_statistics(hass)
    dynamic_cost = entity_id(hass, entry, "dynamic_cost")
    await live_statistics(hass, {dynamic_cost: "EUR"})

    result = await import_statistics(hass, entry, "2026-10-24")
    await async_wait_recording_done(hass)
    assert result["start"].startswith("2026-10-24T14:00:00+02:00")
    assert result["skipped"] == []
    dynamic = result["sensors"][dynamic_cost]
    # 28 hours from 24.10. 12:00 UTC up to the sensor's first own row
    # (25.10. 16:00 UTC): the last written row starts 15:00 UTC (CET).
    assert dynamic["hours"] == 28
    assert dynamic["added"] == pytest.approx(1 * 0.20 + 1 * 0.25 + 2 * 0.30)
    assert dynamic["until"].startswith("2026-10-25T16:00:00+01:00")

    # Really written: the first three hours before the sensor's own first row.
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 10, 20, tzinfo=UTC),
        None,
        {dynamic_cost},
        "hour",
        None,
        {"sum"},
    )
    sums = {
        datetime.fromtimestamp(row["start"], UTC): row["sum"]
        for row in rows[dynamic_cost]
    }
    # The first hour with energy books 0.20, the running sum reaches 1.05
    # and shifts the sensor's own first row (live 0.5) by it.
    assert sums[datetime(2026, 10, 24, 13, tzinfo=UTC)] == pytest.approx(0.20)
    assert sums[datetime(2026, 10, 24, 15, tzinfo=UTC)] == pytest.approx(1.05)
    assert sums[LIVE_HOUR] == pytest.approx(0.5 + 1.05)


@pytest.mark.freeze_time(START)
async def test_added_total_price_tariff_gets_statistics_prices_once(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A total-price tariff added later: the quarter hour since the setup
    before the sensor's first price comes from the sensor's hourly
    statistics (the recorder has no state of it there). The price goes into
    the price table, so it is stored: after a restart the cost is the same
    before any background work, and nothing is left to fill."""
    entry = await setup_entry(hass, market=False)
    await two_kwh(hass, freezer)
    # The new sensor is read from 16:15 UTC on (its first state is 16:29:30).
    hass.states.async_set(NEW_TOTAL, "0.05", PRICE_UNIT)
    metadata: dict[str, Any] = {
        "has_sum": False,
        "mean_type": StatisticMeanType.ARITHMETIC,
        "name": None,
        "source": "recorder",
        "statistic_id": NEW_TOTAL,
        "unit_of_measurement": "€/kWh",
    }
    if "unit_class" in StatisticMetaData.__annotations__:
        metadata["unit_class"] = None
    # The hour of the setup (16:00 UTC): its row starts before the setup
    # (16:00:30) and must count.
    async_import_statistics(
        hass,
        metadata,  # type: ignore[arg-type]
        [{"start": datetime(2026, 10, 25, 16, tzinfo=UTC), "mean": 0.25}],
    )
    await async_wait_recording_done(hass)

    key = await add_tariff(
        hass, entry, "dynamic_total", {"name": "Gesamt", "price_entity": NEW_TOTAL}
    )
    # 16:00 from the statistics, 16:15 the live price (the mean does not
    # replace it).
    expected = (1 + 1 / 30) * 0.25 + 29 / 30 * 0.05
    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(expected)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["unpriced_until"] == {}

    # Stored: the same after a restart without the background fill.
    with patch.object(MeterRuntime, "_async_fill_past_prices", AsyncMock()):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(expected)
