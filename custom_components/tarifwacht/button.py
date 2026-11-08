"""Button: a short report for a bug report (issue_report.py).

Tarifwacht's part of it: the sources by role ("meter", "tariff 2 price"),
the tariffs by kind and number with their prices from a fixed list of fields,
and a few lines on the bookings. Never the entry or tariff names (free text),
entity ids or the meter reading.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TarifwachtConfigEntry
from .const import (
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_CHANGES,
    CONF_CURRENT,
    CONF_FROM,
    CONF_GRID_FEE,
    CONF_KIND,
    CONF_LEVIES,
    CONF_MARGIN,
    CONF_METER,
    CONF_MODUL3,
    CONF_PRICE,
    CONF_SMARD_FILL,
    CONF_VAT,
    DOMAIN,
    KIND_DYNAMIC_MARKET,
    KIND_FIXED,
    VERSION,
)
from .entity import MeterEntity
from .frontend_resource import card_status
from .issue_report import Lines, build, show
from .modul3 import WindowError, parse_windows
from .runtime import MeterRuntime, tariff_subentries
from .smard_cache import DATA_SMARD
from .tariff_config import price_entity, tariff_key

NAME = "Tarifwacht"
METER_ROLE = "meter"
# Price fields of a tariff or a price change shown in the report (positive
# list): numbers and choices only, never the name or the price sensor.
PRICE_FIELDS = (
    CONF_PRICE,
    CONF_GRID_FEE,
    CONF_LEVIES,
    CONF_MARGIN,
    CONF_VAT,
    CONF_BASE_PRICE,
    CONF_BASE_PERIOD,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TarifwachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([IssueReport(entry)])


class IssueReport(MeterEntity, ButtonEntity):
    """A short report to copy into a bug report, as a notification: what an
    issue needs without the diagnostics download (issue_report.py)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: TarifwachtConfigEntry) -> None:
        super().__init__(entry, "issue_report")
        self._entry = entry

    async def async_press(self) -> None:
        entry = self._entry
        tariffs = [s.data for s in tariff_subentries(entry)]
        mapping = roles(entry.data[CONF_METER], tariffs)
        report = build(
            self.hass,
            DOMAIN,
            NAME,
            VERSION,
            entry,
            mapping=mapping,
            extra=entry_lines(self.hass, entry, entry.runtime_data, mapping),
            private=(METER_ROLE,),
            setting_lines=tariff_settings(tariffs),
        )
        show(self.hass, DOMAIN, NAME, entry, report)


def _label(number: int) -> str:
    return f"tariff {number}"


