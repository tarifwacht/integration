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
    CONF_BONUS,
    CONF_BONUS_DATE,
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
    CONF_MODUL3,
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
from .modul3 import modul3_from_data
from .tariffs import (
    BasePeriod,
    ComposedPrice,
    FixedPrice,
    FixedWithGridFee,
    PriceSource,
    Tariff,
)

# Modul 3 of a fixed price: the standard grid fee contained in the price
# (ct/kWh net) and the VAT on the difference (percent), kept with the windows.
MODUL3_STANDARD = "standard"
MODUL3_VAT = "vat"


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
        return (CONF_PRICE, CONF_MODUL3, *base)
    if kind == KIND_DYNAMIC_MARKET:
        return (CONF_GRID_FEE, CONF_LEVIES, CONF_MARGIN, CONF_VAT, CONF_MODUL3, *base)
    return base


def change_start(change: Mapping[str, Any]) -> datetime:
    """A change applies from local midnight of its date (UTC instant)."""
    day = date.fromisoformat(change[CONF_FROM])
    return datetime.combine(day, time(), BERLIN).astimezone(UTC)


def bonus_of(data: Mapping[str, Any]) -> tuple[float, datetime | None]:
    """The tariff's one-off bonus (EUR) and its instant: local midnight of
    its date, like a price change. (0, None) without one."""
    amount = float(data.get(CONF_BONUS) or 0)
    day = data.get(CONF_BONUS_DATE)
    if amount <= 0 or not day:
        return 0.0, None
    return amount, change_start({CONF_FROM: day})


# What a tariff's own costs do not depend on (the current tariff only moves
# the differences), and what changes them only from a date on.
_NOT_OWN_COSTS = (CONF_CURRENT,)
_FROM_A_DATE = (CONF_CHANGES, CONF_BONUS, CONF_BONUS_DATE)


def stale_since(
    old: Mapping[str, Any], new: Mapping[str, Any]
) -> tuple[bool, datetime | None]:
    """Whether a changed tariff changes its own costs, and from when.

    (False, None): unchanged. (True, moment): from that UTC instant on -
    the earliest price change added, removed or altered, or the bonus's
    date (old or new). (True, None): from the start (the values from the
    start, Modul 3 from the start, the kind or the price sensor).
    """

    def rest(data: Mapping[str, Any]) -> dict[str, Any]:
        skip = (*_NOT_OWN_COSTS, *_FROM_A_DATE)
        return {k: v for k, v in data.items() if k not in skip}

    if rest(old) != rest(new):
        return True, None
    moments: list[datetime] = []
    before = {c[CONF_FROM]: c for c in old.get(CONF_CHANGES) or []}
    after = {c[CONF_FROM]: c for c in new.get(CONF_CHANGES) or []}
    for day in before.keys() | after.keys():
        if before.get(day) != after.get(day):
            moments.append(change_start({CONF_FROM: day}))
    if (old_bonus := bonus_of(old)) != (new_bonus := bonus_of(new)):
        moments += [at for _, at in (old_bonus, new_bonus) if at is not None]
    if not moments:
        return False, None
    return True, min(moments)


def state_at(data: Mapping[str, Any], day: date) -> dict[str, Any]:
    """The tariff's values valid on `day`: the start values plus all changes
    from before or on that day."""
    values = {k: v for k, v in data.items() if k != CONF_CHANGES}
    for change in sorted(data.get(CONF_CHANGES, []), key=lambda c: c[CONF_FROM]):
        if date.fromisoformat(change[CONF_FROM]) <= day:
            values.update({k: v for k, v in change.items() if k != CONF_FROM})
    return values


def tariff_from_data(
    data: Mapping[str, Any],
    price_table: Callable[[str], PriceSource],
    market_table: Callable[[str], PriceSource] | None = None,
) -> Tariff:
    """The engine's tariff with its later price states (`changes`) and its
    one-off bonus.

    `price_table` returns the prices of a price sensor; `market_table`, if
    given, those of an exchange price sensor (e.g. completed from SMARD.de).
    """
    tables = (price_table, market_table or price_table)
    tariff = _single_tariff(data, *tables)
    bonus, bonus_at = bonus_of(data)
    if bonus_at is not None:
        tariff = replace(tariff, bonus=bonus, bonus_at=bonus_at)
    changes = sorted(data.get(CONF_CHANGES, []), key=lambda c: c[CONF_FROM])
    if not changes:
        return tariff
    states = tuple(
        (
            change_start(change),
            _single_tariff(
                state_at(data, date.fromisoformat(change[CONF_FROM])), *tables
            ),
        )
        for change in changes
    )
    return replace(tariff, changes=states)


def _single_tariff(
    data: Mapping[str, Any],
    price_table: Callable[[str], PriceSource],
    market_table: Callable[[str], PriceSource],
) -> Tariff:
    """One price state; the callables return the prices of a price sensor."""
    kind = data[CONF_KIND]
    prices: PriceSource
    if kind == KIND_FIXED:
        modul3_data = data.get(CONF_MODUL3) or {}
        standard = float(modul3_data.get(MODUL3_STANDARD) or 0)
        modul3 = modul3_from_data(modul3_data, standard, BERLIN)
        price = float(data[CONF_PRICE]) / 100
        prices = (
            FixedPrice(price)
            if modul3 is None
            else FixedWithGridFee(
                price,
                modul3.standard,
                float(modul3_data.get(MODUL3_VAT) or 0) / 100,
                modul3.fee,
            )
        )
    elif kind == KIND_DYNAMIC_TOTAL:
        prices = price_table(data[CONF_PRICE_ENTITY])
    elif kind == KIND_DYNAMIC_MARKET:
        modul3 = modul3_from_data(
            data.get(CONF_MODUL3) or {}, float(data.get(CONF_GRID_FEE) or 0), BERLIN
        )
        surcharge = surcharge_ct(data)
        if modul3 is not None:
            # The grid fee depends on the quarter hour.
            surcharge -= float(data.get(CONF_GRID_FEE) or 0)
        prices = ComposedPrice(
            market_table(data[CONF_PRICE_ENTITY]),
            surcharge / 100,
            float(data.get(CONF_VAT) or 0) / 100,
            grid_fee=modul3.fee if modul3 is not None else None,
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


def initial_fixed_tariff(config: Mapping[str, Any]) -> dict[str, Any]:
    """Data of the fixed tariff of the setup form: the current one."""
    return {
        CONF_KEY: TARIFF_FIXED,
        CONF_KIND: KIND_FIXED,
        CONF_PRICE: float(config[CONF_FIXED_PRICE]),
        CONF_BASE_PRICE: float(config.get(CONF_FIXED_BASE) or 0),
        CONF_BASE_PERIOD: BasePeriod.MONTH.value,
        CONF_CURRENT: True,
    }


def initial_tariffs(
    config: Mapping[str, Any], titles: tuple[str, str]
) -> list[tuple[str, dict[str, Any]]]:
    """(title, data) of the two tariffs of 0.1.0b1, for its migration.

    The keys keep the unique ids of that version's entities. The fixed
    tariff is the current one.
    """
    fixed_title, dynamic_title = titles
    return [
        (fixed_title, initial_fixed_tariff(config)),
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
