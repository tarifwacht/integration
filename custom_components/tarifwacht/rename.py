"""Follow a source entity renamed in the entity registry. Pure Python.

An entry refers to its meter (entry data, also its unique id) and to the
price sensors of its tariffs (subentry data) by entity id. Home Assistant
moves the statistics along with a renamed entity; these references follow at
once (__init__.py). The stored state is keyed by entity id as well: the price
table of each sensor (live file and yearly archives) and the meter of the
last reading. The entry data keeps the renames (`CONF_RENAMED`) until the next
start has moved the stored state (runtime.py), so an entry that is not loaded
at the time catches up later.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .const import CONF_METER, CONF_PRICE_ENTITY, CONF_RENAMED
from .tariff_config import price_entity


def sources(data: Mapping[str, Any], tariffs: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every entity id the entry refers to: meter and price sensors."""
    found = {entity for t in tariffs if (entity := price_entity(t))}
    if meter := data.get(CONF_METER):
        found.add(meter)
    return found


def renamed_data(data: Mapping[str, Any], old: str, new: str) -> dict[str, Any]:
    """The entry data with `old` replaced by `new` and the rename noted.

    Renames since the last start are kept as {stored id: current id}: a chain
    A -> B -> C before the next start moves A's stored state to C, and
    renaming back drops the note.
    """
    result = dict(data)
    if data.get(CONF_METER) == old:
        result[CONF_METER] = new
    renames = {
        stored: new if current == old else current
        for stored, current in (data.get(CONF_RENAMED) or {}).items()
    }
    renames.setdefault(old, new)
    result[CONF_RENAMED] = {s: c for s, c in renames.items() if s != c}
    return result


def renamed_tariff(
    data: Mapping[str, Any], old: str, new: str
) -> dict[str, Any] | None:
    """The tariff data with its price sensor renamed; None if it reads another."""
    if price_entity(data) != old:
        return None
    return {**data, CONF_PRICE_ENTITY: new}


def renamed_unique_id(unique_id: str | None, old: str, new: str) -> str | None:
    """The unique id (the meter) after the rename; None if it does not name `old`."""
    return new if unique_id == old else None


def renamed_storage(
    data: Mapping[str, Any], renames: Mapping[str, str]
) -> Mapping[str, Any]:
    """Stored state (live file or yearly archive) under the current entity ids.

    All renames apply at once, so two sensors that swapped their ids swap
    their price tables. If a table already exists under the new id, its own
    prices take precedence and the renamed one only fills its gaps.
    """
    if not renames:
        return data
    result = dict(data)
    prices: Mapping[str, Any] = data.get("prices") or {}
    if any(source in renames for source in prices):
        moved: dict[str, Any] = {}
        # Tables that keep their id first: their prices take precedence.
        for source, table in sorted(
            prices.items(), key=lambda item: item[0] in renames
        ):
            target = renames.get(source, source)
            moved[target] = _merge(moved[target], table) if target in moved else table
        result["prices"] = moved
    meter: Mapping[str, Any] = data.get("meter") or {}
    if (source := meter.get("source")) in renames:
        result["meter"] = {**meter, "source": renames[source]}
    return result


def _merge(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    """Price tables per UTC day; values of `first` win, `second` fills gaps."""
    merged = dict(first)
    for day, values in second.items():
        mine = merged.get(day)
        if (
            isinstance(mine, list)
            and isinstance(values, list)
            and len(mine) == len(values)
        ):
            merged[day] = [
                a if a is not None else b for a, b in zip(mine, values, strict=True)
            ]
        else:
            merged.setdefault(day, values)
    return merged