def roles(meter: str, tariffs: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """{role: entity id} of the sources: the meter and each tariff's price
    sensor, tariffs numbered in the order of their subentries."""
    mapping = {METER_ROLE: meter}
    for number, data in enumerate(tariffs, 1):
        if entity := price_entity(data):
            mapping[f"{_label(number)} price"] = entity
    return mapping


def _num(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except TypeError, ValueError:
        return "-"


def _prices(data: Mapping[str, Any]) -> list[str]:
    """The price fields set in a tariff or price change, as `field value`."""
    return [
        f"{key} {_num(data[key]) if key != CONF_BASE_PERIOD else data[key]}"
        for key in PRICE_FIELDS
        if data.get(key) is not None
    ]


def _windows(text: Any) -> str:
    """Modul 3 windows as parsed (minutes of the day), not the text typed in."""
    try:
        windows = parse_windows(str(text or ""))
    except WindowError:
        return "invalid"
    return (
        " ".join(
            f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}" for a, b in windows
        )
        or "none"
    )


def _modul3(data: Mapping[str, Any]) -> str:
    if not data.get("active"):
        return "off"
    quarters = ",".join(
        str(q) for q in sorted(int(q) for q in data.get("quarters", []))
    )
    return (
        f"NT {_num(data.get('nt'))} ct {_windows(data.get('nt_windows'))}, "
        f"HT {_num(data.get('ht'))} ct {_windows(data.get('ht_windows'))}, "
        f"quarters {quarters or '-'}"
    )


def tariff_settings(tariffs: Sequence[Mapping[str, Any]]) -> Lines:
    """Each tariff by number: kind, prices, Modul 3, SMARD.de, price changes.

    Fields from a positive list only (`PRICE_FIELDS` and the switches); the
    tariff's name and price sensor are left out.
    """
    lines: Lines = []
    for number, data in enumerate(tariffs, 1):
        label = _label(number)
        parts = [str(data.get(CONF_KIND))]
        if data.get(CONF_CURRENT):
            parts.append("current")
        parts += _prices(data)
        if data.get(CONF_KIND) == KIND_DYNAMIC_MARKET:
            parts.append(
                f"SMARD.de fill {'on' if data.get(CONF_SMARD_FILL) else 'off'}"
            )
        lines.append((label, ", ".join(parts)))
        if modul3 := data.get(CONF_MODUL3):
            lines.append((f"{label} modul 3", _modul3(modul3)))
        changes = sorted(data.get(CONF_CHANGES) or [], key=lambda c: c[CONF_FROM])
        for change in changes:
            parts = _prices(change)
            if CONF_MODUL3 in change:
                parts.append(f"modul 3 {_modul3(change[CONF_MODUL3] or {})}")
            lines.append((f"{label} from {change[CONF_FROM]}", ", ".join(parts)))
    return lines


def _time(value: datetime | None) -> str:
    return "-" if value is None else f"{value:%Y-%m-%d %H:%M} UTC"


def scrub(text: str, mapping: Mapping[str, str]) -> str:
    """An error text with every source's entity id replaced by its role."""
    for role, entity in sorted(mapping.items(), key=lambda i: -len(i[1])):
        text = text.replace(entity, role)
    return text


def entry_lines(
    hass: HomeAssistant,
    entry: TarifwachtConfigEntry,
    runtime: MeterRuntime,
    mapping: Mapping[str, str],
) -> Lines:
    """The state of the bookings: what diagnostics.py shows, in short, with
    roles instead of entity ids and no energy or cost totals."""
    engine = runtime.engine
    subentries = tariff_subentries(entry)
    kinds = Counter(str(s.data.get(CONF_KIND)) for s in subentries)
    current = next(
        (n for n, s in enumerate(subentries, 1) if s.data.get(CONF_CURRENT)), None
    )
    slots = [slot for slot, _ in engine.consumption.items()]
    lines: Lines = [
        (
            "tariffs",
            f"{len(subentries)} ("
            + ", ".join(f"{kind} {n}" for kind, n in sorted(kinds.items()))
            + f"), current: {_label(current) if current else 'none'}",
        ),
        ("started", _time(engine.started)),
        (
            "quarter hours booked",
            f"{len(slots)}, {_time(slots[0]) if slots else '-'} "
            f"to {_time(slots[-1]) if slots else '-'}",
        ),
        (
            "meter",
            f"last reading {_time(engine.meter.last_time)}, unit "
            + (
                "ok"
                if runtime.meter_unit_ok
                else f"not supported ({runtime.unknown_unit})"
            ),
        ),
        (
            "meter events",
            ", ".join(f"{k} {v}" for k, v in sorted(engine.meter_events.items()))
            or "none",
        ),
    ]
    if engine.backfill_until is not None or runtime.backfill_error:
        lines.append(
            (
                "backfill from recorder",
                f"until {_time(engine.backfill_until)}, error "
                + scrub(runtime.backfill_error or "none", mapping),
            )
        )
    for number, subentry in enumerate(subentries, 1):
        parts: list[str] = []
        if entity := price_entity(subentry.data):
            table = engine.prices.get(entity)
            parsed = engine.last_parse.get(entity)
            parts.append(f"{len(table) if table else 0} prices")
            if parsed is not None:
                minutes = (
                    f"{parsed.resolution.total_seconds() / 60:g} min"
                    if parsed.resolution
                    else "-"
                )
                parts.append(
                    f"format {parsed.format}, {minutes}, {parsed.skipped} skipped"
                )
            if entity in runtime.wrong_price_unit:
                parts.append(f"unit not supported ({runtime.wrong_price_unit[entity]})")
            if (until := engine.unpriced_until(entity)) is not None:
                parts.append(f"no prices before {_time(until)}")
        elif subentry.data.get(CONF_KIND) != KIND_FIXED:
            parts.append("no price sensor")
        if totals := engine.totals.get(tariff_key(subentry.subentry_id, subentry.data)):
            parts.append(f"{len(totals.pending)} quarter hours waiting for a price")
            if totals.energy_without_price > 0:
                parts.append("energy without price")
        lines.append((_label(number), ", ".join(parts) or "-"))
    lines.append(
        (
            "comparison leaves energy out",
            "yes" if engine.comparison.energy_left_out else "no",
        )
    )
    market = [
        n
        for n, s in enumerate(subentries, 1)
        if s.data.get(CONF_KIND) == KIND_DYNAMIC_MARKET
    ]
    if market:
        fill = [n for n in market if subentries[n - 1].data.get(CONF_SMARD_FILL)]
        cache = hass.data.get(DATA_SMARD)
        stored = (
            f"{len(cache.table)} prices, years "
            + (", ".join(str(y) for y in sorted(cache.table.years())) or "-")
            if cache is not None
            else "not loaded"
        )
        lines.append(
            (
                "SMARD.de",
                f"fill agreed for {', '.join(_label(n) for n in fill) or 'none'}; "
                f"stored {stored}",
            )
        )
    if runtime.past_prices_error:
        lines.append(("past prices error", scrub(runtime.past_prices_error, mapping)))
    lines.append(("card", card_status(hass)))
    if runtime.own_entities:
        own = {entity: role for role, entity in mapping.items()}
        lines.append(
            (
                "own sensors as source",
                ", ".join(own.get(e, "?") for e in runtime.own_entities),
            )
        )
    return lines
