"""Booking core: time slots, meter, prices, quarter-hour history (no Home Assistant)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.tarifwacht.history import SlotSeries
from custom_components.tarifwacht.meter import MeterEvent, MeterTracker, to_kwh
from custom_components.tarifwacht.prices import (
    PriceTable,
    attribute_shape,
    parse_interval_prices,
    parse_price_attributes,
    parse_start_prices,
    prices_from_states,
)
from custom_components.tarifwacht.timeslots import (
    QUARTER,
    slot_start,
    split_interval,
)
from tests.conftest import load_fixture

GRID_KW = 24  # 3 x 35 A house connection


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def fixture_prices() -> PriceTable:
    fixture = load_fixture("epex_spot_2026-10-25.json")
    table = PriceTable()
    for entries in (fixture["history_supplement"], fixture["attributes"]["data"]):
        table.merge(parse_interval_prices(entries).prices)
    return table


# --- time slots ---------------------------------------------------------------


def test_slot_start_floors_in_utc() -> None:
    local = datetime.fromisoformat("2026-10-25T02:59:59+01:00")
    assert slot_start(local) == utc(2026, 10, 25, 1, 45)
    with pytest.raises(ValueError):
        slot_start(datetime(2026, 1, 1))  # noqa: DTZ001


def test_split_interval_is_proportional() -> None:
    pieces = split_interval(utc(2026, 1, 1, 9, 10), utc(2026, 1, 1, 9, 20), 0.004)
    assert pieces == [
        (utc(2026, 1, 1, 9, 0), pytest.approx(0.002)),
        (utc(2026, 1, 1, 9, 15), pytest.approx(0.002)),
    ]


def test_split_interval_over_gap_keeps_sum() -> None:
    pieces = split_interval(utc(2026, 1, 1, 8, 7), utc(2026, 1, 1, 11, 2), 3.0)
    assert len(pieces) == 13  # 08:00 ... 11:00
    assert sum(e for _, e in pieces) == pytest.approx(3.0)
    assert pieces[0][0] == utc(2026, 1, 1, 8, 0)
    assert pieces[-1][0] == utc(2026, 1, 1, 11, 0)


def test_split_interval_empty() -> None:
    at = utc(2026, 1, 1, 9, 0)
    assert split_interval(at, at, 0.5) == [(at, 0.5)]


# --- meter --------------------------------------------------------------------


def test_units() -> None:
    assert to_kwh(1234567.0, "Wh") == pytest.approx(1234.567)
    assert to_kwh(1.5, "kWh") == 1.5
    with pytest.raises(KeyError):
        to_kwh(1.0, "W")


def test_meter_first_reading_is_baseline() -> None:
    meter = MeterTracker(max_power_kw=GRID_KW)
    update = meter.update(100.0, utc(2026, 1, 1, 9))
    assert update.event is MeterEvent.FIRST
    assert update.pieces == []


def test_meter_reset_and_jump_are_not_booked() -> None:
    meter = MeterTracker(max_power_kw=GRID_KW)
    meter.update(1234.567, utc(2026, 1, 1, 9, 0))
    # A meter interface that restarts reports 0, then the real counter again.
    reset = meter.update(0.0, utc(2026, 1, 1, 9, 1))
    jump = meter.update(1234.568, utc(2026, 1, 1, 9, 2))
    assert reset.event is MeterEvent.RESET and reset.pieces == []
    assert jump.event is MeterEvent.JUMP and jump.pieces == []
    # Normal operation continues from the new baseline.
    normal = meter.update(1234.578, utc(2026, 1, 1, 9, 3))
    assert normal.event is None
    assert sum(e for _, e in normal.pieces) == pytest.approx(0.010)


def test_meter_allows_full_power_and_whole_wh_steps() -> None:
    meter = MeterTracker(max_power_kw=GRID_KW)
    meter.update(0.0, utc(2026, 1, 1, 18, 0, 0))
    # Full house connection for one hour (sauna, wallbox and cooking at once).
    assert meter.update(24.0, utc(2026, 1, 1, 19, 0, 0)).event is None
    # 1 Wh one second later (rounding of the counter).
    assert meter.update(24.001, utc(2026, 1, 1, 19, 0, 1)).event is None


def test_meter_ignores_out_of_order_readings() -> None:
    meter = MeterTracker(max_power_kw=GRID_KW)
    meter.update(1.0, utc(2026, 1, 1, 9, 5))
    assert meter.update(0.5, utc(2026, 1, 1, 9, 0)).pieces == []
    assert meter.last_value == 1.0


def test_meter_round_trip() -> None:
    meter = MeterTracker(max_power_kw=GRID_KW)
    meter.update(1.0, utc(2026, 1, 1, 9, 5))
    restored = MeterTracker(max_power_kw=GRID_KW)
    restored.restore(meter.as_dict())
    assert restored == meter
    named = MeterTracker(max_power_kw=GRID_KW, source="sensor.grid_import")
    named.update(1.0, utc(2026, 1, 1, 9, 5))
    restored = MeterTracker(max_power_kw=GRID_KW, source="sensor.grid_import")
    restored.restore(named.as_dict())
    assert restored == named


def test_swapped_meter_starts_with_a_new_baseline() -> None:
    """Meter swapped in the reconfiguration: the old reading is no baseline."""
    old = MeterTracker(max_power_kw=GRID_KW, source="sensor.old")
    old.update(5000.0, utc(2026, 1, 1, 9))
    new = MeterTracker(max_power_kw=GRID_KW, source="sensor.new")
    new.restore(old.as_dict())
    assert new.last_value is None
    first = new.update(12.0, utc(2026, 1, 1, 9, 10))
    assert first.event is MeterEvent.FIRST
    assert first.pieces == []
    assert new.as_dict()["source"] == "sensor.new"
    # Stored before the meter was named: taken over as before.
    legacy = MeterTracker(max_power_kw=GRID_KW, source="sensor.new")
    legacy.restore({"last_value": 11.0, "last_time": "2026-01-01T09:00:00+00:00"})
    assert legacy.update(12.0, utc(2026, 1, 1, 9, 10)).delta == pytest.approx(1.0)


# --- prices -------------------------------------------------------------------


def test_parse_epex_fixture() -> None:
    fixture = load_fixture("epex_spot_2026-10-25.json")
    parsed = parse_interval_prices(fixture["attributes"]["data"])
    assert parsed.skipped == 0
    assert parsed.resolution == QUARTER
    assert len(parsed.prices) == 192
    # The repeated hour: both 02:45 CEST and 02:00 CET exist, one hour apart in UTC.
    assert parsed.prices[utc(2026, 10, 25, 0, 45)] == 0
    assert parsed.prices[utc(2026, 10, 25, 1, 0)] == 0.00001


def test_parse_hourly_prices_cover_four_quarters() -> None:
    parsed = parse_interval_prices(
        [
            {
                "start_time": "2026-01-01T10:00:00+01:00",
                "end_time": "2026-01-01T11:00:00+01:00",
                "price_per_kwh": 0.31,
            }
        ]
    )
    assert parsed.resolution == timedelta(hours=1)
    assert sorted(parsed.prices) == [utc(2026, 1, 1, 9, m) for m in (0, 15, 30, 45)]


def test_parse_skips_broken_entries() -> None:
    parsed = parse_interval_prices(
        [
            {"start_time": "2026-01-01T10:00:00+01:00"},
            {"start_time": "x", "end_time": "y", "price_per_kwh": 1},
            {
                "start_time": "2026-01-01T10:05:00+01:00",
                "end_time": "2026-01-01T10:20:00+01:00",
                "price_per_kwh": 0.1,
            },
            {
                "start_time": "2026-01-01T10:00:00",
                "end_time": "2026-01-01T10:15:00",
                "price_per_kwh": 0.1,
            },
        ]
    )
    assert parsed.prices == {}
    assert parsed.skipped == 4
    assert parsed.resolution is None


def test_price_table_round_trip() -> None:
    table = fixture_prices()
    restored = PriceTable()
    restored.restore(table.as_dict())
    assert restored == table
    assert len(restored) == 196


def test_price_table_reads_version_1_format() -> None:
    """0.1.0b1 stored {slot start: price}; it is converted on restore."""
    table = PriceTable()
    table.restore(
        {"2026-10-25T03:00:00+00:00": -0.00001, "2026-10-25T03:15:00+00:00": 0}
    )
    assert table.get(utc(2026, 10, 25, 3)) == -0.00001
    assert table.get(utc(2026, 10, 25, 3, 15)) == 0
    assert table.get(utc(2026, 10, 25, 3, 30)) is None


# --- quarter-hour history -------------------------------------------------------

# 25.10.2026 local time (25 hours, DST ends).
DAY_START, DAY_END = utc(2026, 10, 24, 22), utc(2026, 10, 25, 23)


def test_slot_series_spans_utc_days() -> None:
    series = SlotSeries()
    slot = DAY_START
    while slot < DAY_END:
        series.add(slot, 0.25)
        slot += QUARTER
    series.add(DAY_START, 0.25)
    # The local day of 100 quarter hours lies on two UTC days.
    assert sorted(series.days) == [date(2026, 10, 24), date(2026, 10, 25)]
    assert len(series) == 100
    items = list(series.items())
    assert items[0] == (DAY_START, 0.5)
    assert items[-1][0] == DAY_END - QUARTER
    assert [s for s, _ in items] == sorted(s for s, _ in items)


def test_slot_series_round_trip_and_rounding() -> None:
    series = SlotSeries()
    series.add(utc(2026, 1, 1, 9, 15), 1 / 3)
    series.set(utc(2026, 1, 1, 23, 45), 0.0)
    data = series.as_dict(7)
    assert data["2026-01-01"][37] == 0.3333333
    assert data["2026-01-01"][95] == 0.0
    assert data["2026-01-01"][0] is None
    restored = SlotSeries()
    restored.restore(data)
    assert restored.get(utc(2026, 1, 1, 9, 15)) == pytest.approx(1 / 3)
    assert restored.get(utc(2026, 1, 1, 9, 30)) is None
    assert len(restored) == 2


def test_slot_series_day_ranges_and_merge() -> None:
    series = SlotSeries()
    for day in (24, 25, 26):
        series.set(utc(2026, 10, day, 12), float(day))
    assert list(series.as_dict(7, start=date(2026, 10, 25))) == [
        "2026-10-25",
        "2026-10-26",
    ]
    assert list(series.as_dict(7, end=date(2026, 10, 25))) == ["2026-10-24"]
    assert series.years() == {2026}
    # Merging keeps days already present (the live state wins).
    live = SlotSeries()
    live.set(utc(2026, 10, 26, 12), 99.0)
    live.restore(series.as_dict(7), merge=True)
    assert live.get(utc(2026, 10, 26, 12)) == 99.0
    assert live.get(utc(2026, 10, 24, 12)) == 24.0


# --- price sources ------------------------------------------------------------------


def test_epex_spot_format_recognised() -> None:
    fixture = load_fixture("epex_spot_2026-10-25.json")
    parsed = parse_price_attributes(fixture["attributes"])
    assert parsed is not None
    assert parsed.format == "epex_spot"
    assert len(parsed.prices) == 192


@pytest.mark.parametrize("as_objects", [False, True])
def test_nordpool_raw_today(as_objects: bool) -> None:
    """Strings as serialized; datetime objects as inside Home Assistant."""
    attributes = load_fixture("nordpool_raw_2025-10-01.json")["attributes"]
    if as_objects:
        attributes["raw_today"] = [
            {
                **e,
                "start": datetime.fromisoformat(e["start"]),
                "end": datetime.fromisoformat(e["end"]),
            }
            for e in attributes["raw_today"]
        ]
    parsed = parse_price_attributes(attributes)
    assert parsed is not None
    assert parsed.format == "nordpool"
    assert parsed.resolution == QUARTER
    assert parsed.skipped == 0
    assert len(parsed.prices) == 96
    # 2025-10-01 00:00 CEST = 2025-09-30 22:00 UTC: 556.68 EUR/MWh.
    assert parsed.prices[utc(2025, 9, 30, 22)] == 0.557


def test_entsoe_hourly_prices_without_end() -> None:
    attributes = load_fixture("entsoe_prices_2024-10-06.json")["attributes"]
    parsed = parse_price_attributes(attributes)
    assert parsed is not None
    assert parsed.format == "entsoe"
    assert parsed.resolution == timedelta(hours=1)
    # 48 hours (today and tomorrow), each for its four quarter hours; the
    # entries of `prices_today`/`prices_tomorrow` repeat those of `prices`.
    assert len(parsed.prices) == 192
    hour = utc(2024, 10, 5, 22)
    assert {parsed.prices[hour + i * QUARTER] for i in range(4)} == {0.06704}
    assert parsed.prices[utc(2024, 10, 6, 11)] == -0.00001


def test_start_prices_gap_is_not_filled() -> None:
    entries = [
        {"time": "2026-01-01 10:00:00+01:00", "price": 0.1},
        {"time": "2026-01-01 11:00:00+01:00", "price": 0.2},
        {"time": "2026-01-01 13:00:00+01:00", "price": 0.3},
    ]
    parsed = parse_start_prices(entries)
    assert parsed.resolution == timedelta(hours=1)
    assert utc(2026, 1, 1, 10, 45) in parsed.prices
    assert utc(2026, 1, 1, 11) not in parsed.prices
    assert parsed.prices[utc(2026, 1, 1, 12, 45)] == 0.3
    # A single entry has no measurable length: nothing is guessed.
    single = parse_start_prices(entries[:1])
    assert single.prices == {}
    assert single.skipped == 1


@pytest.mark.parametrize(
    "attributes",
    [
        # Ostrom: same attribute name as EPEX Spot, other keys, ct/kWh.
        {"data": [{"date": "2026-10-26T10:00:00.000Z", "price": 31.2}]},
        # 1KOMMA5 (two integrations, two structures under `forecast`).
        {"forecast": [{"datetime": "2026-10-26T10:00:00+00:00", "price": 0.31}]},
        {"today": [0.31, 0.32]},
    ],
)
def test_unknown_formats_are_not_guessed(attributes: dict) -> None:
    assert parse_price_attributes(attributes) is None


def test_attribute_shape_has_no_values() -> None:
    attributes = load_fixture("nordpool_raw_2025-10-01.json")["attributes"]
    shape = attribute_shape(attributes)
    assert shape["raw_today"] == {
        "entries": 96,
        "entry": {"start": "str", "end": "str", "value": "float"},
    }
    assert "raw_tomorrow" not in shape  # empty lists are left out
    assert "0.557" not in str(shape)


# --- prices from recorded states -------------------------------------------------


def recorded_states(
    prices: list[tuple[datetime, float]], delay: timedelta = timedelta(seconds=0.3)
) -> list[tuple[datetime, float | None]]:
    """States as the recorder keeps them: a row only when the price changes,
    shortly after the quarter-hour boundary (EPEX Spot)."""
    states: list[tuple[datetime, float | None]] = []
    for slot, price in prices:
        if not states or states[-1][1] != price:
            states.append((slot + delay, price))
    return states


def test_prices_from_states_reproduce_the_fixture() -> None:
    """The step function of the state gives every quarter-hour price back,
    also runs of equal prices without a state change (48 at 0 €)."""
    prices = list(fixture_prices().items())
    start, end = prices[0][0], prices[-1][0] + QUARTER
    states = recorded_states(prices)
    assert len(states) < len(prices)
    # A later state ends the last price (it would be the next price change).
    states.append((end + timedelta(seconds=0.2), 0.5))
    assert prices_from_states(states, start, end) == dict(prices)


def test_prices_from_states_not_across_a_restart() -> None:
    """A state that does not start a quarter hour may follow a restart: the
    time before it gets no price, the price may have changed meanwhile."""
    a = utc(2026, 10, 25, 10)
    states: list[tuple[datetime, float | None]] = [
        (a + timedelta(seconds=0.3), 0.10),
        # Home Assistant off from about 10:05, back at 11:03:27.
        (a + timedelta(hours=1, minutes=3, seconds=27), 0.20),
        (a + timedelta(hours=1, minutes=15, seconds=0.2), 0.30),
    ]
    prices = prices_from_states(states, a, a + timedelta(hours=2))
    assert prices == {
        a: 0.10,
        a + timedelta(hours=1): 0.20,
        a + timedelta(hours=1, minutes=15): 0.30,
    }


def test_prices_from_states_unavailable_and_period() -> None:
    a = utc(2026, 10, 25, 10)
    states: list[tuple[datetime, float | None]] = [
        # Before the period: holds into it up to the next price change.
        (a - timedelta(minutes=29, seconds=59.7), 0.10),
        (a + QUARTER + timedelta(seconds=0.3), 0.20),
        # Unavailable right at a boundary: no price from here on.
        (a + 2 * QUARTER + timedelta(seconds=0.1), None),
        (a + 4 * QUARTER + timedelta(seconds=0.4), 0.40),
        # Unavailable within a quarter hour: the earlier price stays.
        (a + 4 * QUARTER + timedelta(minutes=5), None),
    ]
    prices = prices_from_states(states, a, a + 5 * QUARTER)
    assert prices == {a: 0.10, a + QUARTER: 0.20, a + 4 * QUARTER: 0.40}
    assert prices_from_states([], a, a + QUARTER) == {}
