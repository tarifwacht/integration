"""Short summaries at the top of "Reconfigure" of the entry and of the
subentry "PV and battery" (markdown). Pure Python.

As in the sisters (Speicherwacht, Wärmewacht): "Set up" lists what the
entry or subentry reads and computes, "Missing" (only when something is)
what is not set up and what that costs - only what the code derives from
it. Description placeholders are not translated by Home Assistant, so the
words are here, German or English after the language of Home Assistant
(like the tariff summary). The facts about the source entities come from
the caller, read when the form opens; nothing is read from the statistics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from .const import (
    CONF_CHARGED_ENTITY,
    CONF_DISCHARGED_ENTITY,
    CONF_FEED_IN_ENTITY,
    CONF_FEED_IN_RATE,
    CONF_NEGATIVE_UNPAID,
    CONF_PV_ENTITY,
    CONF_SAME_INVERTER,
)
from .payback import BATTERY, PV, purchases
from .tariff_summary import _MARKDOWN, _date, _euro, _number


@dataclass(frozen=True, slots=True)
class Source:
    """A source entity as the summary shows it."""

    entity_id: str
    # The entity's name from its state; None: there is no state (removed,
    # or renamed outside the registry).
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Tariff:
    """A tariff subentry as the entry's summary shows it."""

    title: str
    current: bool = False


_WORDS: dict[str, dict[str, str]] = {
    "de": {
        "configured": "**Eingerichtet**",
        "missing": "**Was fehlt**",
        "meter": "Bezugszähler: {name}",
        "started": (
            "Bucht seit {date}; die Zeit davor über die Aktionen „Tarife "
            "vergleichen“ und „Statistik nachtragen“"
        ),
        "tariffs": "Tarife: {count} ({names})",
        "current": "Mein aktueller Tarif: {name}",
        "solar_battery": "PV und Speicher: PV mit Speicher",
        "solar_pv": "PV und Speicher: PV ohne Speicher",
        "hint_meter_missing": (
            "Bezugszähler {entity} gibt es nicht: keine neuen Werte, bis er "
            "wieder da ist oder hier ein anderer gewählt ist."
        ),
        "hint_no_tariff": (
            "Kein Tarif: nichts zu rechnen – unter „Tarif hinzufügen“ einen anlegen."
        ),
        "hint_one_tariff": (
            "Nur ein Tarif: nichts zu vergleichen – weitere unter „Tarif hinzufügen“."
        ),
        "hint_no_current": (
            "Kein „Mein aktueller Tarif“: keine Sensoren „Differenz zum "
            "aktuellen Tarif“ – im Tarif unter „Tarif bearbeiten“ "
            "setzen."
        ),
        "hint_no_solar": (
            "Kein „PV und Speicher“: keine Sensoren „Ersparnis PV“ und "
            "„Ersparnis Speicher“ (nur mit eigener Anlage nötig)."
        ),
        # PV and battery
        "feed_in": "Einspeisezähler: {name}",
        "pv": "PV-Zähler: {name}",
        "battery": "Speicher: geladen {charged}, entladen {discharged}, {coupling}",
        "same_inverter": "am selben Wechselrichter wie die PV (Hybrid)",
        "own_inverter": "mit eigenem Wechselrichter",
        "rate": "Einspeisevergütung: {rate} ct/kWh",
        "unpaid": ", bei negativen Preisen keine Vergütung (§ 51 EEG, Börsenpreis {market})",
        "market_tariff": "aus dem Tarif {title}",
        "purchase": "Anschaffung: {items}",
        "purchase_item": "{part} {cost} seit {date}",
        "part_pv": "PV",
        "part_battery": "Speicher",
        "and": " und ",
        "solar_started": "Ersparnis gerechnet seit {date}",
        "role_feed_in": "Einspeisezähler",
        "role_pv": "PV-Zähler",
        "role_battery": "Speicherzähler",
        "hint_solar_meter_missing": (
            "{role} {entity} gibt es nicht: keine neuen Stunden in der "
            "Ersparnis, bis er wieder da ist oder hier ein anderer gewählt ist."
        ),
        "hint_battery_meter_missing": (
            "{role} {entity} gibt es nicht: er zählt als 0, die Ersparnis "
            "stimmt nicht, bis er wieder da ist oder hier ein anderer gewählt "
            "ist."
        ),
        "hint_no_battery": (
            "Ohne Speicherzähler keine Sensoren „Ersparnis Speicher“ (nur mit "
            "Speicher nötig)."
        ),
        "hint_no_market": (
            "„Keine Vergütung bei negativen Preisen“ ohne Börsenpreis (weder "
            "unter „Börsenpreis für § 51“ noch ein Börsenpreis-Tarif): alle "
            "Stunden fehlen in der Ersparnis."
        ),
        "hint_market_missing": (
            "Börsenpreis-Sensor {entity} für § 51 gibt es nicht: keine neuen "
            "Preise, Stunden ohne Börsenpreis fehlen in der Ersparnis."
        ),
        "hint_no_purchase": (
            "Ohne Anschaffung {parts} (unter „Anschaffung“): kein „bezahlt "
            "gemacht“ dafür."
        ),
    },
    "en": {
        "configured": "**Set up**",
        "missing": "**Missing**",
        "meter": "Grid purchase meter: {name}",
        "started": (
            "Booking since {date}; the time before through the actions "
            "“Compare tariffs” and “Import statistics”"
        ),
        "tariffs": "Tariffs: {count} ({names})",
        "current": "My current tariff: {name}",
        "solar_battery": "PV and battery: PV with battery",
        "solar_pv": "PV and battery: PV without battery",
        "hint_meter_missing": (
            "Grid purchase meter {entity} does not exist: no new values until "
            "it is back or another one is chosen here."
        ),
        "hint_no_tariff": (
            "No tariff: nothing to compute – add one under “Add tariff”."
        ),
        "hint_one_tariff": (
            "Only one tariff: nothing to compare – more under “Add tariff”."
        ),
        "hint_no_current": (
            "No “My current tariff”: no sensors “Difference to current "
            "tariff” – set it in the tariff under “Edit tariff”."
        ),
        "hint_no_solar": (
            "No “PV and battery”: no sensors “Saving by PV” and “Saving by "
            "battery” (only needed with an own plant)."
        ),
        # PV and battery
        "feed_in": "Feed-in meter: {name}",
        "pv": "PV meter: {name}",
        "battery": "Battery: charged {charged}, discharged {discharged}, {coupling}",
        "same_inverter": "on the same inverter as the PV (hybrid)",
        "own_inverter": "with its own inverter",
        "rate": "Feed-in tariff: {rate} ct/kWh",
        "unpaid": ", no payment at negative prices (§ 51 EEG, exchange price {market})",
        "market_tariff": "of the tariff {title}",
        "purchase": "Purchase: {items}",
        "purchase_item": "{part} {cost} since {date}",
        "part_pv": "PV",
        "part_battery": "battery",
        "and": " and ",
        "solar_started": "Saving computed since {date}",
        "role_feed_in": "Feed-in meter",
        "role_pv": "PV meter",
        "role_battery": "Battery meter",
        "hint_solar_meter_missing": (
            "{role} {entity} does not exist: no new hours in the saving until "
            "it is back or another one is chosen here."
        ),
        "hint_battery_meter_missing": (
            "{role} {entity} does not exist: it counts as 0, the saving is "
            "wrong until it is back or another one is chosen here."
        ),
        "hint_no_battery": (
            "Without the battery meters no sensors “Saving by battery” (only "
            "needed with a battery)."
        ),
        "hint_no_market": (
            "“No payment at negative prices” without an exchange price "
            "(neither under “Exchange price for § 51” nor an exchange price "
            "tariff): all hours are missing in the saving."
        ),
        "hint_market_missing": (
            "Exchange price sensor {entity} for § 51 does not exist: no new "
            "prices, hours without an exchange price are missing in the saving."
        ),
        "hint_no_purchase": (
            "Without the purchase of {parts} (under “Purchase”): no “paid back” for it."
        ),
    },
}


