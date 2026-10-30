"""Engine: one meter booked into several tariffs (no Home Assistant)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.tarifwacht.const import BERLIN
from custom_components.tarifwacht.engine import PRICE_WAIT, Engine, migrate_v1
from custom_components.tarifwacht.meter import MeterTracker
from custom_components.tarifwacht.prices import ParsedPrices
from custom_components.tarifwacht.tariffs import (
    BasePeriod,
    ComposedPrice,
    FixedPrice,
    Tariff,
    base_price_between,
    quarters_in_day,
)
from custom_components.tarifwacht.timeslots import QUARTER
from tests.test_core import DAY_END, DAY_START, fixture_prices

FIXED = 0.30  # EUR/kWh
TOTAL = "sensor.total_price"
MARKET = "sensor.market_price"


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def make_engine(fixed_base: float = 0.0, dynamic_base: float = 0.0) -> Engine:
    """A fixed tariff and a dynamic one reading the total-price sensor."""
    engine = Engine(meter=MeterTracker(max_power_kw=100), tariffs={}, tz=BERLIN)
    engine.tariffs = {
        "fixed": Tariff(FixedPrice(FIXED), fixed_base),
        "dynamic": Tariff(engine.price_table(TOTAL), dynamic_base),
    }
    return engine


def with_fixture_prices(engine: Engine, source: str = TOTAL) -> Engine:
    engine.price_table(source).merge(dict(fixture_prices().items()))
    return engine


def run_constant_purchase(engine: Engine, step: timedelta) -> None:
    """1 kW all day on 25.10.2026 (100 quarter hours)."""
    engine.start(DAY_START)
    at, value = DAY_START, 5000.0
    while at <= DAY_END:
        engine.on_meter(value, at, at)
        engine.tick(at)
        at += step
        value += step.total_seconds() / 3600


def snapshot(engine: Engine) -> dict[str, tuple[float, float, float, float]]:
    return {
        key: (t.energy, t.consumption_cost, t.base_cost, t.energy_without_price)
        for key, t in engine.totals.items()
    }


# --- base price ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "quarters"),
    [
        (utc(2026, 10, 24, 22), 100),  # 25.10.2026: clocks go back
        (utc(2026, 3, 28, 23), 92),  # 29.03.2026: clocks go forward
        (utc(2026, 6, 1, 10), 96),
    ],
)
def test_quarters_in_day(day: datetime, quarters: int) -> None:
    assert quarters_in_day(day, BERLIN) == quarters


MONTH, YEAR = BasePeriod.MONTH, BasePeriod.YEAR


def test_base_price_dst_day_and_parts() -> None:
    assert base_price_between(DAY_START, DAY_END, 31.0, MONTH, BERLIN) == (
        pytest.approx(1.0)
    )
    # One quarter hour of the 100.
    assert base_price_between(
        DAY_START, DAY_START + QUARTER, 31.0, MONTH, BERLIN
    ) == pytest.approx(0.01)
    # Over a month boundary: last day of October, first of November (30 days).
    start, end = utc(2026, 10, 30, 23), utc(2026, 11, 1, 23)
    assert base_price_between(start, end, 30.0, MONTH, BERLIN) == pytest.approx(
        30 / 31 + 30 / 30
    )
    assert base_price_between(end, start, 30.0, MONTH, BERLIN) == 0


@pytest.mark.parametrize(("year", "days"), [(2026, 365), (2028, 366)])
def test_base_price_per_year(year: int, days: int) -> None:
    """A yearly price: each day gets price / days of the year."""
    new_year = datetime(year, 1, 1, tzinfo=BERLIN).astimezone(UTC)
    next_year = datetime(year + 1, 1, 1, tzinfo=BERLIN).astimezone(UTC)
    assert base_price_between(new_year, next_year, 146.0, YEAR, BERLIN) == (
        pytest.approx(146.0)
    )
    assert base_price_between(
        new_year, new_year + timedelta(days=1), 146.0, YEAR, BERLIN
    ) == pytest.approx(146.0 / days)


@pytest.mark.parametrize("step", [QUARTER, timedelta(days=3)])
def test_base_price_month_adds_up(step: timedelta) -> None:
    """October 2026 (31 days, one of them with 25 hours) costs the monthly price."""
    engine = make_engine(fixed_base=12.0, dynamic_base=15.5)
    start, end = utc(2026, 9, 30, 22), utc(2026, 10, 31, 23)
    engine.start(start)
    at = start
    while at < end:
        engine.tick(at)
        at += step
    engine.tick(end)
    assert engine.totals["fixed"].base_cost == pytest.approx(12.0)
    assert engine.totals["dynamic"].base_cost == pytest.approx(15.5)
    assert engine.totals["fixed"].cost == pytest.approx(12.0)


def test_base_price_starts_with_first_start() -> None:
    engine = make_engine(fixed_base=30.0)
    engine.start(utc(2026, 6, 10, 12, 5))
    assert engine.started == utc(2026, 6, 10, 12)
    assert engine.totals["fixed"].base_cost == 0
    engine.tick(utc(2026, 6, 10, 12, 15))
    assert engine.totals["fixed"].base_cost == pytest.approx(30 / 30 / 96)


# --- consumption ----------------------------------------------------------------


def test_dst_day_fixed_and_dynamic() -> None:
    engine = with_fixture_prices(make_engine())
    run_constant_purchase(engine, timedelta(minutes=5))
    prices = fixture_prices()
    slots = [DAY_START + i * QUARTER for i in range(100)]
    fixed, dynamic = engine.totals["fixed"], engine.totals["dynamic"]
    assert engine.energy == pytest.approx(25.0)
    assert len(engine.consumption) == 100
    assert fixed.consumption_cost == pytest.approx(25.0 * FIXED)
    assert dynamic.consumption_cost == pytest.approx(
        sum(prices.get(s) for s in slots) * 0.25
    )
    assert dynamic.pending == {}
    assert fixed.average_price == pytest.approx(FIXED)


def test_composed_price() -> None:
    """Exchange price plus net surcharges, then VAT."""
    engine = make_engine()
    market = engine.price_table(MARKET)
    engine.tariffs["composed"] = Tariff(ComposedPrice(market, 0.15, 0.19))
    with_fixture_prices(engine, MARKET)
    run_constant_purchase(engine, timedelta(minutes=5))
    prices = fixture_prices()
    slots = [DAY_START + i * QUARTER for i in range(100)]
    expected = sum((prices.get(s) + 0.15) * 1.19 for s in slots) * 0.25
    assert engine.totals["composed"].consumption_cost == pytest.approx(expected)
    # Exchange price 0: surcharge plus VAT only.
    assert ComposedPrice(market, 0.15, 0.19).get(utc(2026, 10, 25, 0, 45)) == (
        pytest.approx(0.1785)
    )


def test_gap_is_spread_over_its_quarter_hours() -> None:
    """A meter offline for two hours: the delta gets the prices of the gap."""
    engine = make_engine()
    engine.price_table(TOTAL).merge(
        {utc(2026, 1, 5, 9) + i * QUARTER: 0.10 * (i + 1) for i in range(8)}
    )
    engine.start(utc(2026, 1, 5, 9))
    engine.on_meter(100.0, utc(2026, 1, 5, 9), utc(2026, 1, 5, 9))
    engine.on_meter(102.0, utc(2026, 1, 5, 11), utc(2026, 1, 5, 11))
    # 2 kWh evenly over 8 quarter hours priced 0.10 ... 0.80.
    assert engine.totals["dynamic"].consumption_cost == pytest.approx(
        0.25 * sum(range(1, 9)) / 10
    )
    assert engine.totals["fixed"].consumption_cost == pytest.approx(2 * FIXED)


def test_missing_dynamic_price_is_never_free() -> None:
    engine = make_engine()
    now = utc(2026, 1, 5, 9, 10)
    engine.start(utc(2026, 1, 5, 9))
    engine.on_meter(100.0, utc(2026, 1, 5, 9), now)
    engine.on_meter(100.5, now, now)
    fixed, dynamic = engine.totals["fixed"], engine.totals["dynamic"]
    assert fixed.consumption_cost == pytest.approx(0.5 * FIXED)
    assert dynamic.consumption_cost == 0
    assert dynamic.pending
    # The price arrives late: booked with it.
    engine.on_prices(
        TOTAL,
        ParsedPrices(prices={utc(2026, 1, 5, 9): 0.25}),
        now + timedelta(hours=1),
    )
    assert dynamic.consumption_cost == pytest.approx(0.125)
    assert dynamic.pending == {}

    # 09:10-09:20: half in the priced quarter hour, half in 09:15 whose price
    # never comes – counted, not costed, once 24 h after its end have passed.
    engine.on_meter(101.0, utc(2026, 1, 5, 9, 20), now)
    engine.tick(utc(2026, 1, 5, 9, 30) + PRICE_WAIT - timedelta(seconds=1))
    assert dynamic.pending
    engine.tick(utc(2026, 1, 5, 9, 30) + PRICE_WAIT)
    assert dynamic.pending == {}
    assert dynamic.energy_without_price == pytest.approx(0.25)
    assert dynamic.consumption_cost == pytest.approx(0.125 + 0.25 * 0.25)
    assert dynamic.energy == pytest.approx(0.75)
    assert engine.energy == pytest.approx(1.0)


def test_prices_arriving_after_the_start_are_booked() -> None:
    """A tariff added with a new price sensor: the start recomputes first."""
    engine = make_engine()
    start = utc(2026, 1, 5, 9)
    engine.start(start)
    engine.on_meter(100.0, start, start)
    engine.on_meter(101.0, utc(2026, 1, 5, 9, 30), utc(2026, 1, 5, 9, 30))
    # Two days later the sensor has never reported these prices.
    later = utc(2026, 1, 7, 9)
    restored = restart(engine, later)
    assert restored.totals["dynamic"].energy_without_price == pytest.approx(1.0)

    restored.on_prices(TOTAL, ParsedPrices(prices={start: 0.20}), later)
    assert restored.totals["dynamic"].energy_without_price == pytest.approx(0.5)

    # A price for a quarter hour without energy: no recomputation.
    totals = restored.totals
    restored.on_prices(TOTAL, ParsedPrices(prices={later: 0.30}), later)
    assert restored.totals is totals

    restored.on_prices(TOTAL, ParsedPrices(prices={start + QUARTER: 0.40}), later)
    dynamic = restored.totals["dynamic"]
    assert dynamic.energy_without_price == 0
    assert dynamic.consumption_cost == pytest.approx(0.5 * 0.20 + 0.5 * 0.40)
    assert restored.comparison.energy_left_out == 0


def test_comparison_leaves_out_quarter_hours_without_price() -> None:
    engine = make_engine(fixed_base=31.0)
    start = utc(2026, 1, 5, 9)
    engine.start(start)
    engine.price_table(TOTAL).merge({start: 0.25})
    engine.on_meter(100.0, start, start)
    # 09:00-09:20: 0.75 kWh priced in both tariffs, 0.25 kWh in 09:15 only
    # in the fixed one.
    engine.on_meter(101.0, utc(2026, 1, 5, 9, 20), utc(2026, 1, 5, 9, 20))
    comparison = engine.comparison
    assert comparison.energy == pytest.approx(0.75)
    # Waits as long as the dynamic tariff waits for the price.
    assert comparison.pending
    assert engine.compared_cost("dynamic") is not None

    later = utc(2026, 1, 5, 9, 30) + PRICE_WAIT
    engine.tick(later)
    assert comparison.pending == {}
    assert comparison.energy_left_out == pytest.approx(0.25)
    fixed, dynamic = engine.totals["fixed"], engine.totals["dynamic"]
    # The tariffs' own costs keep their rules: fixed costs all of it.
    assert fixed.consumption_cost == pytest.approx(1.0 * FIXED)
    assert dynamic.energy_without_price == pytest.approx(0.25)
    # Compared: only the 0.75 kWh both priced, plus the base prices.
    assert engine.compared_cost("fixed") == pytest.approx(
        0.75 * FIXED + fixed.base_cost
    )
    assert engine.compared_cost("dynamic") == pytest.approx(0.75 * 0.25)

    # The same after a restart (recomputed from the stored history).
    restored = restart(engine, later, fixed_base=31.0)
    assert restored.comparison.energy == pytest.approx(0.75)
    assert restored.comparison.energy_left_out == pytest.approx(0.25)
    assert restored.compared_cost("fixed") == pytest.approx(
        engine.compared_cost("fixed")
    )


def test_compared_cost_without_any_compared_energy() -> None:
    engine = make_engine()
    start = utc(2026, 1, 5, 9)
    engine.start(start)
    engine.on_meter(100.0, start, start)
    engine.on_meter(100.5, utc(2026, 1, 5, 9, 10), utc(2026, 1, 5, 9, 10))
    engine.tick(start + QUARTER + PRICE_WAIT)
    assert engine.comparison.energy_left_out == pytest.approx(0.5)
    assert engine.compared_cost("fixed") is None
    assert engine.compared_cost("dynamic") is None


def test_meter_reset_books_nothing() -> None:
    engine = make_engine()
    engine.start(utc(2026, 1, 5, 9))
    engine.on_meter(100.0, utc(2026, 1, 5, 9), utc(2026, 1, 5, 9))
    engine.on_meter(0.0, utc(2026, 1, 5, 9, 1), utc(2026, 1, 5, 9, 1))
    engine.on_meter(0.1, utc(2026, 1, 5, 9, 2), utc(2026, 1, 5, 9, 2))
    assert engine.energy == pytest.approx(0.1)
    assert engine.meter_events == {"reset": 1, "first": 1}


# --- recomputation ----------------------------------------------------------------


def restart(engine: Engine, now: datetime, **bases: float) -> Engine:
    """A new engine (as after a restart) from the stored state."""
    restored = make_engine(**bases)
    restored.restore(engine.as_dict())
    restored.start(now)
    return restored


@pytest.mark.parametrize("step", [timedelta(minutes=5), timedelta(seconds=61)])
def test_recompute_equals_incremental(step: timedelta) -> None:
    engine = with_fixture_prices(make_engine(fixed_base=10.0, dynamic_base=12.0))
    run_constant_purchase(engine, step)
    # Compare at the same moment (the last reading may come before midnight).
    engine.tick(DAY_END)
    restored = restart(engine, DAY_END, fixed_base=10.0, dynamic_base=12.0)
    for key, values in snapshot(engine).items():
        assert snapshot(restored)[key] == pytest.approx(values, abs=1e-6)
    assert restored.energy == pytest.approx(engine.energy, abs=1e-6)
    assert restored.as_dict() == engine.as_dict()


def test_changed_tariff_covers_whole_period() -> None:
    engine = with_fixture_prices(make_engine())
    run_constant_purchase(engine, timedelta(minutes=5))
    # The fixed price is corrected and a base price added after the fact.
    restored = make_engine(fixed_base=31.0)
    restored.tariffs["fixed"] = Tariff(FixedPrice(0.25), 31.0)
    restored.restore(engine.as_dict())
    restored.start(DAY_END)
    assert restored.totals["fixed"].consumption_cost == pytest.approx(25.0 * 0.25)
    assert restored.totals["fixed"].base_cost == pytest.approx(1.0)


def test_added_tariff_covers_whole_period() -> None:
    engine = with_fixture_prices(make_engine())
    run_constant_purchase(engine, timedelta(minutes=5))
    restored = make_engine()
    restored.tariffs["composed"] = Tariff(
        ComposedPrice(restored.price_table(TOTAL), 0.0, 0.0)
    )
    restored.restore(engine.as_dict())
    restored.start(DAY_END)
    assert restored.totals["composed"].consumption_cost == pytest.approx(
        engine.totals["dynamic"].consumption_cost
    )


def test_restore_keeps_price_table_references() -> None:
    engine = with_fixture_prices(make_engine())
    restored = make_engine()
    table = restored.price_table(TOTAL)
    restored.restore(engine.as_dict())
    assert restored.price_table(TOTAL) is table
    assert restored.tariffs["dynamic"].prices is table
    assert len(table) == 196


# --- update from 0.1.0b1 ------------------------------------------------------------


def test_migrate_v1_with_backfill() -> None:
    """0.1.0b1 kept totals only; the consumption comes back from the recorder."""
    created = utc(2026, 10, 25, 16, 0, 30)
    readings = [
        (1000.0, created),
        (1001.0, utc(2026, 10, 25, 16, 14, 30)),
        (1002.0, utc(2026, 10, 25, 16, 29, 30)),
    ]
    v1 = {
        "meter": {"last_value": 1002.0, "last_time": "2026-10-25T16:29:30+00:00"},
        "prices": {
            slot.isoformat(): price
            for slot, price in fixture_prices().items()
            if utc(2026, 10, 25, 15) <= slot < utc(2026, 10, 25, 17)
        },
        "energy": 2.0,
        "next_base_slot": "2026-10-25T16:15:00+00:00",
        "tariffs": {"fixed": {"ledger": {"totals": {"consumption_cost": 0.6}}}},
        "meter_events": {"first": 1},
    }
    data = migrate_v1(v1, TOTAL, created)
    assert data["started"] == "2026-10-25T16:00:00+00:00"
    assert data["backfill_until"] == "2026-10-25T16:29:30+00:00"

    engine = make_engine(fixed_base=31.0)
    engine.restore(data)
    assert engine.backfill_until == utc(2026, 10, 25, 16, 29, 30)
    engine.backfill([(999.0, utc(2026, 10, 25, 15, 30)), *readings], since=created)
    assert engine.backfill_until is None
    now = utc(2026, 10, 25, 16, 30)
    engine.start(now)
    p1, p2 = 0.04577, 0.06856  # fixture: 17:00 and 17:15 CET
    assert engine.energy == pytest.approx(2.0)
    assert engine.totals["fixed"].consumption_cost == pytest.approx(0.60)
    assert engine.totals["dynamic"].consumption_cost == pytest.approx(
        p1 + p1 / 30 + p2 * 29 / 30
    )
    # Base price since setup: two quarter hours (16:00, 16:15 UTC).
    assert engine.totals["fixed"].base_cost == pytest.approx(0.02)
    # The live meter continues where 0.1.0b1 stopped: nothing booked twice.
    engine.on_meter(1002.5, utc(2026, 10, 25, 16, 44, 30), now)
    assert engine.energy == pytest.approx(2.5)


# --- archives -----------------------------------------------------------------------


def test_live_state_and_archive_restore_everything() -> None:
    """Closed days go to a yearly archive; together they restore the period."""
    engine = with_fixture_prices(make_engine(fixed_base=10.0, dynamic_base=12.0))
    run_constant_purchase(engine, timedelta(minutes=5))
    engine.tick(DAY_END)
    before = date(2026, 10, 25)
    engine.archived_until = before
    live = engine.as_dict()
    archive = engine.archive_dict(2026, before)
    assert live["archived_until"] == "2026-10-25"
    assert set(live["consumption"]) == {"2026-10-25"}
    assert set(archive["consumption"]) == {"2026-10-24"}
    assert set(archive["prices"][TOTAL]) == {"2026-10-24"}

    restored = make_engine(fixed_base=10.0, dynamic_base=12.0)
    restored.restore(live)
    restored.restore_archive(archive)
    restored.start(DAY_END)
    for key, values in snapshot(engine).items():
        assert snapshot(restored)[key] == pytest.approx(values, abs=1e-6)
    assert restored.archived_until == before
    assert restored.years() == {2026}


# --- costs of a period (compare action) ---------------------------------------------


def test_costs_between_whole_and_parts() -> None:
    engine = with_fixture_prices(make_engine(fixed_base=31.0))
    run_constant_purchase(engine, timedelta(minutes=5))
    engine.tick(DAY_END)
    whole = engine.costs_between(DAY_START, DAY_END, DAY_END)
    assert whole.quarter_hours == 100
    assert whole.energy == pytest.approx(25.0)
    for key, totals in engine.totals.items():
        assert whole.totals[key].cost == pytest.approx(totals.cost)
    # Two halves add up to the whole day, base price included.
    middle = DAY_START + 50 * QUARTER
    first = engine.costs_between(DAY_START, middle, DAY_END)
    second = engine.costs_between(middle, DAY_END, DAY_END)
    for key in engine.totals:
        assert first.totals[key].cost + second.totals[key].cost == pytest.approx(
            whole.totals[key].cost
        )
    assert first.totals["fixed"].base_cost == pytest.approx(0.5)


def test_costs_between_is_clipped_to_the_period() -> None:
    engine = with_fixture_prices(make_engine(fixed_base=31.0))
    run_constant_purchase(engine, timedelta(minutes=5))
    engine.tick(DAY_END)
    result = engine.costs_between(
        DAY_START - timedelta(days=30), DAY_END + timedelta(days=30), DAY_END
    )
    assert result.start == DAY_START
    assert result.end == DAY_END + QUARTER
    assert result.totals["fixed"].base_cost == pytest.approx(1.0)
    empty = engine.costs_between(
        DAY_START - timedelta(days=30), DAY_START - timedelta(days=1), DAY_END
    )
    assert empty.quarter_hours == 0
    assert empty.totals["fixed"].cost == 0


def test_late_prices() -> None:
    engine = make_engine()
    engine.start(utc(2026, 1, 5, 9))
    engine.on_meter(100.0, utc(2026, 1, 5, 9), utc(2026, 1, 5, 9))
    engine.on_meter(100.5, utc(2026, 1, 5, 9, 10), utc(2026, 1, 5, 9, 10))
    grace = timedelta(hours=1)
    # The quarter hour 09:00 ends at 09:15: overdue only after 10:15.
    assert engine.late_prices(utc(2026, 1, 5, 10, 15), grace) == set()
    assert engine.late_prices(utc(2026, 1, 5, 10, 16), grace) == {"dynamic"}
    engine.on_prices(
        TOTAL, ParsedPrices(prices={utc(2026, 1, 5, 9): 0.3}), utc(2026, 1, 5, 10, 20)
    )
    assert engine.late_prices(utc(2026, 1, 5, 10, 20), grace) == set()


def test_costs_between_includes_the_running_quarter_hour() -> None:
    """An end inside a quarter hour (e.g. "now") includes that quarter hour."""
    engine = with_fixture_prices(make_engine())
    run_constant_purchase(engine, timedelta(minutes=5))
    now = DAY_START + 10 * QUARTER + timedelta(minutes=7)
    result = engine.costs_between(DAY_START, now, DAY_END)
    assert result.quarter_hours == 11
    assert result.end == DAY_START + 11 * QUARTER


def test_quarter_hour_without_energy_does_not_wait() -> None:
    """A quarter hour with 0 kWh and no price yet is nothing to wait for."""
    engine = make_engine()
    slot = utc(2026, 10, 25, 2)
    engine.started = slot
    engine.consumption.set(slot, 0.0)
    now = slot + 3 * QUARTER
    engine.recompute(now)
    assert engine.totals["dynamic"].pending == {}
    assert engine.comparison.pending == {}
    assert engine.late_prices(now + PRICE_WAIT, timedelta(hours=1)) == set()
