"""Setup, booking through real state changes, restart, tariffs and removal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.tarifwacht.const import DOMAIN
from custom_components.tarifwacht.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import (
    DYNAMIC_SUBENTRY,
    FIXED_SUBENTRY,
    METER,
    METER_ATTRIBUTES,
    PRICE,
    mock_entry,
    price_attributes,
)

# 25.10.2026 17:00:30 CET. Fixture prices: 0.04577 €/kWh (17:00-17:15),
# 0.06856 €/kWh (17:15-17:30).
START = datetime(2026, 10, 25, 16, 0, 30, tzinfo=UTC)
P1, P2 = 0.04577, 0.06856
DYNAMIC = P1 + P1 / 30 + P2 * 29 / 30


def state(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id, key
    current = hass.states.get(entity_id)
    assert current is not None, key
    return current.state


def value(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> float:
    return float(state(hass, entry, key))


async def setup(hass: HomeAssistant) -> MockConfigEntry:
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


@pytest.mark.freeze_time(START)
async def test_booking_and_restart(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert value(hass, entry, "energy") == 0

    freezer.move_to(datetime(2026, 10, 25, 16, 14, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1001000", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    assert value(hass, entry, "energy") == pytest.approx(1.0)
    assert value(hass, entry, "fixed_consumption_cost") == pytest.approx(0.30)
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(P1)

    freezer.move_to(datetime(2026, 10, 25, 16, 29, 30, tzinfo=UTC))
    hass.states.async_set(METER, "1002000", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(DYNAMIC)
    assert value(hass, entry, "fixed_consumption_cost") == pytest.approx(0.60)

    # Restart: everything is recomputed from the stored quarter hours; the
    # ended quarter hour 17:00 gets its base price (31 €/month, 100 quarter
    # hours on 25.10.: 0.01 €).
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(DYNAMIC)
    assert value(hass, entry, "fixed_cost") == pytest.approx(0.61)
    assert value(hass, entry, "dynamic_cost") == pytest.approx(DYNAMIC)
    # The fixed tariff is the current one: only the dynamic one has a difference.
    assert value(hass, entry, "dynamic_difference") == pytest.approx(DYNAMIC - 0.61)
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_fixed_difference"
        )
        is None
    )
    assert value(hass, entry, "fixed_average_price") == pytest.approx(61 / 2)
    assert state(hass, entry, "cheapest") == "Dynamic"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "name" not in diagnostics["config"]
    assert diagnostics["prices"][PRICE]["resolution_minutes"] == 15
    assert diagnostics["prices"][PRICE]["wrong_unit"] is None
    assert diagnostics["consumption"]["quarter_hours"] == 2
    assert set(diagnostics["tariffs"]) == {"fixed", "dynamic"}


@pytest.mark.freeze_time(START)
async def test_entities_belong_to_their_tariff(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    registry = er.async_get(hass)
    for key, subentry in (
        ("fixed_cost", FIXED_SUBENTRY),
        ("dynamic_difference", DYNAMIC_SUBENTRY),
        ("energy", None),
    ):
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}"
        )
        assert entity_id
        assert registry.async_get(entity_id).config_subentry_id == subentry, key


@pytest.mark.freeze_time(START)
async def test_added_tariff_covers_whole_period(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A tariff added later is computed from the start, not from now."""
    entry = await setup(hass)
    await two_kwh(hass, freezer)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "tariff"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "fixed"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Günstig", "price": 25.0, "base_period": "month", "current": False},
    )
    await hass.async_block_till_done()
    added = next(s for s in entry.subentries.values() if s.title == "Günstig")
    key = added.subentry_id
    assert value(hass, entry, f"{key}_consumption_cost") == pytest.approx(0.50)
    # The reload at 17:29:30 books the base price of the ended 17:00 quarter.
    assert value(hass, entry, f"{key}_difference") == pytest.approx(0.50 - 0.61)
    assert value(hass, entry, "energy") == pytest.approx(2.0)


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
    assert diagnostics["prices"][PRICE]["wrong_unit"] == "ct/kWh"


