"""What a tariff shows of itself: the summary at the top of its gear menu
and the attributes of its sensor "Energy price now". Pure Python.

A tariff is a subentry with its values from the start and later price
states (`changes`). The menu text names the kind, what applies today, every
price state (future ones marked), the bonus, Modul 3 and whether it is the
current tariff - in German or English after the language of Home Assistant
(like the dates of "Remove a price change"). Menu descriptions render
markdown: one paragraph per part, the price states as a list.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from .const import (
    BERLIN,
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_BONUS,
    CONF_BONUS_DATE,
    CONF_CHANGES,
    CONF_CURRENT,
    CONF_FROM,
    CONF_GRID_FEE,
    CONF_KIND,
    CONF_LEVIES,
    CONF_MARGIN,
    CONF_MODUL3,
    CONF_PRICE,
    CONF_VAT,
    KIND_DYNAMIC_MARKET,
    KIND_DYNAMIC_TOTAL,
    KIND_FIXED,
)
from .tariff_config import state_at

_WORDS: dict[str, dict[str, str]] = {
    "de": {
        KIND_FIXED: "Festpreis",
        KIND_DYNAMIC_MARKET: "Börsenpreis plus Aufschläge",
        KIND_DYNAMIC_TOTAL: "Sensor mit Gesamtpreis",
        "month": "Monat",
        "year": "Jahr",
        "today": "heute",
        "since": "seit {date}",
        "start": "ab Beginn",
        "from": "ab {date}",
        "coming": "kommt",
        "prices": "Preise:",
        "no_changes": "Preisänderungen: keine",
        "exchange": "Börsenpreis",
        "grid_fee": "Netzentgelt",
        "levies": "Abgaben",
        "margin": "Aufschlag",
        "net": "netto",
        "vat": "MwSt.",
        "base": "Grundpreis",
        "no_base": "ohne Grundpreis",
        "sensor": "Preissensor „{name}“",
        "bonus": "Bonus: {amount} am {date}",
        "no_bonus": "Bonus: –",
        "modul3": "Modul 3",
        "on": "an",
        "off": "aus",
        "current": "Mein aktueller Tarif: {value}",
        "yes": "ja",
        "no": "nein",
        "edit_hint": "Diese Werte gelten ab Beginn des Tarifs. Gilt ab einem "
        "späteren Datum ein neuer Preis: zurück und „Preisänderung ab einem "
        "Datum hinzufügen“.",
    },
    "en": {
        KIND_FIXED: "Fixed price",
        KIND_DYNAMIC_MARKET: "Exchange price plus surcharges",
        KIND_DYNAMIC_TOTAL: "Sensor with the total price",
        "month": "month",
        "year": "year",
        "today": "today",
        "since": "since {date}",
        "start": "from the start",
        "from": "from {date}",
        "coming": "upcoming",
        "prices": "Prices:",
        "no_changes": "Price changes: none",
        "exchange": "exchange price",
        "grid_fee": "grid fee",
        "levies": "levies",
        "margin": "surcharge",
        "net": "net",
        "vat": "VAT",
        "base": "base price",
        "no_base": "no base price",
        "sensor": "price sensor “{name}”",
        "bonus": "Bonus: {amount} on {date}",
        "no_bonus": "Bonus: –",
        "modul3": "Modul 3",
        "on": "on",
        "off": "off",
        "current": "My current tariff: {value}",
        "yes": "yes",
        "no": "no",
        "edit_hint": "These values apply from the start of the tariff. A new "
        "price from a later date: go back and “Add a price change from a "
        "date”.",
    },
}

# Characters markdown would take as formatting in a sensor name.
_MARKDOWN = str.maketrans({c: f"\\{c}" for c in "\\`*_[]<>#|"})


def _words(german: bool) -> dict[str, str]:
    return _WORDS["de" if german else "en"]


def _number(value: float, german: bool, digits: int = 3) -> str:
    """27.75 -> "27,75" (German) or "27.75"; trailing zeros dropped."""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if german else text


def _euro(value: float, german: bool) -> str:
    """1234.5 -> "1.234,50 €" (German) or "1,234.50 €"."""
    text = f"{value:,.2f}"
    if german:
        text = text.translate(str.maketrans(",.", ".,"))
    return f"{text} €"


def _date(day: date, german: bool) -> str:
    return day.strftime("%d.%m.%Y") if german else day.isoformat()


def start_state(data: Mapping[str, Any]) -> dict[str, Any]:
    """The tariff's values from the start (before any price change)."""
    return {k: v for k, v in data.items() if k != CONF_CHANGES}


