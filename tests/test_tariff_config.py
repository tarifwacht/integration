"""Tariff definitions from subentry data (no Home Assistant)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.tarifwacht.const import (
    BERLIN,
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_CHANGES,
    CONF_CURRENT,
    CONF_DYNAMIC_BASE,
    CONF_DYNAMIC_PRICE,
    CONF_FIXED_BASE,
    CONF_FIXED_PRICE,
    CONF_FROM,
    CONF_GRID_FEE,
    CONF_KEY,
    CONF_KIND,
    CONF_LEVIES,
    CONF_MARGIN,
    CONF_METER,
    CONF_NAME,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    CONF_VAT,
    KIND_DYNAMIC_MARKET,
    KIND_DYNAMIC_TOTAL,
    KIND_FIXED,
)
from custom_components.tarifwacht.prices import PriceTable
from custom_components.tarifwacht.tariff_config import (
    change_fields,
    default_titles,
    entry_data,
    initial_tariffs,
    price_entity,
    state_at,
    tariff_from_data,
    tariff_key,
)
from custom_components.tarifwacht.tariffs import BasePeriod

SLOT = datetime(2026, 10, 25, 16, tzinfo=UTC)


def tables() -> dict[str, PriceTable]:
    total, market = PriceTable(), PriceTable()
    total.set(SLOT, 0.31)
    market.set(SLOT, 0.05)
    return {"sensor.total": total, "sensor.market": market}


def test_fixed_price_in_ct() -> None:
    tariff = tariff_from_data(
        {CONF_KIND: KIND_FIXED, CONF_PRICE: 30.0, CONF_BASE_PRICE: 12.5}, tables().get
    )
    assert tariff.prices.get(SLOT) == pytest.approx(0.30)
    assert tariff.base_price == 12.5
    assert tariff.base_period is BasePeriod.MONTH


def test_total_price_sensor() -> None:
    available = tables()
    tariff = tariff_from_data(
        {
            CONF_KIND: KIND_DYNAMIC_TOTAL,
            CONF_PRICE_ENTITY: "sensor.total",
            CONF_BASE_PRICE: 120.0,
            CONF_BASE_PERIOD: "year",
        },
        available.__getitem__,
    )
    assert tariff.prices is available["sensor.total"]
    assert tariff.base_period is BasePeriod.YEAR


def test_exchange_price_plus_surcharges() -> None:
    data = {
        CONF_KIND: KIND_DYNAMIC_MARKET,
        CONF_PRICE_ENTITY: "sensor.market",
        CONF_GRID_FEE: 8.0,
        CONF_LEVIES: 4.0,
        CONF_MARGIN: 2.0,
        CONF_VAT: 19.0,
    }
    tariff = tariff_from_data(data, tables().__getitem__)
    # (0.05 + 0.14) * 1.19
    assert tariff.prices.get(SLOT) == pytest.approx(0.2261)
    assert price_entity(data) == "sensor.market"
    assert price_entity({CONF_KIND: KIND_FIXED, CONF_PRICE: 30.0}) is None


def test_unknown_kind() -> None:
    with pytest.raises(ValueError):
        tariff_from_data({CONF_KIND: "heat_pump"}, tables().__getitem__)


def test_initial_tariffs_keep_keys_of_0_1_0b1() -> None:
    config = {
        CONF_NAME: "Haus",
        CONF_METER: "sensor.meter",
        CONF_FIXED_PRICE: 30.0,
        CONF_FIXED_BASE: 31.0,
        CONF_DYNAMIC_PRICE: "sensor.total",
        CONF_DYNAMIC_BASE: 0,
    }
    (fixed_title, fixed), (dynamic_title, dynamic) = initial_tariffs(
        config, default_titles("de")
    )
    assert (fixed_title, dynamic_title) == ("Festpreis", "Dynamisch")
    assert fixed == {
        CONF_KEY: "fixed",
        CONF_KIND: KIND_FIXED,
        CONF_PRICE: 30.0,
        CONF_BASE_PRICE: 31.0,
        CONF_BASE_PERIOD: "month",
        CONF_CURRENT: True,
    }
    assert dynamic[CONF_KEY] == "dynamic"
    assert dynamic[CONF_PRICE_ENTITY] == "sensor.total"
    assert dynamic[CONF_CURRENT] is False
    assert tariff_key("01ABC", fixed) == "fixed"
    assert tariff_key("01ABC", {CONF_KIND: KIND_FIXED}) == "01ABC"
    assert entry_data(config) == {CONF_NAME: "Haus", CONF_METER: "sensor.meter"}
    assert default_titles("en") == ("Fixed price", "Dynamic")


# --- price changes ------------------------------------------------------------------

NEW_YEAR = datetime(2026, 12, 31, 23, tzinfo=UTC)  # 1 January 2027, 00:00 CET


def test_fixed_price_change_at_local_midnight() -> None:
    data = {
        CONF_KIND: KIND_FIXED,
        CONF_PRICE: 30.0,
        CONF_BASE_PRICE: 31.0,
        CONF_BASE_PERIOD: "month",
        CONF_CHANGES: [
            {CONF_FROM: "2027-01-01", CONF_PRICE: 32.0, CONF_BASE_PRICE: 62.0}
        ],
    }
    tariff = tariff_from_data(data, tables().__getitem__)
    assert tariff.price(NEW_YEAR - timedelta(minutes=15)) == pytest.approx(0.30)
    assert tariff.price(NEW_YEAR) == pytest.approx(0.32)
    # Base price: 31 December at 31 €/month (1 €/day), 1 January at 62 €/month.
    day = timedelta(days=1)
    assert tariff.base_between(NEW_YEAR - day, NEW_YEAR + day, BERLIN) == pytest.approx(
        1.0 + 2.0
    )
    assert state_at(data, date(2027, 1, 1))[CONF_PRICE] == 32.0
    assert state_at(data, date(2026, 12, 31))[CONF_PRICE] == 30.0


def test_market_tariff_grid_fee_change() -> None:
    data = {
        CONF_KIND: KIND_DYNAMIC_MARKET,
        CONF_PRICE_ENTITY: "sensor.market",
        CONF_GRID_FEE: 8.0,
        CONF_LEVIES: 4.0,
        CONF_MARGIN: 2.0,
        CONF_VAT: 19.0,
        CONF_CHANGES: [
            {CONF_FROM: "2026-10-26", CONF_GRID_FEE: 10.0},
            {CONF_FROM: "2026-10-25", CONF_MARGIN: 3.0},
        ],
    }
    tariff = tariff_from_data(data, tables().__getitem__)
    # 25.10.: margin 3 ct (grid fee still 8): (0.05 + 0.15) * 1.19
    assert tariff.price(SLOT) == pytest.approx(0.238)
    # Changes are applied in date order and accumulate.
    assert tariff.at(datetime(2026, 10, 26, 12, tzinfo=UTC)).prices.surcharge == (
        pytest.approx(0.17)
    )
    assert change_fields(KIND_DYNAMIC_MARKET) == (
        CONF_GRID_FEE,
        CONF_LEVIES,
        CONF_MARGIN,
        CONF_VAT,
        "modul3",
        CONF_BASE_PRICE,
        CONF_BASE_PERIOD,
    )
    assert change_fields(KIND_DYNAMIC_TOTAL) == (CONF_BASE_PRICE, CONF_BASE_PERIOD)
