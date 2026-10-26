"""Comparison before the setup: hourly statistics and SMARD.de prices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.tarifwacht.const import (
    BERLIN,
    CONF_KIND,
    CONF_PRICE_ENTITY,
    CONF_VAT,
    KIND_DYNAMIC_MARKET,
    KIND_DYNAMIC_TOTAL,
)
from custom_components.tarifwacht.engine import Engine, month_bounds
from custom_components.tarifwacht.lookback import (
    FallbackPrice,
    Lookback,
    hours_without_energy,
    spread_hours,
)
from custom_components.tarifwacht.meter import MeterTracker
from custom_components.tarifwacht.prices import PriceTable
from custom_components.tarifwacht.smard import (
    parse_index,
    parse_week,
    week_start,
    weeks_covering,
)
from custom_components.tarifwacht.tariff_config import tariff_from_data
from custom_components.tarifwacht.tariffs import ComposedPrice, FixedPrice, Tariff
from custom_components.tarifwacht.timeslots import QUARTER
from tests.conftest import load_fixture
from tests.test_core import fixture_prices

MARKET = "sensor.market_price"
TOTAL = "sensor.total_price"


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def smard_table() -> PriceTable:
    table = PriceTable()
    for name in ("smard_week_2025-09-29.json", "smard_week_2026-10-19.json"):
        table.merge(parse_week(load_fixture(name)))
    return table


# --- SMARD.de -------------------------------------------------------------------


def test_smard_matches_epex_spot() -> None:
    """Same auction: SMARD's DE-LU price equals the EPEX Spot market price."""
    smard = smard_table()
    # The SMARD week ends on Sunday 25.10. (100 quarter hours, DST change).
    epex = [(s, p) for s, p in fixture_prices().items() if s < utc(2026, 10, 25, 23)]
    assert len(epex) >= 100
    for slot, price in epex:
        assert smard.get(slot) == pytest.approx(price, abs=1e-9), slot


def test_smard_hourly_prices_before_october_2025() -> None:
    week = parse_week(load_fixture("smard_week_2025-09-29.json"))
    # 30.09.2025 12:00 CEST: one hourly price for all four quarter hours.
    hour = utc(2025, 9, 30, 10)
    assert len({week[hour + i * QUARTER] for i in range(4)}) == 1
    assert len(week) == 672


def test_smard_week_with_dst_change() -> None:
    week = parse_week(load_fixture("smard_week_2026-10-19.json"))
    assert len(week) == 676  # 7 days + the repeated hour on 25.10.


def test_smard_weeks_covering() -> None:
    index = parse_index(load_fixture("smard_index_quarterhour.json"))
    weeks = weeks_covering(index, utc(2026, 10, 25, 10), utc(2026, 10, 26, 10))
    # Sunday 25.10. and Monday 26.10. are in two week files.
    assert week_start(weeks[0]) == utc(2026, 10, 18, 22)
    assert len(weeks) == 2


# --- hourly statistics -------------------------------------------------------------


def test_spread_hours_clips_to_period() -> None:
    hourly = [(utc(2026, 10, 25, 10), 2.0), (utc(2026, 10, 25, 11), 4.0)]
    quarters = spread_hours(
        hourly, utc(2026, 10, 25, 10, 20), utc(2026, 10, 25, 11, 30)
    )
    # From the quarter hour of the start (10:15) to the end (11:30, exclusive).
    assert quarters == {
        utc(2026, 10, 25, 10, 15): 0.5,
        utc(2026, 10, 25, 10, 30): 0.5,
        utc(2026, 10, 25, 10, 45): 0.5,
        utc(2026, 10, 25, 11, 0): 1.0,
        utc(2026, 10, 25, 11, 15): 1.0,
    }


def test_hours_without_energy() -> None:
    hourly = [(utc(2026, 10, 25, 10), 1.0), (utc(2026, 10, 25, 12), 1.0)]
    assert (
        hours_without_energy(hourly, utc(2026, 10, 25, 10), utc(2026, 10, 25, 13)) == 1
    )
    # A partial hour at the start or end counts.
    assert (
        hours_without_energy(
            hourly, utc(2026, 10, 25, 9, 30), utc(2026, 10, 25, 13, 15)
        )
        == 3
    )


def test_fallback_only_before_until() -> None:
    primary, secondary = PriceTable(), PriceTable()
    a, b, c = utc(2026, 10, 25, 10), utc(2026, 10, 25, 11), utc(2026, 10, 25, 12)
    primary.merge({a: 0.1})
    secondary.merge({a: 0.9, b: 0.2, c: 0.3})
    price = FallbackPrice(primary, secondary, until=c)
    assert price.get(a) == 0.1
    assert price.get(b) == 0.2
    assert price.get(c) is None


def test_market_table_only_for_exchange_price_tariffs() -> None:
    sensor, completed = PriceTable(), PriceTable()
    slot = utc(2026, 10, 25, 10)
    sensor.merge({slot: 0.5})
    completed.merge({slot: 0.1})
    market = tariff_from_data(
        {CONF_KIND: KIND_DYNAMIC_MARKET, CONF_PRICE_ENTITY: MARKET, CONF_VAT: 0.0},
        lambda _: sensor,
        lambda _: completed,
    )
    total = tariff_from_data(
        {CONF_KIND: KIND_DYNAMIC_TOTAL, CONF_PRICE_ENTITY: TOTAL},
        lambda _: sensor,
        lambda _: completed,
    )
    assert market.price(slot) == pytest.approx(0.1)
    assert total.price(slot) == pytest.approx(0.5)


