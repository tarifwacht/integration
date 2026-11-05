"""The report for a bug report: plain text, tariffs by kind and number, no
names, entity ids or other free text."""

from __future__ import annotations

from custom_components.tarifwacht.button import roles, scrub, tariff_settings
from custom_components.tarifwacht.issue_report import render, settings

METER = "sensor.grid_import"
PRICE = "sensor.epex_spot_data_market_price"

FIXED = {
    "key": "fixed",
    "kind": "fixed",
    "price": 30.0,
    "base_price": 31.0,
    "base_period": "month",
    "current": True,
    "changes": [{"from": "2027-01-01", "price": 32.5}],
}
MARKET = {
    "kind": "dynamic_market",
    "price_entity": PRICE,
    "grid_fee": 9.0,
    "levies": 5.0,
    "margin": 2.0,
    "vat": 19.0,
    "base_price": 12.0,
    "base_period": "year",
    "current": False,
    "smard_fill": True,
    "modul3": {
        "active": True,
        "nt": 3.0,
        "ht": 13.0,
        "quarters": [4, 1],
        "nt_windows": "22:00-06:00",
        "ht_windows": " 17:00 - 20:00 ",
    },
}


def test_render_sections_and_lines() -> None:
    text = render(
        "Tarifwacht 0.1.3, Home Assistant 2026.11.0",
        [
            ("entry", [("tariffs", "2 (fixed 1, dynamic_market 1)")]),
            ("sources", []),
            ("settings", settings({"b": 1, "a": "x"})),
        ],
    )
    assert text == (
        "Tarifwacht 0.1.3, Home Assistant 2026.11.0\n"
        "\n"
        "[entry]\n"
        "tariffs: 2 (fixed 1, dynamic_market 1)\n"
        "\n"
        "[settings]\n"
        "a: x\n"
        "b: 1"
    )


def test_roles_number_the_tariffs() -> None:
    assert roles(METER, [FIXED, MARKET]) == {
        "meter": METER,
        "tariff 2 price": PRICE,
    }


def test_tariff_settings_from_a_positive_list() -> None:
    lines = tariff_settings([FIXED, MARKET])
    assert lines == [
        ("tariff 1", "fixed, current, price 30, base_price 31, base_period month"),
        ("tariff 1 from 2027-01-01", "price 32.5"),
        (
            "tariff 2",
            "dynamic_market, grid_fee 9, levies 5, margin 2, vat 19, "
            "base_price 12, base_period year, SMARD.de fill on",
        ),
        (
            "tariff 2 modul 3",
            "NT 3 ct 22:00-24:00 00:00-06:00, HT 13 ct 17:00-20:00, quarters 1,4",
        ),
    ]
    text = str(lines)
    assert PRICE not in text and "key" not in text


def test_modul3_off_and_invalid_windows() -> None:
    off = {**MARKET, "modul3": {"active": False, "nt_windows": "secret text"}}
    assert ("tariff 1 modul 3", "off") in tariff_settings([off])
    bad = {**MARKET, "modul3": {**MARKET["modul3"], "ht_windows": "my text"}}
    (line,) = [v for k, v in tariff_settings([bad]) if k == "tariff 1 modul 3"]
    assert "HT 13 ct invalid" in line and "my text" not in line


def test_scrub_replaces_entity_ids_by_roles() -> None:
    mapping = {"meter": "sensor.price", "tariff 2 price": "sensor.price_2"}
    assert (
        scrub("sensor.price_2: TimeoutError", mapping) == "tariff 2 price: TimeoutError"
    )
    assert scrub("sensor.price failed", mapping) == "meter failed"
