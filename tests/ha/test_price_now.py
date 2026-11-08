"""What a tariff shows of itself: the sensor "Energy price now" and the
summary at the top of its gear menu."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.tarifwacht.const import DOMAIN

from .conftest import (
    DYNAMIC_SUBENTRY,
    FIXED_SUBENTRY,
    METER,
    METER_ATTRIBUTES,
    PRICE,
    fixed_tariff,
    mock_entry,
    price_attributes,
)

# 25.10.2026 17:00:30 CET. Fixture prices: 0.04577 €/kWh (17:00-17:15),
# 0.06856 €/kWh (17:15-17:30).
START = datetime(2026, 10, 25, 16, 0, 30, tzinfo=UTC)


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}_price_now"
    )
    assert found, key
    return found


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.freeze_time(START)
async def test_price_now(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    entry = await setup(hass)
    fixed_id = entity_id(hass, entry, "fixed")
    dynamic_id = entity_id(hass, entry, "dynamic")

    fixed = hass.states.get(fixed_id)
    assert fixed is not None
    assert float(fixed.state) == 30.0
    assert fixed.attributes["unit_of_measurement"] == "ct/kWh"
    # No long-term statistics.
    assert "state_class" not in fixed.attributes
    assert fixed.attributes["base_price_eur"] == 31.0
    assert fixed.attributes["base_period"] == "month"
    assert fixed.attributes["valid_since"] is None
    assert fixed.attributes["modul3_active_now"] is False
    assert "next_change" not in fixed.attributes
    assert "bonus" not in fixed.attributes

    dynamic = hass.states.get(dynamic_id)
    assert dynamic is not None
    assert float(dynamic.state) == pytest.approx(4.577)
    assert "modul3_active_now" not in dynamic.attributes

    # On the tariff's device, a main value (no entity category).
    registry = er.async_get(hass)
    item = registry.async_get(fixed_id)
    assert item is not None
    assert item.entity_category is None
    device = dr.async_get(hass).async_get(item.device_id)
    assert device is not None
    assert (DOMAIN, f"{entry.entry_id}_fixed") in device.identifiers

    # The next quarter hour: the dynamic price moves, the fixed state is not
    # written again.
    freezer.move_to(datetime(2026, 10, 25, 16, 15, 1, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    dynamic = hass.states.get(dynamic_id)
    assert dynamic is not None
    assert float(dynamic.state) == pytest.approx(6.856)
    again = hass.states.get(fixed_id)
    assert again is not None
    assert again.last_reported == fixed.last_reported


@pytest.mark.freeze_time(START)
async def test_price_now_after_a_price_change(hass: HomeAssistant) -> None:
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = mock_entry()
    entry.add_to_hass(hass)
    subentry = entry.subentries[FIXED_SUBENTRY]
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data=fixed_tariff(
            changes=[
                {"from": "2026-10-01", "price": 32.0, "base_price": 12.0},
                {"from": "2027-01-01", "price": 34.5, "base_period": "year"},
            ],
            bonus=100.0,
            bonus_date="2026-11-01",
        ),
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id(hass, entry, "fixed"))
    assert state is not None
    assert float(state.state) == 32.0
    assert state.attributes["base_price_eur"] == 12.0
    assert state.attributes["valid_since"] == "2026-10-01"
    assert state.attributes["next_change"] == {
        "from": "2027-01-01",
        "price_ct": 34.5,
        "base_price_eur": 12.0,
        "base_period": "year",
        "modul3": False,
    }
    assert state.attributes["bonus"] == {"amount_eur": 100.0, "date": "2026-11-01"}


# --- the summary in the gear menu --------------------------------------------


@pytest.fixture
def no_setup() -> Iterator[AsyncMock]:
    with patch(
        "custom_components.tarifwacht.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.mark.freeze_time("2026-11-08 12:00:00+00:00")
async def test_menu_summary(hass: HomeAssistant, no_setup: AsyncMock) -> None:
    hass.states.async_set(PRICE, "0.10574", price_attributes())
    hass.states.async_set(METER, "1234567.0", METER_ATTRIBUTES)
    entry = mock_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_subentry(
        entry,
        entry.subentries[FIXED_SUBENTRY],
        data=fixed_tariff(
            changes=[{"from": "2027-01-01", "price": 29.9, "base_price": 12.0}],
            bonus=50.0,
            bonus_date="2027-02-01",
        ),
    )

    result = await entry.start_subentry_reconfigure_flow(hass, FIXED_SUBENTRY)
    assert result["type"] is FlowResultType.MENU
    assert result["description_placeholders"]["summary"] == (
        "**Fixed price** · today: 30 ct/kWh + 31.00 €/month\n\n"
        "Prices:\n"
        "- from the start: 30 ct/kWh + 31.00 €/month\n"
        "- from 2027-01-01: 29.9 ct/kWh + 12.00 €/month **(upcoming)**\n\n"
        "Bonus: 50.00 € on 2027-02-01 · Modul 3: off · My current tariff: yes"
    )

    # "Edit prices from the start" says what it shows; adding does not.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit"}
    )
    assert result["step_id"] == "fixed"
    assert "from the start" in result["description_placeholders"]["edit_hint"]
    added = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "tariff"), context={"source": "user"}
    )
    added = await hass.config_entries.subentries.async_configure(
        added["flow_id"], {"next_step_id": "fixed"}
    )
    assert added["description_placeholders"] == {"edit_hint": ""}

    # The total price sensor by its name, in German.
    hass.config.language = "de"
    result = await entry.start_subentry_reconfigure_flow(hass, DYNAMIC_SUBENTRY)
    assert result["description_placeholders"]["summary"] == (
        "**Sensor mit Gesamtpreis** · heute: Preissensor „EPEX Spot Data Market "
        "Price“, ohne Grundpreis\n\nPreisänderungen: keine\n\n"
        "Bonus: – · Mein aktueller Tarif: nein"
    )
