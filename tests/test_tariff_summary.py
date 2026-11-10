"""What a tariff shows of itself: the summary of its gear menu and the
sensor "Energy price now" (no Home Assistant needed for the values).

All prices invented.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.tarifwacht.const import BERLIN
from custom_components.tarifwacht.prices import PriceTable
from custom_components.tarifwacht.sensor import PRICE_NOW, _price_now
from custom_components.tarifwacht.tariff_config import tariff_from_data
from custom_components.tarifwacht.tariff_summary import (
    _number,
    edit_hint,
    price_now_attributes,
    summary,
)

TODAY = date(2026, 11, 8)

FIXED: dict[str, Any] = {
    "key": "fixed",
    "kind": "fixed",
    "price": 27.75,
    "base_price": 12.0,
    "base_period": "month",
    "current": True,
    "bonus": 1250.0,
    "bonus_date": "2026-03-01",
    "changes": [
        {
            "from": "2027-01-01",
            "price": 32.0,
            "base_price": 13.0,
            "base_period": "month",
        },
        {
            "from": "2026-01-01",
            "price": 30.5,
            "base_price": 13.0,
            "base_period": "month",
        },
    ],
}

MODUL3 = {
    "active": True,
    "nt": 3.0,
    "ht": 13.0,
    "quarters": [1, 4],
    "nt_windows": "00:00-06:00",
    "ht_windows": "17:00-20:00",
}

MARKET: dict[str, Any] = {
    "key": "boerse",
    "kind": "dynamic_market",
    "price_entity": "sensor.market",
    "grid_fee": 9.0,
    "levies": 5.0,
    "margin": 2.0,
    "vat": 19.0,
    "base_price": 12.0,
    "base_period": "month",
    "current": False,
    "modul3": MODUL3,
}

TOTAL: dict[str, Any] = {
    "key": "total",
    "kind": "dynamic_total",
    "price_entity": "sensor.total",
    "base_price": 120.0,
    "base_period": "year",
    "current": False,
}


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=BERLIN).astimezone(UTC)


# --- menu summary -----------------------------------------------------------


def test_fixed_with_price_changes_and_bonus_german() -> None:
    assert summary(FIXED, TODAY, german=True) == (
        "**Festpreis** · heute: 30,5 ct/kWh + 13,00 €/Monat (seit 01.01.2026)\n\n"
        "Preise:\n"
        "- ab Beginn: 27,75 ct/kWh + 12,00 €/Monat\n"
        "- ab 01.01.2026: 30,5 ct/kWh + 13,00 €/Monat\n"
        "- ab 01.01.2027: 32 ct/kWh + 13,00 €/Monat **(kommt)**\n\n"
        "Bonus: 1.250,00 € am 01.03.2026 · Modul 3: aus · Mein aktueller Tarif: ja"
    )


def test_fixed_english() -> None:
    text = summary(FIXED, TODAY, german=False)
    assert text.startswith(
        "**Fixed price** · today: 30.5 ct/kWh + 13.00 €/month (since 2026-01-01)"
    )
    assert "- from the start: 27.75 ct/kWh + 12.00 €/month\n" in text
    assert "- from 2027-01-01: 32 ct/kWh + 13.00 €/month **(upcoming)**" in text
    assert text.endswith(
        "Bonus: 1,250.00 € on 2026-03-01 · Modul 3: off · My current tariff: yes"
    )


def test_before_the_first_change_today_is_the_start() -> None:
    text = summary(FIXED, date(2025, 12, 31), german=True)
    first = text.split("\n\n")[0]
    assert first == "**Festpreis** · heute: 27,75 ct/kWh + 12,00 €/Monat"
    # Both changes still to come.
    assert text.count("**(kommt)**") == 2


def test_exchange_price_with_modul3() -> None:
    assert summary(MARKET, TODAY, german=True) == (
        "**Börsenpreis plus Aufschläge** · heute: Börsenpreis + Netzentgelt 9 + "
        "Abgaben 5 + Aufschlag 2 ct (netto) + MwSt. 19 %, Grundpreis 12,00 €/Monat"
        "\n\nPreisänderungen: keine\n\n"
        "Bonus: – · Modul 3: an (Q1, Q4) · Mein aktueller Tarif: nein"
    )


def test_exchange_price_only_with_surcharge_and_modul3_from_a_date() -> None:
    data = {
        **MARKET,
        "grid_fee": 0.0,
        "levies": 0.0,
        "margin": 14.5,
        "modul3": {**MODUL3, "active": False},
        "changes": [
            {
                "from": "2027-01-01",
                "grid_fee": 0.0,
                "levies": 0.0,
                "margin": 15.0,
                "vat": 19.0,
                "modul3": {**MODUL3, "quarters": [1, 2, 3, 4]},
                "base_price": 12.0,
                "base_period": "month",
            }
        ],
    }
    text = summary(data, TODAY, german=False)
    assert text.startswith(
        "**Exchange price plus surcharges** · today: exchange price + "
        "surcharge 14.5 ct (net) + VAT 19 %, base price 12.00 €/month\n\n"
    )
    assert (
        "- from 2027-01-01: surcharge 15 ct (net) + VAT 19 %, base price "
        "12.00 €/month, Modul 3 **(upcoming)**"
    ) in text
    assert "Modul 3: off" in text
    # From the change on, all quarters.
    assert "Modul 3: on (Q1–Q4)" in summary(data, date(2027, 1, 1), german=False)


def test_total_price_sensor() -> None:
    assert summary(TOTAL, TODAY, german=True, sensor_name="EPEX_Spot *Total*") == (
        "**Sensor mit Gesamtpreis** · heute: Preissensor „EPEX\\_Spot \\*Total\\*“, "
        "Grundpreis 120,00 €/Jahr\n\nPreisänderungen: keine\n\n"
        "Bonus: – · Mein aktueller Tarif: nein"
    )
    no_base = summary({**TOTAL, "base_price": 0.0}, TODAY, german=False)
    assert "today: price sensor “?”, no base price" in no_base


def test_edit_hint() -> None:
    assert edit_hint(True).startswith("\n\nDiese Werte gelten ab Beginn")
    assert "„Preisänderung ab einem Datum hinzufügen“" in edit_hint(True)
    assert "“Add a price change from a date”" in edit_hint(False)


# --- sensor "Energy price now": attributes ----------------------------------


def test_attributes_of_a_fixed_price_with_changes() -> None:
    assert price_now_attributes(FIXED, local(2026, 11, 8, 12, 0)) == {
        "base_price_eur": 13.0,
        "base_period": "month",
        "valid_since": "2026-01-01",
        "next_change": {
            "from": "2027-01-01",
            "price_ct": 32.0,
            "base_price_eur": 13.0,
            "base_period": "month",
            "modul3": False,
        },
        "bonus": {"amount_eur": 1250.0, "date": "2026-03-01"},
        "modul3_active_now": False,
    }
    # The last state: no next change; local midnight counts (UTC still 2026).
    last = price_now_attributes(FIXED, local(2027, 1, 1, 0, 30))
    assert last["valid_since"] == "2027-01-01"
    assert "next_change" not in last


def test_attributes_modul3_by_quarter() -> None:
    assert price_now_attributes(MARKET, local(2026, 11, 8, 12, 0)) == {
        "base_price_eur": 12.0,
        "base_period": "month",
        "valid_since": None,
        "modul3_active_now": True,
    }
    # Q2 is not one of its quarters.
    assert not price_now_attributes(MARKET, local(2026, 5, 8, 12, 0))[
        "modul3_active_now"
    ]


def test_attributes_of_a_total_price_sensor() -> None:
    assert price_now_attributes(TOTAL, local(2026, 11, 8, 12, 0)) == {
        "base_price_eur": 120.0,
        "base_period": "year",
        "valid_since": None,
    }


# --- sensor "Energy price now": value ---------------------------------------


def runtime(data: dict[str, Any], table: PriceTable) -> tuple[Any, Any]:
    """A stand-in runtime with the engine's tariff, and the tariff."""
    tariff = tariff_from_data(data, lambda _entity: table)
    engine = SimpleNamespace(tariffs={data["key"]: tariff})
    return SimpleNamespace(engine=engine), SimpleNamespace(key=data["key"])


