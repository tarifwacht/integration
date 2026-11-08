"""Recalculated statistics rows and the plausibility of hourly meter changes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.tarifwacht.const import BERLIN
from custom_components.tarifwacht.lookback import (
    FIVE_MINUTES,
    HOUR,
    MAX_HOURLY_KWH,
    hourly_costs,
    period_costs,
    plausible_hours,
)
from custom_components.tarifwacht.statistics_rows import (
    add_values,
    build_rows,
    place_savings,
    total_between,
)
from custom_components.tarifwacht.tariffs import FixedPrice, Tariff
from custom_components.tarifwacht.timeslots import QUARTER


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# 30 ct/kWh, 31 EUR/month: 0.01 EUR per quarter hour on 25.10.2026 (100).
TARIFF = Tariff(FixedPrice(0.30), base_price=31.0)
SETUP = utc(2026, 10, 25, 16, 15)


def test_five_minute_costs_add_up_to_the_hours() -> None:
    quarters = [(SETUP, 0.6), (SETUP + QUARTER, 0.3), (SETUP + 2 * QUARTER, 0.0)]
    end = utc(2026, 10, 25, 18)
    hourly = hourly_costs(quarters, {"f": TARIFF}, SETUP, end, BERLIN)
    five = period_costs(quarters, {"f": TARIFF}, SETUP, end, BERLIN, FIVE_MINUTES)
    # A quarter hour's energy in equal thirds, priced with its price.
    assert five.energy[SETUP] == pytest.approx(0.2)
    assert five.consumption_cost["f"][SETUP + FIVE_MINUTES] == pytest.approx(0.06)
    assert five.cost["f"][SETUP] == pytest.approx(0.06 + 0.01 / 3)
    for hour, cost in hourly.cost["f"].items():
        parts = total_between(five.cost["f"], hour, hour + HOUR)
        assert parts == pytest.approx(cost)
    # The setup hour only from the setup on (three quarter hours of base).
    assert hourly.cost["f"][utc(2026, 10, 25, 16)] == pytest.approx(0.27 + 0.03)
    assert not five.incomplete


def test_rows_from_the_setup_keep_sum_minus_state() -> None:
    """Before the setup state = sum (as imported); from it on, state = the
    sensor's value, so sum - state is the same in every row."""
    hours = [utc(2026, 10, 25, h) for h in (14, 15, 16, 17)]
    values = dict(zip(hours, (1.0, 2.0, 0.5, 0.25), strict=True))
    rows = build_rows(
        values,
        start=hours[0],
        end=hours[-1] + HOUR,
        width=HOUR,
        base=0.0,
        offset=3.0,  # what was booked before the setup
        started=SETUP,
    )
    assert rows == [
        (hours[0], 1.0, 1.0),
        (hours[1], 3.0, 3.0),
        (hours[2], 0.5, 3.5),
        (hours[3], 0.75, 3.75),
    ]
    assert {round(total - state, 9) for _, state, total in rows[2:]} == {3.0}


def test_short_rows_only_where_they_exist() -> None:
    start = utc(2026, 10, 25, 17)
    values = {start + i * FIVE_MINUTES: 0.1 for i in range(12)}
    keep = {start, start + 11 * FIVE_MINUTES}
    rows = build_rows(
        values,
        start=start,
        end=start + HOUR,
        width=FIVE_MINUTES,
        base=2.0,
        offset=2.0,
        started=SETUP,
        keep=keep,
    )
    # The periods without a row still add up.
    assert rows == [
        (start, pytest.approx(0.1), pytest.approx(2.1)),
        (start + 11 * FIVE_MINUTES, pytest.approx(1.2), pytest.approx(3.2)),
    ]


def test_savings_show_as_the_sensor_shows_them() -> None:
    """From the setup on an hour's saving shows at minute 10 of the next hour
    (the sensor updates at minute 12); before it in its own hour."""
    setup_hour = utc(2026, 10, 25, 16)
    hourly = {setup_hour - HOUR: 0.5, setup_hour: 0.25, setup_hour + HOUR: 0.125}
    assert place_savings(hourly, setup_hour, HOUR) == {
        setup_hour - HOUR: 0.5,
        setup_hour + HOUR: 0.25,
        setup_hour + 2 * HOUR: 0.125,
    }
    assert place_savings(hourly, setup_hour, FIVE_MINUTES) == {
        setup_hour - HOUR: 0.5,
        setup_hour + HOUR + 2 * FIVE_MINUTES: 0.25,
        setup_hour + 2 * HOUR + 2 * FIVE_MINUTES: 0.125,
    }
    assert add_values({setup_hour: 1.0}, {setup_hour: 2.0, SETUP: 1.0}) == {
        setup_hour: 3.0,
        SETUP: 1.0,
    }


def test_unit_glitch_in_the_statistics_is_left_out() -> None:
    """The pattern seen on a meter that briefly reported Wh as kWh: the state
    107 -> 109851.5 -> 110.131 kWh. Home Assistant books the jump and, when
    the state falls again, a new cycle with the whole reading."""
    hour = utc(2025, 9, 24, 10)
    rows = [
        (hour, 0.4, 107.0),
        (hour + HOUR, 109851.5 - 107.0, 109851.5),
        (hour + 2 * HOUR, 110.131, 110.131),
        (hour + 3 * HOUR, 0.369, 110.5),
        # A busy hour: wallbox 11 kW and heat pump - must stay.
        (hour + 4 * HOUR, 20.0, 130.5),
        # Meter replaced: the sum went down.
        (hour + 5 * HOUR, -3.0, 2.0),
        (hour + 6 * HOUR, 0.5, 2.5),
    ]
    kept, left_out = plausible_hours(rows)
    assert left_out == [hour + HOUR, hour + 2 * HOUR, hour + 5 * HOUR]
    assert kept == [
        (hour, 0.4),
        (hour + 3 * HOUR, 0.369),
        (hour + 4 * HOUR, 20.0),
        (hour + 6 * HOUR, 0.5),
    ]
    # One rule with the live meter: 100 kW x 1.5 in an hour.
    assert MAX_HOURLY_KWH == 150.0
    assert plausible_hours([(hour, 150.0, None)])[1] == []
    assert plausible_hours([(hour, 150.1, None)])[1] == [hour]


def test_a_new_cycle_without_a_jump_stays() -> None:
    """A state that falls without a jump before (meter reset to 0): the
    hour's change is the new reading and stays."""
    hour = utc(2026, 1, 1)
    rows = [(hour, 1.0, 500.0), (hour + HOUR, 0.4, 0.4)]
    assert plausible_hours(rows) == (
        [(hour, 1.0), (hour + HOUR, 0.4)],
        [],
    )


def test_hours_without_rows_and_the_setup_hour() -> None:
    """The first hour counts only from the setup on (`start` mid-hour)."""
    rows = build_rows(
        {utc(2026, 10, 25, 16): 0.3},
        start=SETUP,
        end=utc(2026, 10, 25, 18),
        width=HOUR,
        base=0.0,
        offset=0.0,
        started=SETUP,
    )
    assert rows == [
        (utc(2026, 10, 25, 16), 0.3, 0.3),
        (utc(2026, 10, 25, 17), 0.3, 0.3),
    ]
    assert timedelta(hours=1) == HOUR
