"""Payback of PV and battery (payback.py); made-up amounts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from custom_components.tarifwacht.const import BERLIN
from custom_components.tarifwacht.payback import (
    Purchase,
    merge_days,
    payback,
    payback_attributes,
    purchase_status,
    purchases,
)
from custom_components.tarifwacht.solar import HourFlows, SolarSettings, solar_totals
from custom_components.tarifwacht.tariffs import FixedPrice, Tariff

DAY = timedelta(days=1)


def days(first: date, count: int, value: float) -> dict[date, float]:
    return {first + i * DAY: value for i in range(count)}


def test_forecast_from_a_full_year() -> None:
    """Two years of 2 EUR a day: 1,460 of 5,000 EUR, 3,540 left at 2 a day."""
    today = date(2026, 11, 8)
    since = today - 730 * DAY
    result = payback(Purchase(5000.0, since), days(since, 730, 2.0), today)
    assert result.saved == 1460.0
    assert result.remaining == 3540.0
    assert not result.paid_back
    assert result.per_day == 2.0
    assert not result.forecast_rough
    assert result.forecast == today + 1770 * DAY
    assert result.counted_since == since


def test_average_over_the_last_year_only() -> None:
    """The year before counts for the saving, not for the average."""
    today = date(2026, 11, 8)
    since = today - 730 * DAY
    daily = days(since, 365, 1.0) | days(today - 365 * DAY, 365, 3.0)
    result = payback(Purchase(10000.0, since), daily, today)
    assert result.saved == 365.0 + 1095.0
    assert result.per_day == 3.0


def test_short_history_gives_a_rough_forecast() -> None:
    today = date(2026, 11, 8)
    since = today - 30 * DAY
    result = payback(Purchase(1000.0, since), days(since, 31, 1.0), today)
    # 30 complete days averaged (today is not complete), today counts saved.
    assert result.per_day == 1.0
    assert result.saved == 31.0
    assert result.forecast_rough
    assert result.forecast == today + 969 * DAY


def test_no_forecast_with_too_few_days_or_no_saving() -> None:
    today = date(2026, 11, 8)
    few = payback(
        Purchase(1000.0, today - 3 * DAY), days(today - 3 * DAY, 4, 5.0), today
    )
    assert few.per_day is None and few.forecast is None
    since = today - 100 * DAY
    none = payback(Purchase(1000.0, since), days(since, 100, -0.1), today)
    assert none.per_day is not None and none.per_day < 0
    assert none.forecast is None


def test_paid_back_on_the_day_the_sum_reaches_the_cost() -> None:
    today = date(2026, 11, 8)
    since = date(2026, 1, 1)
    result = payback(Purchase(100.0, since), days(since, 300, 1.0), today)
    assert result.paid_back
    assert result.paid_back_on == since + 99 * DAY
    assert result.remaining == 0.0
    assert result.forecast is None


def test_days_before_commissioning_do_not_count() -> None:
    """A battery added later: the PV's earlier days are not its savings."""
    today = date(2026, 11, 8)
    since = date(2026, 6, 1)
    daily = days(date(2026, 1, 1), 312, 1.0)
    result = payback(Purchase(500.0, since), daily, today)
    assert result.counted_since == since
    assert result.saved == (today - since).days + 1


def test_counted_later_than_commissioning() -> None:
    """Statistics only since the setup: counted from there."""
    today = date(2026, 11, 8)
    result = payback(
        Purchase(5000.0, date(2020, 5, 1)), days(date(2026, 10, 1), 39, 2.0), today
    )
    assert result.counted_since == date(2026, 10, 1)
    assert result.forecast_rough
    attributes = payback_attributes(result)
    assert attributes["counted_since"] == "2026-10-01"
    assert attributes["commissioned_on"] == "2020-05-01"
    assert attributes["purchase_cost_eur"] == 5000.0
    assert attributes["paid_back"] is False
    assert payback_attributes(None) == {}


def test_merge_days() -> None:
    a = {date(2026, 1, 1): 1.0, date(2026, 1, 2): 2.0}
    b = {date(2026, 1, 2): 0.5}
    assert merge_days(a, b) == {date(2026, 1, 1): 1.0, date(2026, 1, 2): 2.5}


def test_purchases_from_the_subentry() -> None:
    meters = {"charged_entity": "sensor.c", "discharged_entity": "sensor.d"}
    found = purchases(
        {"pv_cost": 9000, "pv_since": "2023-04-01", "battery_cost": 4500, **meters}
    )
    # The battery without its own date counts from the PV's.
    assert found["pv"] == Purchase(9000.0, date(2023, 4, 1))
    assert found["battery"] == Purchase(4500.0, date(2023, 4, 1))
    later = purchases(
        {
            "pv_cost": 9000,
            "pv_since": "2023-04-01",
            "battery_cost": 4500,
            "battery_since": "2025-03-15",
            **meters,
        }
    )
    assert later["battery"].since == date(2025, 3, 15)
    # No battery meters, no cost, or no date: nothing.
    assert "battery" not in purchases({"battery_cost": 4500, "pv_since": "2023-04-01"})
    assert purchases({"pv_since": "2023-04-01"}) == {}
    assert purchases({"pv_cost": 9000}) == {}
    assert (
        purchase_status(
            {"pv_cost": 9000, "pv_since": "2023-04-01", "battery_cost": 1, **meters}
        )
        == "pv cost set, battery cost set"
    )
    assert purchase_status({}) == "none"
    assert purchase_status(None) == "none"


def test_solar_totals_per_day() -> None:
    """The saving per local day adds up to the totals."""
    noon = datetime(2026, 6, 1, 10, tzinfo=UTC)
    hours = {
        noon: HourFlows(pv=3.0, charged=2.0),
        noon + timedelta(hours=8): HourFlows(purchase=0.2, discharged=1.8),
        noon + timedelta(days=1): HourFlows(pv=2.0, feed_in=1.0),
    }
    tariffs = {"fixed": Tariff(FixedPrice(0.30))}
    settings = SolarSettings(same_inverter=False, feed_in_rate=0.08)
    result = solar_totals(hours, tariffs, settings, BERLIN, daily=True)
    per_day = result.days["fixed"]
    assert set(per_day) == {date(2026, 6, 1), date(2026, 6, 2)}
    total = result.totals["fixed"]
    assert round(sum(v[0] for v in per_day.values()), 6) == round(total.saving_pv, 6)
    assert round(sum(v[1] for v in per_day.values()), 6) == round(
        total.saving_battery, 6
    )
    assert solar_totals(hours, tariffs, settings, BERLIN).days == {}
