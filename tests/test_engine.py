"""Engine: one meter booked into several tariffs (no Home Assistant)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.tarifwacht.const import BERLIN
from custom_components.tarifwacht.engine import PRICE_WAIT, Engine, migrate_v1
from custom_components.tarifwacht.meter import MeterTracker
from custom_components.tarifwacht.prices import ParsedPrices
from custom_components.tarifwacht.tariffs import (
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


def test_base_price_dst_day_and_parts() -> None:
    assert base_price_between(DAY_START, DAY_END, 31.0, BERLIN) == pytest.approx(1.0)
    # One quarter hour of the 100.
    assert base_price_between(
        DAY_START, DAY_START + QUARTER, 31.0, BERLIN
    ) == pytest.approx(0.01)
    # Over a month boundary: last day of October, first of November (30 days).
    start, end = utc(2026, 10, 30, 23), utc(2026, 11, 1, 23)
    assert base_price_between(start, end, 30.0, BERLIN) == pytest.approx(
        30 / 31 + 30 / 30
    )
    assert base_price_between(end, start, 30.0, BERLIN) == 0


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
    engine.backfill(readings)
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
