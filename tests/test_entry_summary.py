"""Summaries at the top of "Reconfigure" of the entry and of "PV and
battery" (no Home Assistant needed). All names and values invented."""

from __future__ import annotations

from datetime import date
from typing import Any

from custom_components.tarifwacht.entry_summary import (
    Source,
    Tariff,
    entry_summary,
    solar_summary,
)

METER = Source("sensor.grid_import", "Netz Bezug")
STARTED = date(2026, 10, 26)
TARIFFS = [Tariff("Festpreis", current=True), Tariff("Dynamisch")]

SOLAR: dict[str, Any] = {
    "feed_in_entity": "sensor.grid_export",
    "pv_entity": "sensor.inverter_energy",
    "charged_entity": "sensor.battery_charged",
    "discharged_entity": "sensor.battery_discharged",
    "same_inverter": True,
    "feed_in_rate": 7.94,
    "negative_unpaid": True,
    "pv_cost": 12000.0,
    "pv_since": "2023-05-01",
    "battery_cost": 6000.0,
}
SOURCES = {
    "feed_in_entity": Source("sensor.grid_export", "Netz Einspeisung"),
    "pv_entity": Source("sensor.inverter_energy", "Wechselrichter Erzeugung"),
    "charged_entity": Source("sensor.battery_charged", "Akku geladen"),
    "discharged_entity": Source("sensor.battery_discharged", "Akku entladen"),
}
MARKET = Source("sensor.exchange_price", "Börsenpreis")


def test_entry_all_set_up() -> None:
    text = entry_summary(METER, TARIFFS, SOLAR, started=STARTED, german=True)
    assert text == (
        "**Eingerichtet**\n"
        "- Bezugszähler: „Netz Bezug“\n"
        "- Bucht seit 26.10.2026; die Zeit davor über die Aktionen „Tarife "
        "vergleichen“ und „Statistik nachtragen“\n"
        "- Tarife: 2 („Festpreis“, „Dynamisch“)\n"
        "- Mein aktueller Tarif: „Festpreis“\n"
        "- PV und Speicher: PV mit Speicher"
    )
    assert "Was fehlt" not in text


def test_entry_missing_parts() -> None:
    text = entry_summary(
        Source("sensor.gone"),
        [Tariff("Festpreis"), Tariff("Dynamisch")],
        None,
        started=None,
        german=True,
    )
    lines = text.split("\n")
    assert lines[:3] == [
        "**Eingerichtet**",
        "- Bezugszähler: `sensor.gone`",
        "- Tarife: 2 („Festpreis“, „Dynamisch“)",
    ]
    # Not loaded: no "since"; no current tariff, no PV.
    assert "Bucht seit" not in text
    assert "\n\n**Was fehlt**\n" in text
    missing = text.split("**Was fehlt**\n")[1].split("\n")
    assert missing[0].startswith("- Bezugszähler `sensor.gone` gibt es nicht")
    assert missing[1].startswith("- Kein „Mein aktueller Tarif“: keine Sensoren")
    assert missing[2].startswith("- Kein „PV und Speicher“")


def test_entry_tariff_count_hints() -> None:
    one = entry_summary(METER, [Tariff("A")], {}, started=STARTED, german=True)
    assert "Nur ein Tarif: nichts zu vergleichen" in one
    # With one tariff, no current one is not worth a word.
    assert "Mein aktueller Tarif" not in one
    assert "PV ohne Speicher" in one
    none = entry_summary(METER, [], {}, started=STARTED, german=True)
    assert "- Kein Tarif: nichts zu rechnen" in none
    assert "Tarife:" not in none


def test_entry_first_marked_is_current_and_names_escaped() -> None:
    text = entry_summary(
        Source("sensor.m", "Zähler *1*"),
        [Tariff("A_b", True), Tariff("C", True)],
        None,
        started=STARTED,
        german=False,
    )
    assert "- Grid purchase meter: “Zähler \\*1\\*”" in text
    assert "- My current tariff: “A\\_b”" in text
    assert text.startswith("**Set up**\n")
    assert "**Missing**\n- No “PV and battery”" in text
    assert "Booking since 2026-10-26" in text