@pytest.mark.freeze_time(START)
async def test_remove_entry(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.freeze_time(START)
async def test_entities_update_at_most_once_a_minute(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Fewer recorder writes: readings within a minute are shown together."""
    entry = await setup(hass)
    freezer.move_to(datetime(2026, 10, 25, 16, 5, tzinfo=UTC))
    hass.states.async_set(METER, "1000100", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    assert value(hass, entry, "energy") == pytest.approx(0.1)
    freezer.tick(timedelta(seconds=10))
    hass.states.async_set(METER, "1000200", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    assert value(hass, entry, "energy") == pytest.approx(0.1)
    freezer.tick(timedelta(seconds=50))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert value(hass, entry, "energy") == pytest.approx(0.2)


@pytest.mark.freeze_time(START)
async def test_closed_days_move_to_yearly_archive(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The live file keeps yesterday and today; older days are archived."""
    entry = await setup(hass)
    await two_kwh(hass, freezer)
    assert await hass.config_entries.async_unload(entry.entry_id)
    live = hass_storage[f"{DOMAIN}.{entry.entry_id}"]
    assert live["version"] == 3
    assert "2026-10-25" in live["data"]["consumption"]

    # Two days later: 25.10. (UTC) is closed and goes to the 2026 archive.
    freezer.move_to(datetime(2026, 10, 27, 16, 30, tzinfo=UTC))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    archive = hass_storage[f"{DOMAIN}.{entry.entry_id}.2026"]["data"]
    live = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert "2026-10-25" in archive["consumption"]
    assert "2026-10-25" in archive["prices"][PRICE]
    assert "2026-10-25" not in live["consumption"]
    assert live["archived_until"] == "2026-10-26"

    # Live state and archive together restore the period.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert value(hass, entry, "energy") == pytest.approx(2.0)
    assert value(hass, entry, "dynamic_consumption_cost") == pytest.approx(DYNAMIC)


@pytest.mark.freeze_time(START)
async def test_compare_action(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    await two_kwh(hass, freezer)

    async def compare(**data: Any) -> dict[str, Any]:
        return await hass.services.async_call(
            DOMAIN,
            "compare",
            {"config_entry": entry.entry_id, **data},
            blocking=True,
            return_response=True,
        )

    # Whole period: since setup (17:00 CET) until now (17:29:30).
    whole = await compare()
    assert whole["energy_kwh"] == pytest.approx(2.0)
    assert whole["quarter_hours"] == 2
    assert whole["cheapest"] == "Dynamic"
    tariffs = {t["tariff"]: t for t in whole["tariffs"]}
    assert tariffs["Fixed price"]["consumption_cost"] == pytest.approx(0.60)
    # Base price of the ended quarter hour 17:00 (31 €/month, 100 on 25.10.).
    assert tariffs["Fixed price"]["cost"] == pytest.approx(0.61)
    assert tariffs["Fixed price"]["current"] is True
    assert tariffs["Dynamic"]["difference_to_current"] == pytest.approx(
        round(DYNAMIC, 4) - 0.61, abs=1e-4
    )

    # From 17:15 local time (no zone: Home Assistant's time zone).
    part = await compare(start="2026-10-25 17:15:00")
    assert part["start"].startswith("2026-10-25T17:15:00")
    assert part["energy_kwh"] == pytest.approx(29 / 30, abs=1e-4)
    tariffs = {t["tariff"]: t for t in part["tariffs"]}
    assert tariffs["Fixed price"]["consumption_cost"] == pytest.approx(
        0.30 * 29 / 30, abs=1e-4
    )

    with pytest.raises(ServiceValidationError):
        await compare(start="2026-10-25 17:20:00", end="2026-10-25 17:10:00")


@pytest.mark.freeze_time(START)
async def test_repair_issue_for_wrong_price_unit(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass)
    issues = ir.async_get(hass)
    issue_id = f"{entry.entry_id}_price_unit_{PRICE}"
    attributes = {**price_attributes(), "unit_of_measurement": "ct/kWh"}
    hass.states.async_set(PRICE, "4.577", attributes)
    await hass.async_block_till_done()
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "price_unit"
    assert issue.translation_placeholders["unit"] == "ct/kWh"
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.freeze_time(START)
async def test_repair_issue_for_late_prices(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A price sensor without forecast: later quarter hours lack prices."""
    hass.states.async_set(PRICE, "0.31", {"unit_of_measurement": "€/kWh"})
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    freezer.move_to(datetime(2026, 10, 25, 16, 20, tzinfo=UTC))
    hass.states.async_set(METER, "1000500", METER_ATTRIBUTES)
    await hass.async_block_till_done()
    issues = ir.async_get(hass)
    issue_id = f"{entry.entry_id}_late_prices"
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    # The quarter hour 16:15 UTC ended at 16:30; an hour later it is overdue.
    freezer.move_to(datetime(2026, 10, 25, 17, 45, 1, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["tariffs"] == "Dynamic"
    assert value(hass, entry, "fixed_consumption_cost") == pytest.approx(0.15)
