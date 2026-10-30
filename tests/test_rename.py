"""Renamed source entities: entry data, tariffs and stored state follow."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.tarifwacht.const import (
    BERLIN,
    CONF_KIND,
    CONF_METER,
    CONF_NAME,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    CONF_RENAMED,
    KIND_DYNAMIC_MARKET,
    KIND_DYNAMIC_TOTAL,
    KIND_FIXED,
)
from custom_components.tarifwacht.engine import Engine
from custom_components.tarifwacht.meter import MeterTracker
from custom_components.tarifwacht.prices import ParsedPrices
from custom_components.tarifwacht.rename import (
    renamed_data,
    renamed_storage,
    renamed_tariff,
    renamed_unique_id,
    sources,
)
from custom_components.tarifwacht.tariff_config import tariff_from_data

METER = "sensor.grid_import"
TOTAL = "sensor.epex_total"
MARKET = "sensor.epex_market"
DAY = [None] * 96

FIXED = {CONF_KIND: KIND_FIXED, CONF_PRICE: 30.0}
DYNAMIC = {CONF_KIND: KIND_DYNAMIC_TOTAL, CONF_PRICE_ENTITY: TOTAL}
EXCHANGE = {CONF_KIND: KIND_DYNAMIC_MARKET, CONF_PRICE_ENTITY: MARKET}


def day(**values: float) -> list[float | None]:
    """A UTC day of prices; keyword `q<index>` sets one quarter hour."""
    result: list[float | None] = list(DAY)
    for key, value in values.items():
        result[int(key[1:])] = value
    return result


def test_sources() -> None:
    data = {CONF_NAME: "Haus", CONF_METER: METER}
    assert sources(data, [FIXED, DYNAMIC, EXCHANGE]) == {METER, TOTAL, MARKET}
    # A fixed price keeps no sensor, even if one was left in its data.
    assert sources(data, [{**FIXED, CONF_PRICE_ENTITY: TOTAL}]) == {METER}


def test_meter_renamed() -> None:
    data = {CONF_NAME: "Haus", CONF_METER: METER}
    assert renamed_data(data, METER, "sensor.smart_meter") == {
        CONF_NAME: "Haus",
        CONF_METER: "sensor.smart_meter",
        CONF_RENAMED: {METER: "sensor.smart_meter"},
    }
    assert renamed_unique_id(METER, METER, "sensor.smart_meter") == (
        "sensor.smart_meter"
    )
    assert renamed_unique_id(None, METER, "sensor.smart_meter") is None


def test_price_sensor_renamed() -> None:
    data = {CONF_NAME: "Haus", CONF_METER: METER}
    assert renamed_data(data, TOTAL, "sensor.price") == {
        **data,
        CONF_RENAMED: {TOTAL: "sensor.price"},
    }
    assert renamed_tariff(DYNAMIC, TOTAL, "sensor.price") == {
        **DYNAMIC,
        CONF_PRICE_ENTITY: "sensor.price",
    }
    assert renamed_tariff(EXCHANGE, TOTAL, "sensor.price") is None
    assert renamed_tariff(FIXED, TOTAL, "sensor.price") is None


def test_chain_and_back() -> None:
    """A -> B -> C before the next start moves A's state to C; back to A
    leaves nothing to move."""
    data = {CONF_NAME: "Haus", CONF_METER: METER}
    once = renamed_data(data, TOTAL, "sensor.b")
    twice = renamed_data(once, "sensor.b", "sensor.c")
    assert twice[CONF_RENAMED] == {TOTAL: "sensor.c", "sensor.b": "sensor.c"}
    back = renamed_data(once, "sensor.b", TOTAL)
    assert back[CONF_RENAMED] == {"sensor.b": TOTAL}


def test_swapped_ids() -> None:
    """Two price sensors swap their ids via a temporary one."""
    data = {CONF_NAME: "Haus", CONF_METER: METER}
    data = renamed_data(data, TOTAL, "sensor.tmp")
    data = renamed_data(data, MARKET, TOTAL)
    data = renamed_data(data, "sensor.tmp", MARKET)
    renames = data[CONF_RENAMED]
    assert renames[TOTAL] == MARKET
    assert renames[MARKET] == TOTAL
    stored = {"prices": {TOTAL: {"2026-10-25": day(q0=0.3)}, MARKET: {}}}
    moved = renamed_storage(stored, renames)
    assert moved["prices"] == {MARKET: {"2026-10-25": day(q0=0.3)}, TOTAL: {}}


def test_storage_moves_prices_and_meter() -> None:
    stored = {
        "meter": {"last_value": 1000.0, "last_time": None, "source": METER},
        "prices": {TOTAL: {"2026-10-25": day(q1=0.25)}},
        "started": "2026-10-25T16:00:00+00:00",
    }
    renames = {TOTAL: "sensor.price", METER: "sensor.smart_meter"}
    moved = renamed_storage(stored, renames)
    assert moved["prices"] == {"sensor.price": {"2026-10-25": day(q1=0.25)}}
    assert moved["meter"]["source"] == "sensor.smart_meter"
    assert moved["meter"]["last_value"] == 1000.0
    assert moved["started"] == stored["started"]
    # The stored data itself is left as it is.
    assert TOTAL in stored["prices"]
    assert renamed_storage(stored, {}) is stored
    # An archive has no meter.
    archive = {"consumption": {}, "prices": {TOTAL: {}}}
    assert renamed_storage(archive, renames)["prices"] == {"sensor.price": {}}


def test_storage_merges_into_existing_table() -> None:
    """The table under the new id keeps its prices; the renamed one fills gaps."""
    stored = {
        "prices": {
            TOTAL: {"2026-10-24": day(q0=0.1), "2026-10-25": day(q0=0.2, q1=0.3)},
            "sensor.price": {"2026-10-25": day(q0=0.9)},
        }
    }
    moved = renamed_storage(stored, {TOTAL: "sensor.price"})
    assert moved["prices"] == {
        "sensor.price": {
            "2026-10-25": day(q0=0.9, q1=0.3),
            "2026-10-24": day(q0=0.1),
        }
    }


def test_restored_engine_reads_prices_under_new_id() -> None:
    """End to end in the core: a tariff of the renamed sensor finds the
    prices booked under the old id, and the meter keeps its baseline."""
    slot = datetime(2026, 10, 25, 16, 0, tzinfo=UTC)
    old = Engine(
        meter=MeterTracker(max_power_kw=100.0, source=METER), tariffs={}, tz=BERLIN
    )
    old.on_prices(TOTAL, ParsedPrices(prices={slot: 0.25}, format="test"), slot)
    old.on_meter(1000.0, slot, slot)
    renames = {TOTAL: "sensor.price", METER: "sensor.smart_meter"}

    new = Engine(
        meter=MeterTracker(max_power_kw=100.0, source="sensor.smart_meter"),
        tariffs={},
        tz=BERLIN,
    )
    data = {**DYNAMIC, CONF_PRICE_ENTITY: "sensor.price"}
    new.tariffs["dynamic"] = tariff_from_data(data, new.price_table)
    new.restore(dict(renamed_storage(old.as_dict(), renames)))
    assert new.tariffs["dynamic"].price(slot) == 0.25
    assert new.meter.last_value == 1000.0