def test_no_state_class() -> None:
    assert PRICE_NOW.state_class is None
    assert PRICE_NOW.entity_category is None
    assert PRICE_NOW.native_unit_of_measurement == "ct/kWh"


def test_price_now_fixed_follows_the_price_changes() -> None:
    run, tariff = runtime(FIXED, PriceTable())
    assert _price_now(run, tariff, local(2025, 12, 31, 23, 59)) == 27.75
    assert _price_now(run, tariff, local(2026, 11, 8, 12, 7)) == 30.5
    assert _price_now(run, tariff, local(2027, 1, 1, 0, 0)) == 32.0


def test_price_now_fixed_with_modul3() -> None:
    data = {
        **FIXED,
        "changes": [],
        "modul3": {**MODUL3, "standard": 8.0, "vat": 19.0},
    }
    run, tariff = runtime(data, PriceTable())
    # NT window in Q4: 27.75 + (3 - 8) * 1.19.
    assert _price_now(run, tariff, local(2026, 11, 8, 3, 10)) == pytest.approx(21.8)
    # HT: 27.75 + (13 - 8) * 1.19; outside the windows the fixed price.
    assert _price_now(run, tariff, local(2026, 11, 8, 18, 0)) == pytest.approx(33.7)
    assert _price_now(run, tariff, local(2026, 11, 8, 12, 0)) == 27.75
    # Q2 is not one of its quarters.
    assert _price_now(run, tariff, local(2026, 5, 8, 18, 0)) == 27.75


def test_price_now_exchange_price_with_modul3() -> None:
    table = PriceTable()
    table.merge(
        {
            local(2026, 11, 8, 18, 0): 0.10,
            local(2026, 11, 8, 18, 15): 0.12,
            local(2026, 11, 8, 12, 0): -0.01,
        }
    )
    run, tariff = runtime(MARKET, table)
    # HT window: (10 + 13 + 5 + 2) * 1.19.
    assert _price_now(run, tariff, local(2026, 11, 8, 18, 14)) == pytest.approx(35.7)
    assert _price_now(run, tariff, local(2026, 11, 8, 18, 15)) == pytest.approx(
        (12 + 13 + 5 + 2) * 1.19
    )
    # Standard grid fee outside the windows, also with a negative price.
    assert _price_now(run, tariff, local(2026, 11, 8, 12, 5)) == pytest.approx(
        (-1 + 9 + 5 + 2) * 1.19
    )
    # No price for the quarter hour yet.
    assert _price_now(run, tariff, local(2026, 11, 8, 19, 0)) is None


def test_price_now_total_price_sensor() -> None:
    table = PriceTable()
    table.merge({local(2026, 11, 8, 12, 0): 0.31234})
    run, tariff = runtime(TOTAL, table)
    assert _price_now(run, tariff, local(2026, 11, 8, 12, 14)) == 31.234
    assert _price_now(run, tariff, local(2026, 11, 8, 12, 15)) is None


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [(90, 0, "90"), (100, 0, "100"), (0, 0, "0"), (27.75, 3, "27,75"), (19.0, 1, "19")],
)
def test_number_keeps_whole_numbers(value: float, digits: int, expected: str) -> None:
    assert _number(value, True, digits) == expected