def price_states(data: Mapping[str, Any]) -> list[tuple[date | None, dict[str, Any]]]:
    """Every price state: (None, values from the start), then (date, values
    from that date on) per price change, in order."""
    changes = sorted(data.get(CONF_CHANGES) or [], key=lambda c: c[CONF_FROM])
    states: list[tuple[date | None, dict[str, Any]]] = [(None, start_state(data))]
    for change in changes:
        day = date.fromisoformat(change[CONF_FROM])
        states.append((day, state_at(data, day)))
    return states


def valid_since(data: Mapping[str, Any], today: date) -> date | None:
    """The date of the price change in force on `today`, None: the values
    from the start."""
    since = None
    for day, _ in price_states(data)[1:]:
        if day is not None and day <= today:
            since = day
    return since


def next_change(
    data: Mapping[str, Any], today: date
) -> tuple[date, dict[str, Any]] | None:
    """The first price state after `today` and its values."""
    for day, values in price_states(data)[1:]:
        if day is not None and day > today:
            return day, values
    return None


def modul3_on(values: Mapping[str, Any]) -> bool:
    """Whether a price state uses Modul 3."""
    return bool((values.get(CONF_MODUL3) or {}).get("active"))


def _quarters(values: Mapping[str, Any]) -> str:
    quarters = sorted(
        int(q) for q in (values.get(CONF_MODUL3) or {}).get("quarters") or []
    )
    if quarters == [1, 2, 3, 4]:
        return "Q1–Q4"
    return ", ".join(f"Q{q}" for q in quarters)


def _base(values: Mapping[str, Any], german: bool, *, label: bool) -> str:
    words = _words(german)
    amount = float(values.get(CONF_BASE_PRICE) or 0)
    if not amount:
        return words["no_base"]
    period = words[str(values.get(CONF_BASE_PERIOD) or "month")]
    text = f"{_euro(amount, german)}/{period}"
    return f"{words['base']} {text}" if label else text


def _market_parts(values: Mapping[str, Any], german: bool) -> str:
    """ "Netzentgelt 9 + Abgaben 5 + Aufschlag 2 ct (netto)": the surcharges
    that are set; "" without any."""
    words = _words(german)
    parts = [
        f"{words[key]} {_number(float(values.get(key) or 0), german)}"
        for key in (CONF_GRID_FEE, CONF_LEVIES, CONF_MARGIN)
        if float(values.get(key) or 0)
    ]
    if not parts:
        return ""
    return " + ".join(parts) + f" ct ({words['net']})"


def _vat(values: Mapping[str, Any], german: bool) -> str:
    vat = float(values.get(CONF_VAT) or 0)
    return f"{_words(german)['vat']} {_number(vat, german, 1)} %"


def state_text(
    kind: str,
    values: Mapping[str, Any],
    german: bool,
    *,
    today: bool = False,
    sensor: str | None = None,
) -> str:
    """One price state in a line; `today`: as what applies today, with the
    exchange price or the price sensor (its name, `sensor`)."""
    words = _words(german)
    # Today Modul 3 has its own part of the summary.
    modul3 = f", {words['modul3']}" if modul3_on(values) and not today else ""
    if kind == KIND_FIXED:
        price = f"{_number(float(values.get(CONF_PRICE) or 0), german)} ct/kWh"
        base = float(values.get(CONF_BASE_PRICE) or 0)
        text = f"{price} + {_base(values, german, label=False)}" if base else price
        return text + modul3
    if kind == KIND_DYNAMIC_MARKET:
        parts = [words["exchange"]] if today else []
        if surcharges := _market_parts(values, german):
            parts.append(surcharges)
        parts.append(_vat(values, german))
        joined = " + ".join(parts)
        return f"{joined}, {_base(values, german, label=True)}{modul3}"
    base = _base(values, german, label=True)
    if not today:
        return base
    name = (sensor or "?").translate(_MARKDOWN)
    return f"{words['sensor'].format(name=name)}, {base}"