def _words(german: bool) -> dict[str, str]:
    return _WORDS["de" if german else "en"]


def _quoted(text: str, german: bool) -> str:
    """A name in quotes, markdown characters escaped."""
    text = text.translate(_MARKDOWN)
    return f"„{text}“" if german else f"“{text}”"


def _name(source: Source, german: bool) -> str:
    """The entity's name, its id without a state."""
    if source.name:
        return _quoted(source.name, german)
    return f"`{source.entity_id}`"


def _markdown(words: Mapping[str, str], lines: list[str], missing: list[str]) -> str:
    blocks = [
        "\n".join([words[heading], *(f"- {line}" for line in items)])
        for heading, items in (("configured", lines), ("missing", missing))
        if items
    ]
    return "\n\n".join(blocks)


def entry_summary(
    meter: Source,
    tariffs: Sequence[Tariff],
    solar: Mapping[str, Any] | None,
    *,
    started: date | None,
    german: bool,
) -> str:
    """The summary of the entry: the meter, since when it books, the tariffs
    and the current one, PV and battery; what is missing.

    `solar` is the data of the subentry "PV and battery" (None: none);
    `started` the German local day the booking started (None: the entry is
    not loaded).
    """
    words = _words(german)
    lines = [words["meter"].format(name=_name(meter, german))]
    if started is not None:
        lines.append(words["started"].format(date=_date(started, german)))
    if tariffs:
        names = ", ".join(_quoted(t.title, german) for t in tariffs)
        lines.append(words["tariffs"].format(count=len(tariffs), names=names))
    # The first marked one, as the sensors take it (MeterRuntime.current).
    current = next((t for t in tariffs if t.current), None)
    if current is not None:
        lines.append(words["current"].format(name=_quoted(current.title, german)))
    if solar is not None:
        battery = bool(
            solar.get(CONF_CHARGED_ENTITY) and solar.get(CONF_DISCHARGED_ENTITY)
        )
        lines.append(words["solar_battery" if battery else "solar_pv"])

    missing: list[str] = []
    if meter.name is None:
        missing.append(
            words["hint_meter_missing"].format(entity=f"`{meter.entity_id}`")
        )
    if not tariffs:
        missing.append(words["hint_no_tariff"])
    elif len(tariffs) == 1:
        missing.append(words["hint_one_tariff"])
    elif current is None:
        missing.append(words["hint_no_current"])
    if solar is None:
        missing.append(words["hint_no_solar"])
    return _markdown(words, lines, missing)


