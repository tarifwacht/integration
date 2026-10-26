"""Tariff definitions as stored in config subentries. Pure Python.

A subentry's data describes one tariff; `tariff_from_data` turns it into the
engine's `Tariff`. Prices are entered as on price sheets (ct/kWh, VAT in
percent) and converted to EUR/kWh and fractions here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Any

from .const import (
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
    TARIFF_DYNAMIC,
    TARIFF_FIXED,
)
from .prices import PriceTable
from .tariffs import BasePeriod, ComposedPrice, FixedPrice, PriceSource, Tariff


def tariff_key(subentry_id: str, data: Mapping[str, Any]) -> str:
    """Stable id of a tariff: kept from 0.1.0b1, else the subentry id."""
    return str(data.get(CONF_KEY) or subentry_id)


def price_entity(data: Mapping[str, Any]) -> str | None:
    """The price sensor a tariff reads, None for a fixed price."""
    return data.get(CONF_PRICE_ENTITY) if data[CONF_KIND] != KIND_FIXED else None


def surcharge_ct(data: Mapping[str, Any]) -> float:
    """Net surcharges in ct/kWh of a tariff built from the exchange price."""
    return sum(
        float(data.get(k) or 0) for k in (CONF_GRID_FEE, CONF_LEVIES, CONF_MARGIN)
    )


def change_fields(kind: str) -> tuple[str, ...]:
    """What a price change of a tariff of this kind may set."""
    base = (CONF_BASE_PRICE, CONF_BASE_PERIOD)
    if kind == KIND_FIXED:
        return (CONF_PRICE, *base)
    if kind == KIND_DYNAMIC_MARKET:
        return (CONF_GRID_FEE, CONF_LEVIES, CONF_MARGIN, CONF_VAT, *base)
    return base


def change_start(change: Mapping[str, Any]) -> datetime:
    """A change applies from local midnight of its date (UTC instant)."""
    day = date.fromisoformat(change[CONF_FROM])
    return datetime.combine(day, time(), BERLIN).astimezone(UTC)


def state_at(data: Mapping[str, Any], day: date) -> dict[str, Any]:
    """The tariff's values valid on `day`: the start values plus all changes
    from before or on that day."""
    values = {k: v for k, v in data.items() if k != CONF_CHANGES}
    for change in sorted(data.get(CONF_CHANGES, []), key=lambda c: c[CONF_FROM]):
        if date.fromisoformat(change[CONF_FROM]) <= day:
            values.update({k: v for k, v in change.items() if k != CONF_FROM})
    return values


def tariff_from_data(
    data: Mapping[str, Any], price_table: Callable[[str], PriceTable]
) -> Tariff:
    """The engine's tariff with its later price states (`changes`)."""
    tariff = _single_tariff(data, price_table)
    changes = sorted(data.get(CONF_CHANGES, []), key=lambda c: c[CONF_FROM])
    if not changes:
        return tariff
    states = tuple(
        (
            change_start(change),
            _single_tariff(
                state_at(data, date.fromisoformat(change[CONF_FROM])), price_table
            ),
        )
        for change in changes
    )
    return replace(tariff, changes=states)


def _single_tariff(
    data: Mapping[str, Any], price_table: Callable[[str], PriceTable]
) -> Tariff:
    """One price state; `price_table` returns the table of a price sensor."""
    kind = data[CONF_KIND]
    prices: PriceSource
    if kind == KIND_FIXED:
        prices = FixedPrice(float(data[CONF_PRICE]) / 100)
    elif kind == KIND_DYNAMIC_TOTAL:
        prices = price_table(data[CONF_PRICE_ENTITY])
    elif kind == KIND_DYNAMIC_MARKET:
        prices = ComposedPrice(
            price_table(data[CONF_PRICE_ENTITY]),
            surcharge_ct(data) / 100,
            float(data.get(CONF_VAT) or 0) / 100,
        )
    else:
        raise ValueError(f"unknown tariff kind {kind}")
    return Tariff(
        prices,
        float(data.get(CONF_BASE_PRICE) or 0),
        BasePeriod(data.get(CONF_BASE_PERIOD) or BasePeriod.MONTH),
    )


def default_titles(language: str) -> tuple[str, str]:
    """Names of the two tariffs of the setup form (also the 0.1.0b1 names)."""
    if language.startswith("de"):
        return ("Festpreis", "Dynamisch")
    return ("Fixed price", "Dynamic")


def initial_tariffs(
    config: Mapping[str, Any], titles: tuple[str, str]
) -> list[tuple[str, dict[str, Any]]]:
    """(title, data) of the fixed and the dynamic tariff of the setup form.

    Used for new entries and to migrate entries of 0.1.0b1; the keys keep the
    unique ids of that version's entities. The fixed tariff is the current one.
    """
    fixed_title, dynamic_title = titles
    return [
        (
            fixed_title,
            {
                CONF_KEY: TARIFF_FIXED,
                CONF_KIND: KIND_FIXED,
                CONF_PRICE: float(config[CONF_FIXED_PRICE]),
                CONF_BASE_PRICE: float(config.get(CONF_FIXED_BASE) or 0),
                CONF_BASE_PERIOD: BasePeriod.MONTH.value,
                CONF_CURRENT: True,
            },
        ),
        (
            dynamic_title,
            {
                CONF_KEY: TARIFF_DYNAMIC,
                CONF_KIND: KIND_DYNAMIC_TOTAL,
                CONF_PRICE_ENTITY: config[CONF_DYNAMIC_PRICE],
                CONF_BASE_PRICE: float(config.get(CONF_DYNAMIC_BASE) or 0),
                CONF_BASE_PERIOD: BasePeriod.MONTH.value,
                CONF_CURRENT: False,
            },
        ),
    ]


def entry_data(config: Mapping[str, Any]) -> dict[str, Any]:
    """What stays in the config entry itself: name and meter."""
    return {CONF_NAME: config[CONF_NAME], CONF_METER: config[CONF_METER]}
