"""Saving by PV and battery (no Home Assistant). Made-up values only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.tarifwacht.const import BERLIN
from custom_components.tarifwacht.solar import (
    HourFlows,
    SolarSettings,
    detect_same_inverter,
    solar_totals,
)
from custom_components.tarifwacht.tariffs import FixedPrice, Tariff
from custom_components.tarifwacht.timeslots import QUARTER

HOUR = timedelta(hours=1)
NOON = datetime(2026, 6, 1, 10, tzinfo=UTC)  # 12:00 local
FIXED = Tariff(FixedPrice(0.30))


class Prices:
    """Quarter-hour prices from a dict, None elsewhere."""

    def __init__(self, prices: dict[datetime, float]) -> None:
        self.prices = prices

    def get(self, slot: datetime) -> float | None:
        return self.prices.get(slot)


def quarters(hour: datetime, *values: float) -> dict[datetime, float]:
    return {hour + i * QUARTER: v for i, v in enumerate(values)}


AC = SolarSettings(same_inverter=False, feed_in_rate=0.08)


def test_no_pv_no_saving() -> None:
    hours = {NOON: HourFlows(purchase=2.0)}
    totals = solar_totals(hours, {"fix": FIXED}, AC, BERLIN).totals["fix"]
    assert totals.without == pytest.approx(0.60)
    assert totals.actual == pytest.approx(0.60)
    assert totals.saving == pytest.approx(0.0)


def test_pv_only_saves_consumption_and_earns_feed_in() -> None:
    """3 kWh PV, 1 kWh consumption: 1 kWh saved at 30 ct, 2 kWh fed in at 8 ct."""
    hours = {NOON: HourFlows(feed_in=2.0, pv=3.0)}
    totals = solar_totals(hours, {"fix": FIXED}, AC, BERLIN).totals["fix"]
    assert totals.consumption == pytest.approx(1.0)
    assert totals.without == pytest.approx(0.30)
    assert totals.actual == pytest.approx(-0.16)
    assert totals.saving_pv == pytest.approx(0.46)
    assert totals.saving_battery == pytest.approx(0.0)


def test_ac_battery_shifts_pv_into_the_evening() -> None:
    """Noon: PV 3 kWh, consumption 1, battery takes 2. Evening: battery gives
    1.8 kWh (90 %), consumption 2, 0.2 from the grid."""
    evening = NOON + 8 * HOUR
    hours = {
        NOON: HourFlows(pv=3.0, charged=2.0),
        evening: HourFlows(purchase=0.2, discharged=1.8),
    }
    totals = solar_totals(hours, {"fix": FIXED}, AC, BERLIN).totals["fix"]
    assert totals.consumption == pytest.approx(3.0)
    assert totals.without == pytest.approx(0.90)
    # Without battery: noon 2 kWh fed in (16 ct), evening 2 kWh bought (60 ct).
    assert totals.pv_only == pytest.approx(0.60 - 0.16)
    assert totals.actual == pytest.approx(0.06)
    assert totals.saving_battery == pytest.approx(0.44 - 0.06)
    assert totals.battery_value == pytest.approx((0.44 - 0.06) / 1.8)


def test_hybrid_inverter_counts_battery_on_its_ac_meter() -> None:
    """Same flows behind a hybrid inverter: its AC meter shows noon 1 kWh
    (3 PV - 2 into the battery, efficiency ignored here) and evening 1.8."""
    settings = SolarSettings(same_inverter=True, feed_in_rate=0.08, efficiency=1.0)
    evening = NOON + 8 * HOUR
    hours = {
        NOON: HourFlows(pv=1.0, charged=2.0),
        evening: HourFlows(purchase=0.2, pv=1.8, discharged=1.8),
    }
    totals = solar_totals(hours, {"fix": FIXED}, settings, BERLIN).totals["fix"]
    assert totals.consumption == pytest.approx(3.0)
    assert totals.pv == pytest.approx(3.0)
    assert totals.saving_battery == pytest.approx(0.38)


def test_negative_prices_pay_no_feed_in() -> None:
    """Two of four quarter hours negative: half the feed-in is unpaid."""
    settings = SolarSettings(
        same_inverter=False, feed_in_rate=0.08, negative_unpaid=True
    )
    market = Prices(quarters(NOON, -0.01, -0.02, 0.0, 0.01))
    hours = {NOON: HourFlows(feed_in=2.0, pv=2.0)}
    totals = solar_totals(hours, {"fix": FIXED}, settings, BERLIN, market).totals["fix"]
    assert totals.feed_in_unpaid == pytest.approx(1.0)
    assert totals.actual == pytest.approx(-0.08)


def test_hour_without_a_price_is_left_out() -> None:
    dynamic = Tariff(Prices(quarters(NOON, 0.2, 0.2, 0.2, 0.2)))
    hours = {NOON: HourFlows(purchase=1.0), NOON + HOUR: HourFlows(purchase=1.0)}
    totals = solar_totals(hours, {"dyn": dynamic}, AC, BERLIN).totals["dyn"]
    assert totals.hours == 1
    assert totals.hours_left_out == 1
    assert totals.without == pytest.approx(0.2)


def test_market_missing_leaves_the_hour_out_under_section_51() -> None:
    settings = SolarSettings(
        same_inverter=False, feed_in_rate=0.08, negative_unpaid=True
    )
    hours = {NOON: HourFlows(feed_in=1.0, pv=1.0)}
    totals = solar_totals(hours, {"fix": FIXED}, settings, BERLIN, None).totals["fix"]
    assert totals.hours == 0
    assert totals.hours_left_out == 1


def test_months_are_local() -> None:
    """The hour 22:00 UTC on 31 May is 1 June in Berlin."""
    hours = {datetime(2026, 5, 31, 22, tzinfo=UTC): HourFlows(purchase=1.0)}
    result = solar_totals(hours, {"fix": FIXED}, AC, BERLIN)
    assert list(result.months) == ["2026-06"]


def test_detect_same_inverter() -> None:
    nights = [NOON + 12 * HOUR + timedelta(days=d) for d in range(12)]
    hybrid = {h: HourFlows(pv=0.95, discharged=1.0) for h in nights}
    separate = {h: HourFlows(discharged=1.0) for h in nights}
    assert detect_same_inverter(hybrid) is True
    assert detect_same_inverter(separate) is False
    assert detect_same_inverter(dict(list(hybrid.items())[:3])) is None
