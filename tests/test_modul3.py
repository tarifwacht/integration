"""Modul 3 (§ 14a EnWG): windows, quarters and fees (no Home Assistant).

Examples from published price sheets 2026 (net ct/kWh); sources in
docs/ENTWICKLUNG.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.tarifwacht.const import (
    BERLIN,
    CONF_GRID_FEE,
    CONF_KIND,
    CONF_LEVIES,
    CONF_MARGIN,
    CONF_MODUL3,
    CONF_PRICE_ENTITY,
    CONF_VAT,
    KIND_DYNAMIC_MARKET,
)
from custom_components.tarifwacht.modul3 import (
    WindowError,
    modul3_from_data,
    overlaps,
    parse_windows,
)
from custom_components.tarifwacht.prices import PriceTable
from custom_components.tarifwacht.tariff_config import tariff_from_data

NETZE_BW = {
    "active": True,
    "nt": 3.03,
    "ht": 11.06,
    "quarters": [1, 2, 3, 4],
    "nt_windows": "10:00-14:00",
    "ht_windows": "17:00-22:00",
}


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=BERLIN).astimezone(UTC)


def test_parse_windows() -> None:
    assert parse_windows("10:00-14:00") == [(600, 840)]
    assert parse_windows("01:45-06:15, 22:30-24:00") == [(105, 375), (1350, 1440)]
    # Across midnight (EAM Netz 2026: NT 23:00-06:00).
    assert parse_windows("23:00 - 06:00") == [(1380, 1440), (0, 360)]
    assert parse_windows("") == []
    for text, key in (
        ("10-14", "window_format"),
        ("10:00-10:00", "window_format"),
        ("25:00-26:00", "window_format"),
        ("10:05-14:00", "window_grid"),
    ):
        with pytest.raises(WindowError) as err:
            parse_windows(text)
        assert err.value.key == key
    assert overlaps(parse_windows("10:00-14:00"), parse_windows("13:45-15:00"))
    assert not overlaps(parse_windows("10:00-14:00"), parse_windows("14:00-15:00"))


def test_netze_bw_2026_levels() -> None:
    modul3 = modul3_from_data(NETZE_BW, 7.57, BERLIN)
    assert modul3 is not None
    assert modul3.fee(local(2026, 6, 1, 9, 45)) == pytest.approx(0.0757)
    assert modul3.fee(local(2026, 6, 1, 10, 0)) == pytest.approx(0.0303)
    assert modul3.fee(local(2026, 6, 1, 13, 45)) == pytest.approx(0.0303)
    assert modul3.fee(local(2026, 6, 1, 14, 0)) == pytest.approx(0.0757)
    assert modul3.fee(local(2026, 1, 15, 21, 45)) == pytest.approx(0.1106)
    assert modul3.fee(local(2026, 1, 15, 22, 0)) == pytest.approx(0.0757)


def test_dusseldorf_2026_only_q1_and_q4() -> None:
    """Netzgesellschaft Düsseldorf: NT 04:30-05:00, HT 18:00-20:00, Q1 and Q4."""
    data = {
        "active": True,
        "nt": 3.16,
        "ht": 8.19,
        "quarters": [1, 4],
        "nt_windows": "04:30-05:00",
        "ht_windows": "18:00-20:00",
    }
    modul3 = modul3_from_data(data, 7.91, BERLIN)
    assert modul3 is not None
    assert modul3.fee(local(2026, 3, 31, 4, 30)) == pytest.approx(0.0316)
    # 1 April is Q2: standard all day, also inside the windows.
    assert modul3.fee(local(2026, 4, 1, 4, 30)) == pytest.approx(0.0791)
    assert modul3.fee(local(2026, 10, 1, 18, 0)) == pytest.approx(0.0819)


def test_fall_back_day_both_hours_get_the_level() -> None:
    """25.10.2026: 02:00-03:00 local occurs twice; both get its level."""
    data = {**NETZE_BW, "nt_windows": "02:00-03:00", "ht_windows": "17:00-22:00"}
    modul3 = modul3_from_data(data, 7.57, BERLIN)
    assert modul3 is not None
    first = datetime(2026, 10, 25, 0, 15, tzinfo=UTC)  # 02:15 CEST
    second = datetime(2026, 10, 25, 1, 15, tzinfo=UTC)  # 02:15 CET
    assert modul3.fee(first) == modul3.fee(second) == pytest.approx(0.0303)


def test_inactive_or_missing() -> None:
    assert modul3_from_data({}, 7.57, BERLIN) is None
    assert modul3_from_data({**NETZE_BW, "active": False}, 7.57, BERLIN) is None


def test_market_tariff_with_modul3() -> None:
    """(exchange + grid fee of the quarter hour + other surcharges) * (1 + VAT)."""
    market = PriceTable()
    nt_slot, st_slot = local(2026, 6, 1, 11, 0), local(2026, 6, 1, 8, 0)
    market.set(nt_slot, 0.05)
    market.set(st_slot, 0.05)
    data = {
        CONF_KIND: KIND_DYNAMIC_MARKET,
        CONF_PRICE_ENTITY: "sensor.market",
        CONF_GRID_FEE: 7.57,
        CONF_LEVIES: 4.0,
        CONF_MARGIN: 2.0,
        CONF_VAT: 19.0,
        CONF_MODUL3: NETZE_BW,
    }
    tariff = tariff_from_data(data, lambda _: market)
    assert tariff.price(nt_slot) == pytest.approx((0.05 + 0.0303 + 0.06) * 1.19)
    assert tariff.price(st_slot) == pytest.approx((0.05 + 0.0757 + 0.06) * 1.19)
    # Without Modul 3: the standard grid fee all day.
    plain = tariff_from_data({**data, CONF_MODUL3: {}}, lambda _: market)
    assert plain.price(nt_slot) == pytest.approx((0.05 + 0.1357) * 1.19)
