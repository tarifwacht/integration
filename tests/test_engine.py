"""Engine: one meter booked into a fixed and a dynamic tariff (no Home Assistant)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.tarifwacht.const import BERLIN, TARIFF_DYNAMIC, TARIFF_FIXED
from custom_components.tarifwacht.engine import Engine, TariffAccount
from custom_components.tarifwacht.ledger import PRICE_WAIT
from custom_components.tarifwacht.meter import MeterTracker
from custom_components.tarifwacht.prices import ParsedPrices, PriceTable
from custom_components.tarifwacht.tariffs import (
    FixedPrice,
    base_price_per_slot,
    quarters_in_day,
)
from custom_components.tarifwacht.timeslots import QUARTER
from tests.test_core import DAY_END, DAY_START, fixture_prices

FIXED = 0.30  # EUR/kWh


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def make_engine(
    fixed_base: float = 0.0, dynamic_base: float = 0.0, prices: PriceTable | None = None
) -> Engine:
    table = prices if prices is not None else PriceTable()
    return Engine(
        meter=MeterTracker(max_power_kw=100),
        tariffs={
            TARIFF_FIXED: TariffAccount(FixedPrice(FIXED), fixed_base),
            TARIFF_DYNAMIC: TariffAccount(table, dynamic_base),
        },
        tz=BERLIN,
        prices=table,
    )


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


def test_base_price_day_adds_up_on_dst_day() -> None:
    slots = [DAY_START + i * QUARTER for i in range(100)]
    assert sum(base_price_per_slot(s, 31.0, BERLIN) for s in slots) == pytest.approx(
        1.0
    )


@pytest.mark.parametrize("step", [QUARTER, timedelta(days=3)])
def test_base_price_month_adds_up(step: timedelta) -> None:
    """October 2026 (31 days, one of them with 25 hours) costs the monthly price."""
    engine = make_engine(fixed_base=12.0, dynamic_base=15.5)
    start, end = utc(2026, 9, 30, 22), utc(2026, 10, 31, 23)
    at = start
    while at < end:
        engine.tick(at)
        at += step
    engine.tick(end)
    assert engine.tariffs[TARIFF_FIXED].base_cost == pytest.approx(12.0)
    assert engine.tariffs[TARIFF_DYNAMIC].base_cost == pytest.approx(15.5)
    assert engine.tariffs[TARIFF_FIXED].cost == pytest.approx(12.0)


def test_base_price_starts_with_first_start() -> None:
    engine = make_engine(fixed_base=30.0)
    engine.tick(utc(2026, 6, 10, 12, 5))
    assert engine.tariffs[TARIFF_FIXED].base_cost == 0
    engine.tick(utc(2026, 6, 10, 12, 15))
    assert engine.tariffs[TARIFF_FIXED].base_cost == pytest.approx(30 / 30 / 96)


# --- consumption ----------------------------------------------------------------


def run_constant_purchase(engine: Engine, step: timedelta) -> None:
    """1 kW all day on 25.10.2026 (100 quarter hours)."""
    at, value = DAY_START, 5000.0
    while at <= DAY_END:
        engine.on_meter(value, at, at)
        engine.tick(at)
        at += step
        value += step.total_seconds() / 3600


def test_dst_day_fixed_and_dynamic() -> None:
    prices = fixture_prices()
    engine = make_engine(prices=prices)
    run_constant_purchase(engine, timedelta(minutes=5))
    slots = [DAY_START + i * QUARTER for i in range(100)]
    fixed, dynamic = engine.tariffs[TARIFF_FIXED], engine.tariffs[TARIFF_DYNAMIC]
    assert engine.energy == pytest.approx(25.0)
    assert fixed.consumption_cost == pytest.approx(25.0 * FIXED)
    assert dynamic.consumption_cost == pytest.approx(
        sum(prices.get(s) for s in slots) * 0.25
    )
    assert dynamic.ledger.pending == {}


def test_gap_is_spread_over_its_quarter_hours() -> None:
    """A meter offline for two hours: the delta gets the prices of the gap."""
    prices = PriceTable()
    prices.merge({utc(2026, 1, 5, 9) + i * QUARTER: 0.10 * (i + 1) for i in range(8)})
    engine = make_engine(prices=prices)
    engine.on_meter(100.0, utc(2026, 1, 5, 9), utc(2026, 1, 5, 9))
    engine.on_meter(102.0, utc(2026, 1, 5, 11), utc(2026, 1, 5, 11))
    dynamic = engine.tariffs[TARIFF_DYNAMIC]
    # 2 kWh evenly over 8 quarter hours priced 0.10 ... 0.80.
    assert dynamic.consumption_cost == pytest.approx(0.25 * sum(range(1, 9)) / 10)
    assert engine.tariffs[TARIFF_FIXED].consumption_cost == pytest.approx(2 * FIXED)


def test_missing_dynamic_price_is_never_free() -> None:
    engine = make_engine()
    now = utc(2026, 1, 5, 9, 10)
    engine.on_meter(100.0, utc(2026, 1, 5, 9), now)
    engine.on_meter(100.5, now, now)
    fixed, dynamic = engine.tariffs[TARIFF_FIXED], engine.tariffs[TARIFF_DYNAMIC]
    assert fixed.consumption_cost == pytest.approx(0.5 * FIXED)
    assert dynamic.consumption_cost == 0
    assert dynamic.ledger.pending
    # The price arrives late: booked with it.
    engine.on_prices(
        ParsedPrices(prices={utc(2026, 1, 5, 9): 0.25}), now + timedelta(hours=1)
    )
    assert dynamic.consumption_cost == pytest.approx(0.125)

    # 09:10-09:20: half in the priced quarter hour, half in 09:15 whose price
    # never comes – counted, not costed.
    engine.on_meter(101.0, utc(2026, 1, 5, 9, 20), now)
    engine.tick(now + PRICE_WAIT + timedelta(minutes=10))
    assert dynamic.ledger.pending == {}
    assert dynamic.ledger.totals["energy_without_price"] == pytest.approx(0.25)
    assert dynamic.consumption_cost == pytest.approx(0.125 + 0.25 * 0.25)


def test_meter_reset_books_nothing() -> None:
    engine = make_engine()
    engine.on_meter(100.0, utc(2026, 1, 5, 9), utc(2026, 1, 5, 9))
    engine.on_meter(0.0, utc(2026, 1, 5, 9, 1), utc(2026, 1, 5, 9, 1))
    engine.on_meter(0.1, utc(2026, 1, 5, 9, 2), utc(2026, 1, 5, 9, 2))
    assert engine.energy == pytest.approx(0.1)
    assert engine.meter_events == {"reset": 1, "first": 1}


def test_round_trip() -> None:
    prices = fixture_prices()
    engine = make_engine(fixed_base=10.0, dynamic_base=12.0, prices=prices)
    run_constant_purchase(engine, timedelta(minutes=7))
    restored = make_engine(fixed_base=10.0, dynamic_base=12.0)
    restored.restore(engine.as_dict())
    assert restored.as_dict() == engine.as_dict()
    assert restored.tariffs[TARIFF_DYNAMIC].cost == pytest.approx(
        engine.tariffs[TARIFF_DYNAMIC].cost
    )
    # The restored dynamic account reads the restored price table.
    assert restored.tariffs[TARIFF_DYNAMIC].prices is restored.prices
