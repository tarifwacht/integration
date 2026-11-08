"""One-off bonus of a tariff: booked once at local midnight of its date."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.tarifwacht.button import tariff_settings
from custom_components.tarifwacht.config_flow import _tariff_data, bonus_error
from custom_components.tarifwacht.const import (
    BERLIN,
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_BONUS,
    CONF_BONUS_DATE,
    CONF_CHANGES,
    CONF_CURRENT,
    CONF_FROM,
    CONF_KIND,
    CONF_NAME,
    CONF_PRICE,
    KIND_FIXED,
    SECTION_BONUS,
)
from custom_components.tarifwacht.engine import Engine
from custom_components.tarifwacht.lookback import FIVE_MINUTES, HOUR, period_costs
from custom_components.tarifwacht.meter import MeterTracker
from custom_components.tarifwacht.tariff_config import bonus_of, tariff_from_data
from custom_components.tarifwacht.tariffs import FixedPrice, Tariff
from custom_components.tarifwacht.timeslots import QUARTER


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# 1 February 2027, 00:00 CET.
BONUS_AT = utc(2027, 1, 31, 23)
FIXED_DATA = {
    CONF_KIND: KIND_FIXED,
    CONF_PRICE: 30.0,
    CONF_BASE_PRICE: 10.0,
    CONF_BASE_PERIOD: "month",
    CONF_BONUS: 250.0,
    CONF_BONUS_DATE: "2027-02-01",
}


def no_tables(entity: str) -> FixedPrice:
    raise AssertionError(entity)


def engine_with_bonus(started: datetime) -> Engine:
    engine = Engine(meter=MeterTracker(max_power_kw=100), tariffs={}, tz=BERLIN)
    engine.tariffs = {
        "bonus": tariff_from_data(FIXED_DATA, no_tables),
        "plain": Tariff(FixedPrice(0.30), 10.0),
    }
    engine.start(started)
    return engine


def test_bonus_at_local_midnight_of_its_date() -> None:
    assert bonus_of(FIXED_DATA) == (250.0, BONUS_AT)
    assert bonus_of({**FIXED_DATA, CONF_BONUS: 0}) == (0.0, None)
    assert bonus_of({k: v for k, v in FIXED_DATA.items() if k != CONF_BONUS_DATE}) == (
        0.0,
        None,
    )
    # Summer time: 1 July 00:00 CEST.
    summer = bonus_of({**FIXED_DATA, CONF_BONUS_DATE: "2027-07-01"})
    assert summer == (250.0, utc(2027, 6, 30, 22))


def test_the_bonus_belongs_to_the_tariff_not_to_a_price_state() -> None:
    data = {
        **FIXED_DATA,
        CONF_CHANGES: [{CONF_FROM: "2027-01-15", CONF_PRICE: 32.0}],
    }
    tariff = tariff_from_data(data, no_tables)
    assert tariff.bonus == 250.0 and tariff.bonus_at == BONUS_AT
    assert tariff.price(BONUS_AT) == pytest.approx(0.32)
    assert tariff.bonus_between(BONUS_AT, BONUS_AT + QUARTER) == 250.0
    assert tariff.bonus_between(BONUS_AT - QUARTER, BONUS_AT) == 0.0
    # Base price and bonus are separate.
    assert tariff.base_between(BONUS_AT, BONUS_AT + QUARTER, BERLIN) > 0


def test_running_totals_credit_the_bonus_once_its_quarter_hour_ended() -> None:
    engine = engine_with_bonus(utc(2027, 1, 20))
    engine.tick(BONUS_AT)
    assert engine.totals["bonus"].bonus == 0.0
    engine.tick(BONUS_AT + QUARTER)
    totals, plain = engine.totals["bonus"], engine.totals["plain"]
    assert totals.bonus == 250.0
    assert totals.base_cost == pytest.approx(plain.base_cost)
    assert totals.cost == pytest.approx(plain.cost - 250.0)
    # The consumption cost stays as it is.
    assert totals.consumption_cost == plain.consumption_cost
    # Only once, also when recomputed or ticked again later.
    engine.tick(BONUS_AT + timedelta(days=3))
    engine.recompute(BONUS_AT + timedelta(days=3))
    assert engine.totals["bonus"].bonus == 250.0
    # The comparison (differences, cheapest tariff) includes it.
    assert engine.compared_cost("bonus") == pytest.approx(
        engine.compared_cost("plain") - 250.0
    )


def test_a_bonus_before_the_period_does_not_count() -> None:
    engine = engine_with_bonus(BONUS_AT + timedelta(days=1))
    engine.tick(BONUS_AT + timedelta(days=5))
    assert engine.totals["bonus"].bonus == 0.0


def test_a_future_bonus_counts_when_reached() -> None:
    engine = engine_with_bonus(utc(2027, 1, 1))
    engine.tick(BONUS_AT - timedelta(hours=1))
    assert engine.totals["bonus"].bonus == 0.0
    engine.tick(BONUS_AT + timedelta(hours=1))
    assert engine.totals["bonus"].bonus == 250.0


def test_compare_counts_the_bonus_in_its_month() -> None:
    engine = engine_with_bonus(utc(2027, 1, 1))
    now = utc(2027, 3, 1)
    engine.tick(now)
    costs = engine.costs_between(utc(2027, 1, 1), now, now)
    assert costs.totals["bonus"].bonus == 250.0
    assert costs.months["2027-01"].totals["bonus"].bonus == 0.0
    assert costs.months["2027-02"].totals["bonus"].bonus == 250.0
    february = costs.months["2027-02"].totals
    assert february["bonus"].cost == pytest.approx(february["plain"].cost - 250.0)
    # A period without the date: no bonus.
    january = engine.costs_between(utc(2027, 1, 1), BONUS_AT, now)
    assert january.totals["bonus"].bonus == 0.0


def test_hourly_statistics_carry_the_bonus_in_its_hour() -> None:
    tariffs = {"bonus": tariff_from_data(FIXED_DATA, no_tables)}
    start, end = BONUS_AT - 2 * HOUR, BONUS_AT + 2 * HOUR
    quarters = [(start + i * QUARTER, 0.25) for i in range(16)]
    hourly = period_costs(quarters, tariffs, start, end, BERLIN)
    base = tariffs["bonus"].base_between(BONUS_AT, BONUS_AT + HOUR, BERLIN)
    assert hourly.cost["bonus"][BONUS_AT] == pytest.approx(0.3 + base - 250.0)
    assert hourly.consumption_cost["bonus"][BONUS_AT] == pytest.approx(0.3)
    others = [v for h, v in hourly.cost["bonus"].items() if h != BONUS_AT]
    assert all(v > 0 for v in others)
    # Short-term rows: in the five minutes from midnight on.
    five = period_costs(quarters, tariffs, start, end, BERLIN, FIVE_MINUTES)
    negative = [p for p, v in five.cost["bonus"].items() if v < 0]
    assert negative == [BONUS_AT]
    # Summed up the same.
    assert sum(five.cost["bonus"].values()) == pytest.approx(
        sum(hourly.cost["bonus"].values())
    )


def form(**bonus: object) -> dict[str, object]:
    return {
        CONF_NAME: "Neu",
        CONF_PRICE: 30.0,
        CONF_BASE_PERIOD: "month",
        CONF_CURRENT: False,
        SECTION_BONUS: bonus,
    }


def test_form_stores_a_bonus_only_with_a_date() -> None:
    data = _tariff_data(KIND_FIXED, form(bonus=250, bonus_date="2027-02-01"))
    assert data[CONF_BONUS] == 250.0 and data[CONF_BONUS_DATE] == "2027-02-01"
    assert bonus_error(form(bonus=250)) == "bonus_date_required"
    assert bonus_error(form(bonus=250, bonus_date="2027-02-01")) is None
    # A date without an amount (or an emptied amount) is no bonus.
    assert CONF_BONUS not in _tariff_data(KIND_FIXED, form(bonus_date="2027-02-01"))
    assert bonus_error(form(bonus_date="2027-02-01")) is None
    assert CONF_BONUS not in _tariff_data(KIND_FIXED, form())


def test_issue_report_lists_the_bonus() -> None:
    ((label, line),) = tariff_settings([FIXED_DATA])
    assert label == "tariff 1"
    assert line.endswith("bonus 250 EUR on 2027-02-01")
