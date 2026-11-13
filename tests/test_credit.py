"""Credit per year (e.g. Modul 1 under § 14a EnWG): spread like a yearly
base price with the opposite sign, also with price changes (no Home
Assistant)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.tarifwacht.const import (
    BERLIN,
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_CHANGES,
    CONF_CREDIT,
    CONF_FROM,
    CONF_KIND,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    KIND_DYNAMIC_TOTAL,
    KIND_FIXED,
)
from custom_components.tarifwacht.engine import Engine
from custom_components.tarifwacht.lookback import Lookback, hourly_costs, spread_hours
from custom_components.tarifwacht.meter import MeterTracker
from custom_components.tarifwacht.tariff_config import (
    stale_since,
    state_at,
    tariff_from_data,
)
from custom_components.tarifwacht.tariff_summary import (
    price_now_attributes,
    summary,
)
from custom_components.tarifwacht.tariffs import FixedPrice, Tariff
from custom_components.tarifwacht.timeslots import QUARTER

# Invented values: 120 € base price and 146 € credit per year.
FIXED = {
    CONF_KIND: KIND_FIXED,
    CONF_PRICE: 30.0,
    CONF_BASE_PRICE: 120.0,
    CONF_BASE_PERIOD: "year",
    CONF_CREDIT: 146.0,
}
DAY = timedelta(days=1)
# 1 March 2027, 00:00 CET (2027 has 365 days).
MARCH = datetime(2027, 2, 28, 23, tzinfo=UTC)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def tariff(data: dict) -> Tariff:
    return tariff_from_data(data, lambda _: FixedPrice(0.0))


def test_credit_spread_like_a_yearly_base_price() -> None:
    plain = tariff({**FIXED, CONF_CREDIT: 0})
    credited = tariff(FIXED)
    assert credited.credit == 146.0
    assert plain.credit == 0
    # One day: 120/365 base price less 146/365 credit, below zero.
    one_day = credited.base_between(MARCH, MARCH + DAY, BERLIN)
    assert one_day == pytest.approx((120 - 146) / 365)
    assert one_day < 0
    # A whole year adds up to exactly the yearly amounts.
    year = (
        datetime(2026, 12, 31, 23, tzinfo=UTC),
        datetime(2027, 12, 31, 23, tzinfo=UTC),
    )
    assert credited.base_between(*year, BERLIN) == pytest.approx(120 - 146)
    # Spread over every quarter hour of the day (DST day: 92 quarter hours).
    dst = datetime(2027, 3, 27, 23, tzinfo=UTC)  # 28 March 2027, 00:00 CET
    quarter = credited.base_between(dst, dst + QUARTER, BERLIN)
    assert quarter == pytest.approx((120 - 146) / 365 / 92)


def test_credit_with_a_monthly_base_price_and_without_any() -> None:
    monthly = tariff({**FIXED, CONF_BASE_PRICE: 31.0, CONF_BASE_PERIOD: "month"})
    one_day = monthly.base_between(utc(2027, 1, 9, 23), utc(2027, 1, 10, 23), BERLIN)
    assert one_day == pytest.approx(1.0 - 146 / 365)
    # A sensor tariff without a base price: only the credit.
    total = tariff(
        {
            CONF_KIND: KIND_DYNAMIC_TOTAL,
            CONF_PRICE_ENTITY: "sensor.total",
            CONF_CREDIT: 73.0,
        }
    )
    assert total.base_between(MARCH, MARCH + DAY, BERLIN) == pytest.approx(-0.2)


def test_credit_in_a_price_change() -> None:
    """A price change sets the credit from its date, like the base price;
    without the key the credit before carries on."""
    data = {
        **FIXED,
        CONF_CHANGES: [
            {CONF_FROM: "2027-03-01", CONF_PRICE: 31.0, CONF_CREDIT: 73.0},
            {CONF_FROM: "2027-06-01", CONF_PRICE: 32.0},
        ],
    }
    t = tariff(data)
    assert t.base_between(MARCH - DAY, MARCH, BERLIN) == pytest.approx(-26 / 365)
    assert t.base_between(MARCH, MARCH + DAY, BERLIN) == pytest.approx(47 / 365)
    assert state_at(data, date(2027, 6, 1))[CONF_CREDIT] == 73.0
    # Changed credit in a price change: stale from its date only.
    ended = {**data, CONF_CHANGES: [{**data[CONF_CHANGES][0], CONF_CREDIT: 0.0}]}
    assert stale_since(data, ended) == (True, MARCH)
    # The tariff's own credit: from the start.
    assert stale_since(FIXED, {**FIXED, CONF_CREDIT: 150.0}) == (True, None)


def test_engine_comparison_lookback_and_statistics_include_the_credit() -> None:
    started = utc(2027, 3, 10, 11)
    now = started + 2 * DAY
    engine = Engine(meter=MeterTracker(max_power_kw=100), tariffs={}, tz=BERLIN)
    engine.tariffs = {"plain": tariff({**FIXED, CONF_CREDIT: 0}), "m1": tariff(FIXED)}
    engine.start(started)
    engine.recompute(now)
    credit = 146 * (now - started) / DAY / 365
    plain, m1 = engine.totals["plain"], engine.totals["m1"]
    assert plain.base_cost - m1.base_cost == pytest.approx(credit)
    assert engine.compared_cost("plain") - engine.compared_cost("m1") == (
        pytest.approx(credit)
    )
    # Look-back before the setup and the hourly statistics rows: the same.
    hourly = [(utc(2027, 3, 9, 11) + i * timedelta(hours=1), 0.5) for i in range(24)]
    lookback = Lookback(
        consumption=spread_hours(hourly, utc(2027, 3, 9, 11), started),
        tariffs=engine.tariffs,
        until=started,
    )
    result = engine.costs_between(utc(2027, 3, 9, 11), started, now, lookback)
    assert result.totals["plain"].cost - result.totals["m1"].cost == pytest.approx(
        146 / 365
    )
    rows = hourly_costs(
        lookback.consumption.items(),
        engine.tariffs,
        utc(2027, 3, 9, 11),
        started,
        BERLIN,
    )
    difference = sum(rows.cost["plain"].values()) - sum(rows.cost["m1"].values())
    assert difference == pytest.approx(146 / 365)


def test_summary_and_price_now_attributes() -> None:
    data = {**FIXED, CONF_CHANGES: [{CONF_FROM: "2027-03-01", CONF_CREDIT: 160.0}]}
    german = summary(data, date(2027, 1, 5), german=True)
    assert "heute: 30 ct/kWh + 120,00 €/Jahr, Gutschrift 146,00 €/Jahr" in german
    assert "ab 01.03.2027: 30 ct/kWh + 120,00 €/Jahr, Gutschrift 160,00 €/Jahr" in (
        german
    )
    english = summary(data, date(2027, 1, 5), german=False)
    assert "credit 146.00 €/year" in english
    attributes = price_now_attributes(data, utc(2027, 1, 5, 12))
    assert attributes["yearly_credit_eur"] == 146.0
    assert attributes["next_change"]["yearly_credit_eur"] == 160.0
    # Without a credit anywhere: no attribute (unchanged for existing tariffs).
    plain = {k: v for k, v in FIXED.items() if k != CONF_CREDIT}
    assert "yearly_credit_eur" not in price_now_attributes(plain, utc(2027, 1, 5))
    assert "Gutschrift" not in summary(plain, date(2027, 1, 5), german=True)