def summary(
    data: Mapping[str, Any],
    today: date,
    *,
    german: bool,
    sensor_name: str | None = None,
) -> str:
    """The text at the top of the tariff's gear menu (markdown).

    `today` is the German local date; `sensor_name` the name of the price
    sensor (dynamic tariffs).
    """
    words = _words(german)
    kind = data[CONF_KIND]
    today_values = state_at(data, today)
    line = f"**{words[kind]}** · {words['today']}: " + state_text(
        kind, today_values, german, today=True, sensor=sensor_name
    )
    if (since := valid_since(data, today)) is not None:
        line += f" ({words['since'].format(date=_date(since, german))})"
    paragraphs = [line]
    states = price_states(data)
    if len(states) == 1:
        paragraphs.append(words["no_changes"])
    else:
        items = [words["prices"]]
        for day, values in states:
            when = (
                words["start"]
                if day is None
                else words["from"].format(date=_date(day, german))
            )
            item = f"- {when}: {state_text(kind, values, german)}"
            if day is not None and day > today:
                item += f" **({words['coming']})**"
            items.append(item)
        paragraphs.append("\n".join(items))
    extras = []
    amount = float(data.get(CONF_BONUS) or 0)
    if amount > 0 and data.get(CONF_BONUS_DATE):
        extras.append(
            words["bonus"].format(
                amount=_euro(amount, german),
                date=_date(date.fromisoformat(str(data[CONF_BONUS_DATE])), german),
            )
        )
    else:
        extras.append(words["no_bonus"])
    if kind != KIND_DYNAMIC_TOTAL:
        modul3 = words["off"]
        if modul3_on(today_values):
            modul3 = f"{words['on']} ({_quarters(today_values)})"
        extras.append(f"{words['modul3']}: {modul3}")
    current = words["yes"] if data.get(CONF_CURRENT) else words["no"]
    extras.append(words["current"].format(value=current))
    paragraphs.append(" · ".join(extras))
    return "\n\n".join(paragraphs)


def edit_hint(german: bool) -> str:
    """The sentence under the description of "Edit prices from the start"."""
    return "\n\n" + _words(german)["edit_hint"]


def _values(kind: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """The values of a price state for attributes, with their units."""
    result: dict[str, Any] = {}
    if kind == KIND_FIXED:
        result["price_ct"] = float(values.get(CONF_PRICE) or 0)
    if kind == KIND_DYNAMIC_MARKET:
        for key in (CONF_GRID_FEE, CONF_LEVIES, CONF_MARGIN):
            result[f"{key}_ct"] = float(values.get(key) or 0)
        result["vat_percent"] = float(values.get(CONF_VAT) or 0)
    result["base_price_eur"] = float(values.get(CONF_BASE_PRICE) or 0)
    result["base_period"] = str(values.get(CONF_BASE_PERIOD) or "month")
    if kind != KIND_DYNAMIC_TOTAL:
        result["modul3"] = modul3_on(values)
    return result


def price_now_attributes(data: Mapping[str, Any], moment: datetime) -> dict[str, Any]:
    """Attributes of "Energy price now" at `moment`: base price and period
    valid today, since when the price state applies (None: from the start),
    the next price change, the bonus and whether Modul 3 applies in this
    calendar quarter."""
    kind = data[CONF_KIND]
    local = moment.astimezone(BERLIN)
    today = local.date()
    values = state_at(data, today)
    since = valid_since(data, today)
    attributes: dict[str, Any] = {
        "base_price_eur": float(values.get(CONF_BASE_PRICE) or 0),
        "base_period": str(values.get(CONF_BASE_PERIOD) or "month"),
        "valid_since": since.isoformat() if since is not None else None,
    }
    if (upcoming := next_change(data, today)) is not None:
        day, later = upcoming
        attributes["next_change"] = {"from": day.isoformat(), **_values(kind, later)}
    amount = float(data.get(CONF_BONUS) or 0)
    if amount > 0 and data.get(CONF_BONUS_DATE):
        attributes["bonus"] = {
            "amount_eur": amount,
            "date": str(data[CONF_BONUS_DATE]),
        }
    if kind != KIND_DYNAMIC_TOTAL:
        quarter = (local.month - 1) // 3 + 1
        quarters = {
            int(q) for q in (values.get(CONF_MODUL3) or {}).get("quarters") or []
        }
        attributes["modul3_active_now"] = modul3_on(values) and quarter in quarters
    return attributes
