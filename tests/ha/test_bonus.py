"""A one-off bonus against a real (in-memory) recorder: Home Assistant's own
compiles around its date book one step, the recalculation writes the same
and stays idempotent, the next compile continues without a jump."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifwacht.const import DOMAIN

from .conftest import (
    METER,
    METER_ATTRIBUTES,
    PRICE,
    entry_data,
    fixed_tariff,
    price_attributes,
    subentries_data,
)
from .test_statistics_recalculate import (
    compile_period,
    entity_id,
    press,
    rows,
    tick,
    value,
)

# 25.10.2026 17:00:30 CET; the bonus on 26.10. is credited at 23:00 UTC.
START = datetime(2026, 10, 25, 16, 0, 30, tzinfo=UTC)
BONUS_AT = datetime(2026, 10, 25, 23, tzinfo=UTC)
# Base price 31 EUR/month: per quarter hour 0.01 EUR on 25.10. (100), 1/96
# EUR on 26.10.
BASE = 0.01
BASE_26 = 1 / 96


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """The recorder must be set up before `hass` (listed first)."""


async def at(hass: HomeAssistant, freezer: FrozenDateTimeFactory, *t: int) -> None:
    freezer.move_to(datetime(*t, tzinfo=UTC))
    await hass.async_block_till_done()


@pytest.mark.freeze_time(START)
async def test_bonus_in_the_statistics(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    subentries = subentries_data()
    subentries[0]["data"] = fixed_tariff(bonus=250.0, bonus_date="2026-10-26")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=METER,
        title="Haus",
        data=entry_data(),
        version=2,
        subentries_data=subentries,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    cost = entity_id(hass, entry, "fixed_cost")
    consumption = entity_id(hass, entry, "fixed_consumption_cost")
    difference = entity_id(hass, entry, "dynamic_difference")

    # Base price only (no consumption) up to the hour before the bonus.
    await at(hass, freezer, 2026, 10, 25, 23, 0, 1)
    tick(hass, entry)
    assert value(hass, cost) == pytest.approx(28 * BASE)
    await at(hass, freezer, 2026, 10, 25, 23, 0, 10)
    await compile_period(hass, datetime(2026, 10, 25, 22, 55, tzinfo=UTC))
    # The quarter hour from midnight ended: the bonus is credited.
    await at(hass, freezer, 2026, 10, 25, 23, 15, 1)
    tick(hass, entry)
    assert value(hass, cost) == pytest.approx(28 * BASE + BASE_26 - 250)
    assert value(hass, difference) == pytest.approx(-28 * BASE - BASE_26 + 250)
    await at(hass, freezer, 2026, 10, 25, 23, 20, 10)
    await compile_period(hass, datetime(2026, 10, 25, 23, 15, tzinfo=UTC))
    await at(hass, freezer, 2026, 10, 26, 0, 0, 1)
    tick(hass, entry)
    await at(hass, freezer, 2026, 10, 26, 0, 0, 10)
    await compile_period(hass, datetime(2026, 10, 25, 23, 55, tzinfo=UTC))
    await at(hass, freezer, 2026, 10, 26, 0, 15, 1)
    tick(hass, entry)
    await at(hass, freezer, 2026, 10, 26, 0, 20, 10)
    await compile_period(hass, datetime(2026, 10, 26, 0, 15, tzinfo=UTC))

    # Home Assistant's own compile: the fall is a change, not a reset
    # (state class total): sum - state stays, the sum falls by the bonus.
    h22, h23 = datetime(2026, 10, 25, 22, tzinfo=UTC), BONUS_AT
    live = {
        start: (state, total) for start, state, total in await rows(hass, cost, "hour")
    }
    assert live[h23][1] - live[h22][1] == pytest.approx(live[h23][0] - live[h22][0])
    assert -250 < live[h23][1] - live[h22][1] < -249
    consumption_hours = await rows(hass, consumption, "hour")
    assert consumption_hours[-1][2] == consumption_hours[-2][2]

    # The recalculation writes the bonus into its hour (before the latest
    # short-term row) and changes nothing on a second press.
    await press(hass, entry)
    hours = await rows(hass, cost, "hour")
    new = {start: (state, total) for start, state, total in hours}
    assert new[h23][1] - new[h22][1] == pytest.approx(4 * BASE_26 - 250)
    assert new[h23][0] == pytest.approx(28 * BASE + 4 * BASE_26 - 250)
    assert new[h23][1] - new[h23][0] == pytest.approx(new[h22][1] - new[h22][0])
    differences = {s: total for s, _, total in await rows(hass, difference, "hour")}
    assert differences[h23] - differences[h22] == pytest.approx(250 - 4 * BASE_26)
    short = await rows(hass, cost, "5minute")
    await press(hass, entry)
    assert await rows(hass, cost, "hour") == hours
    assert await rows(hass, cost, "5minute") == short

    # The next live compile: only the base price of a quarter hour, no jump.
    await at(hass, freezer, 2026, 10, 26, 0, 30, 1)
    tick(hass, entry)
    await at(hass, freezer, 2026, 10, 26, 0, 35, 10)
    await compile_period(hass, datetime(2026, 10, 26, 0, 30, tzinfo=UTC))
    latest = await rows(hass, cost, "5minute")
    assert latest[-1][2] - latest[-2][2] == pytest.approx(BASE_26)
    assert latest[-1][1] == pytest.approx(value(hass, cost))