# --- engine ------------------------------------------------------------------------


STARTED = utc(2026, 10, 25, 16)  # 17:00 CET
NOW = utc(2026, 10, 27, 12)


def engine_with_lookback() -> tuple[Engine, Lookback]:
    """Fixed (31 €/month), market price + 10 ct + 19 %, total price sensor."""
    engine = Engine(meter=MeterTracker(max_power_kw=100), tariffs={}, tz=BERLIN)
    sensor = engine.price_table(MARKET)
    sensor.merge({STARTED: 0.2})
    engine.price_table(TOTAL).merge({STARTED: 0.4})
    engine.started = STARTED
    engine.consumption.add(STARTED, 0.5)

    def tariffs(market: PriceTable | FallbackPrice) -> dict[str, Tariff]:
        return {
            "fixed": Tariff(FixedPrice(0.30), 31.0),
            "market": Tariff(ComposedPrice(market, 0.10, 0.19)),
            "total": Tariff(engine.price_table(TOTAL)),
        }

    engine.tariffs = tariffs(sensor)
    hourly = [(utc(2026, 10, 25, 14), 1.0), (utc(2026, 10, 25, 15), 2.0)]
    lookback = Lookback(
        consumption=spread_hours(hourly, utc(2026, 10, 25, 14), STARTED),
        tariffs=tariffs(FallbackPrice(sensor, smard_table(), STARTED)),
        until=STARTED,
    )
    return engine, lookback


def test_costs_before_setup() -> None:
    engine, lookback = engine_with_lookback()
    start, end = utc(2026, 10, 25, 14), STARTED + QUARTER
    result = engine.costs_between(start, end, NOW, lookback)
    assert result.start == start
    assert result.energy == pytest.approx(3.5)
    assert result.quarter_hours == 9
    assert result.estimated_energy == pytest.approx(3.0)
    assert result.estimated_quarter_hours == 8

    fixed = result.totals["fixed"]
    assert fixed.consumption_cost == pytest.approx(3.5 * 0.30)
    # 31 €/month, 31 days, 100 quarter hours on 25.10.: 0.01 € each.
    assert fixed.base_cost == pytest.approx(0.09)

    smard = smard_table()
    expected = 0.5 * (0.2 + 0.10) * 1.19
    slot = start
    while slot < STARTED:
        energy = 0.25 if slot.hour == 14 else 0.5
        expected += energy * (smard.get(slot) + 0.10) * 1.19
        slot += QUARTER
    assert result.totals["market"].consumption_cost == pytest.approx(expected)

    # The total price sensor has no prices before the setup.
    total = result.totals["total"]
    assert total.energy == pytest.approx(0.5)
    assert total.energy_without_price == pytest.approx(3.0)

    assert list(result.months) == ["2026-10"]
    month = result.months["2026-10"]
    assert month.totals["fixed"].cost == pytest.approx(fixed.cost)


def test_missing_price_before_setup_does_not_wait() -> None:
    """Right after the setup: the total price sensor never had these prices."""
    engine, lookback = engine_with_lookback()
    now = STARTED + timedelta(minutes=1)
    result = engine.costs_between(utc(2026, 10, 25, 14), now, now, lookback)
    total = result.totals["total"]
    assert total.energy_without_price == pytest.approx(3.0)
    assert not total.pending


def test_without_lookback_the_period_starts_at_setup() -> None:
    engine, _ = engine_with_lookback()
    result = engine.costs_between(utc(2026, 10, 25, 14), STARTED + QUARTER, NOW)
    assert result.start == STARTED
    assert result.energy == pytest.approx(0.5)
    assert result.estimated_energy == 0


def test_months_split_at_local_midnight() -> None:
    engine = Engine(meter=MeterTracker(max_power_kw=100), tariffs={}, tz=BERLIN)
    started = utc(2026, 10, 1, 6)
    engine.started = started
    fixed = {"fixed": Tariff(FixedPrice(0.30), 30.0)}
    engine.tariffs = fixed
    # 30.09. 23:00 and 01.10. 00:00 local time (CEST).
    hourly = [(utc(2026, 9, 30, 21), 1.0), (utc(2026, 9, 30, 22), 2.0)]
    lookback = Lookback(
        consumption=spread_hours(hourly, utc(2026, 9, 30, 21), started),
        tariffs=fixed,
        until=started,
    )
    result = engine.costs_between(
        utc(2026, 9, 30, 21), utc(2026, 9, 30, 23), NOW, lookback
    )
    assert list(result.months) == ["2026-09", "2026-10"]
    september, october = result.months.values()
    assert september.energy == pytest.approx(1.0)
    assert october.energy == pytest.approx(2.0)
    # One hour of 30 €/month in each: 1 €/day, 96 quarter hours.
    assert september.totals["fixed"].base_cost == pytest.approx(4 / 96)
    assert october.totals["fixed"].base_cost == pytest.approx(30 / 31 * 4 / 96)
    assert result.totals["fixed"].base_cost == pytest.approx(
        september.totals["fixed"].base_cost + october.totals["fixed"].base_cost
    )


def test_month_bounds_over_year_end() -> None:
    bounds = list(month_bounds(utc(2026, 12, 31, 12), utc(2027, 1, 1, 12), BERLIN))
    assert [key for key, _, _ in bounds] == ["2026-12", "2027-01"]
    assert bounds[0][2] == utc(2026, 12, 31, 23)  # midnight CET
    assert bounds[1][1] - bounds[0][1] == timedelta(hours=11)