def test_solar_all_set_up() -> None:
    text = solar_summary(
        SOLAR,
        SOURCES,
        market=MARKET,
        market_tariff="Dynamisch",
        started=STARTED,
        german=True,
    )
    assert text == (
        "**Eingerichtet**\n"
        "- Einspeisezähler: „Netz Einspeisung“\n"
        "- PV-Zähler: „Wechselrichter Erzeugung“\n"
        "- Speicher: geladen „Akku geladen“, entladen „Akku entladen“, am "
        "selben Wechselrichter wie die PV (Hybrid)\n"
        "- Einspeisevergütung: 7,94 ct/kWh, bei negativen Preisen keine "
        "Vergütung (§ 51 EEG, Börsenpreis „Börsenpreis“ aus dem Tarif "
        "„Dynamisch“)\n"
        # The battery counts from the PV's day without its own.
        "- Anschaffung: PV 12.000,00 € seit 01.05.2023, Speicher 6.000,00 € "
        "seit 01.05.2023\n"
        "- Ersparnis gerechnet seit 26.10.2026"
    )


def test_solar_without_battery_and_purchase() -> None:
    data = {
        "feed_in_entity": "sensor.grid_export",
        "pv_entity": "sensor.inverter_energy",
        "feed_in_rate": 8.0,
        "negative_unpaid": False,
        "same_inverter": False,
    }
    text = solar_summary(
        data,
        {k: SOURCES[k] for k in ("feed_in_entity", "pv_entity")},
        market=None,
        market_tariff=None,
        started=None,
        german=True,
    )
    assert "Speicher:" not in text
    assert "- Einspeisevergütung: 8 ct/kWh\n" in text
    assert "Anschaffung:" not in text
    missing = text.split("**Was fehlt**\n")[1].split("\n")
    assert missing == [
        "- Ohne Speicherzähler keine Sensoren „Ersparnis Speicher“ (nur mit "
        "Speicher nötig).",
        "- Ohne Anschaffung PV (unter „Anschaffung“): kein „bezahlt gemacht“ dafür.",
    ]


def test_solar_battery_without_its_cost() -> None:
    data = {**SOLAR, "negative_unpaid": False}
    del data["pv_cost"], data["pv_since"], data["battery_cost"]
    text = solar_summary(
        data, SOURCES, market=None, market_tariff=None, started=STARTED, german=False
    )
    assert "**Missing**\n- Without the purchase of PV and battery" in text
    assert "no payment at negative prices" not in text


def test_solar_section51_without_market_and_missing_meters() -> None:
    sources = {
        **SOURCES,
        "pv_entity": Source("sensor.inverter_energy"),
        "charged_entity": Source("sensor.battery_charged"),
    }
    text = solar_summary(
        SOLAR, sources, market=None, market_tariff=None, started=STARTED, german=True
    )
    # Without an exchange price the rule is not in the line of the rate.
    assert "- Einspeisevergütung: 7,94 ct/kWh\n" in text
    assert "- PV-Zähler: `sensor.inverter_energy`" in text
    missing = text.split("**Was fehlt**\n")[1].split("\n")
    assert missing[0].startswith(
        "- PV-Zähler `sensor.inverter_energy` gibt es nicht: keine neuen Stunden"
    )
    assert missing[1].startswith(
        "- Speicherzähler `sensor.battery_charged` gibt es nicht: er zählt als 0"
    )
    assert missing[2].startswith("- „Keine Vergütung bei negativen Preisen“ ohne")
    assert len(missing) == 3


def test_solar_market_sensor_missing() -> None:
    text = solar_summary(
        SOLAR,
        SOURCES,
        market=Source("sensor.exchange_price"),
        market_tariff=None,
        started=None,
        german=True,
    )
    assert "Börsenpreis `sensor.exchange_price`)" in text
    assert (
        "- Börsenpreis-Sensor `sensor.exchange_price` für § 51 gibt es nicht"
    ) in text


def test_solar_own_market_sensor() -> None:
    text = solar_summary(
        SOLAR, SOURCES, market=MARKET, market_tariff=None, started=None, german=False
    )
    assert (
        "- Feed-in tariff: 7.94 ct/kWh, no payment at negative prices "
        "(§ 51 EEG, exchange price “Börsenpreis”)\n"
    ) in text
    assert "Saving computed since" not in text
    assert "**Missing**" not in text
