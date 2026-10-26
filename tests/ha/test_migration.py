"""Update from 0.1.0b1: tariffs become subentries, consumption comes back.

0.1.0b1 kept both tariffs in the entry data and only running totals in its
storage. The entry is migrated to subentries (entity ids and history kept),
the consumption since setup is read back from the recorder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
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

from .conftest import (
    METER,
    METER_ATTRIBUTES,
    PRICE,
    dynamic_tariff,
    entry_data,
    fixed_tariff,
    legacy_entry_data,
    price_attributes,
)
from .test_init import DYNAMIC, START, value


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


@pytest.mark.freeze_time(START)
async def test_update_from_0_1_0b1(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=METER,
        title="Haus",
        data=legacy_entry_data(),
        version=1,
    )
    entry.add_to_hass(hass)
    # Entities as 0.1.0b1 registered them.
    registry = er.async_get(hass)
    old = {
        key: registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}_{key}",
            config_entry=entry,
            suggested_object_id=object_id,
        ).entity_id
        for key, object_id in (
            ("fixed_cost", "haus_festpreis_kosten_gesamt"),
            ("dynamic_extra_cost", "haus_mehrkosten_dynamisch"),
        )
    }
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

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Entry: version 2, name and meter only; tariffs as subentries.
    assert entry.version == 2
    assert entry.data == entry_data()
    tariffs = {s.title: dict(s.data) for s in entry.subentries.values()}
    assert tariffs == {"Fixed price": fixed_tariff(), "Dynamic": dynamic_tariff()}

    # Consumption since setup read back from the recorder.
    assert value(hass, entry, "energy") == pytest.approx(2.0)
    assert value(hass, entry, "fixed_consumption_cost") == pytest.approx(0.60)
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(DYNAMIC)
    # Base price since setup (16:00 UTC): the quarter hour 16:00 has ended.
    assert value(hass, entry, "fixed_cost") == pytest.approx(0.61)

    # The old entities keep their entity ids; "extra cost" became the difference.
    assert float(hass.states.get(old["fixed_cost"]).state) == pytest.approx(0.61)
    difference = registry.async_get(old["dynamic_extra_cost"])
    assert difference.unique_id == f"{entry.entry_id}_dynamic_difference"
    assert float(hass.states.get(old["dynamic_extra_cost"]).state) == pytest.approx(
        DYNAMIC - 0.61
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["backfill"] == {"pending_until": None, "error": None}
    assert diagnostics["consumption"]["quarter_hours"] == 2