def solar_summary(
    data: Mapping[str, Any],
    sources: Mapping[str, Source],
    *,
    market: Source | None,
    market_tariff: str | None,
    started: date | None,
    german: bool,
) -> str:
    """The summary of the subentry "PV and battery": its meters, the feed-in
    tariff with section 51, the purchase; what is missing.

    `sources` are the meters by their key in `data`. `market` is the
    exchange price sensor for section 51 the sensors use: the one of the
    subentry, else that of the first exchange price tariff (then
    `market_tariff` is its title); None without either. `started` is the
    German local day the saving is computed from (None: not loaded).
    """
    words = _words(german)

    def name(key: str) -> str:
        return _name(sources.get(key) or Source(str(data.get(key))), german)

    lines = [
        words["feed_in"].format(name=name(CONF_FEED_IN_ENTITY)),
        words["pv"].format(name=name(CONF_PV_ENTITY)),
    ]
    # Only with both meters there is a battery (runtime.has_battery).
    battery = bool(data.get(CONF_CHARGED_ENTITY) and data.get(CONF_DISCHARGED_ENTITY))
    if battery:
        coupling = "same_inverter" if data.get(CONF_SAME_INVERTER) else "own_inverter"
        lines.append(
            words["battery"].format(
                charged=name(CONF_CHARGED_ENTITY),
                discharged=name(CONF_DISCHARGED_ENTITY),
                coupling=words[coupling],
            )
        )
    rate = words["rate"].format(
        rate=_number(float(data.get(CONF_FEED_IN_RATE) or 0), german)
    )
    unpaid = bool(data.get(CONF_NEGATIVE_UNPAID))
    if unpaid and market is not None:
        source = _name(market, german)
        if market_tariff is not None:
            source += " " + words["market_tariff"].format(
                title=_quoted(market_tariff, german)
            )
        rate += words["unpaid"].format(market=source)
    lines.append(rate)
    # What payback.py counts: a cost with its day; the battery's from the
    # PV's day without its own, and only with the battery meters.
    bought = purchases(data)
    if bought:
        items = ", ".join(
            words["purchase_item"].format(
                part=words[f"part_{part}"],
                cost=_euro(bought[part].cost, german),
                date=_date(bought[part].since, german),
            )
            for part in (PV, BATTERY)
            if part in bought
        )
        lines.append(words["purchase"].format(items=items))
    if started is not None:
        lines.append(words["solar_started"].format(date=_date(started, german)))

    missing: list[str] = []
    for key, role in (
        (CONF_FEED_IN_ENTITY, "role_feed_in"),
        (CONF_PV_ENTITY, "role_pv"),
        (CONF_CHARGED_ENTITY, "role_battery"),
        (CONF_DISCHARGED_ENTITY, "role_battery"),
    ):
        source = sources.get(key)
        if not data.get(key) or source is None or source.name is not None:
            continue
        # A missing battery meter counts as 0 (MeterRuntime.solar_flows),
        # without feed-in or PV meter the hour is left out.
        hint = (
            "hint_battery_meter_missing"
            if role == "role_battery"
            else "hint_solar_meter_missing"
        )
        missing.append(
            words[hint].format(role=words[role], entity=f"`{source.entity_id}`")
        )
    if not battery:
        missing.append(words["hint_no_battery"])
    if unpaid and market is None:
        missing.append(words["hint_no_market"])
    elif unpaid and market is not None and market.name is None:
        # Without its prices the hour is left out (solar._paid_share).
        missing.append(
            words["hint_market_missing"].format(entity=f"`{market.entity_id}`")
        )
    parts = [PV] + ([BATTERY] if battery else [])
    if without := [words[f"part_{p}"] for p in parts if p not in bought]:
        missing.append(
            words["hint_no_purchase"].format(parts=words["and"].join(without))
        )
    return _markdown(words, lines, missing)
