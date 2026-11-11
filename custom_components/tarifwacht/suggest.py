"""Suggested values for the setup forms, from what is set up already.

Copies: einspeisewacht/custom_components/einspeisewacht/suggest.py (derived).

Nothing new to fill in: the meter comes from the grid import of the energy
dashboard, the price sensor from another tariff of the same kind in the entry,
the Einspeisewacht (exchange price) or the EPEX Spot integration. A suggestion
is only a preset: the field still takes any sensor, and the usual checks run
when the form is sent.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_KIND, CONF_PRICE_ENTITY, KIND_DYNAMIC_MARKET, KIND_DYNAMIC_TOTAL

_LOGGER = logging.getLogger(__name__)

EINSPEISEWACHT = "einspeisewacht"
# Key of the Einspeisewacht's exchange price sensor in its entry data.
EINSPEISEWACHT_PRICE = "price_entity"
EPEX_SPOT = "epex_spot"
# EPEX Spot's unique ids are f"{source} {key}" (mampfes/ha_epex_spot 4.1.0,
# commit 2aad1eb: __init__.py L275; keys in sensor.py L54 and L89).
EPEX_KEYS = {KIND_DYNAMIC_MARKET: "MarketPrice", KIND_DYNAMIC_TOTAL: "Total Price"}


def grid_import_stats(prefs: Mapping[str, Any] | None) -> list[str]:
    """Statistic ids of the grid import in the energy dashboard's preferences.

    One grid source per connection with `stat_energy_from`; the older format
    with a `flow_from` list is migrated by Home Assistant when it loads the
    preferences (2026.3 and later) and only read to be safe.
    """
    found: list[str] = []
    for source in (prefs or {}).get("energy_sources") or []:
        if source.get("type") != "grid":
            continue
        if "flow_from" in source:
            stats = [flow.get("stat_energy_from") for flow in source["flow_from"] or []]
        else:
            stats = [source.get("stat_energy_from")]
        for stat in stats:
            if stat and stat not in found:
                found.append(stat)
    return found


def epex_price_sensor(entries: Iterable[er.RegistryEntry], kind: str) -> str | None:
    """The EPEX Spot sensor for a dynamic tariff of this kind: the market price
    for "exchange price plus surcharges", the total price for a total-price
    sensor. With several EPEX Spot entries the first by entity id."""
    key = EPEX_KEYS.get(kind)
    if key is None:
        return None
    matches = sorted(
        entry.entity_id
        for entry in entries
        if entry.platform == EPEX_SPOT
        and entry.domain == "sensor"
        and entry.disabled_by is None
        and entry.unique_id.endswith(f" {key}")
    )
    return matches[0] if matches else None


def suggested_price(
    hass: HomeAssistant, kind: str, tariffs: Iterable[Mapping[str, Any]] = ()
) -> str | None:
    """Price sensor to suggest for a new dynamic tariff of this kind.

    First the sensor of another tariff of the same kind in the entry (a second
    exchange tariff mostly differs only in its surcharges), then for the
    exchange price the Einspeisewacht's, then EPEX Spot's.
    """
    for data in tariffs:
        if data.get(CONF_KIND) == kind and (entity := data.get(CONF_PRICE_ENTITY)):
            return entity
    if kind == KIND_DYNAMIC_MARKET:
        for entry in hass.config_entries.async_entries(
            EINSPEISEWACHT, include_ignore=False
        ):
            if entity := entry.data.get(EINSPEISEWACHT_PRICE):
                return entity
    return epex_price_sensor(er.async_get(hass).entities.values(), kind)


async def async_suggested_meter(hass: HomeAssistant, in_use: set[str]) -> str | None:
    """The grid import meter of the energy dashboard, if it is a sensor that no
    Tarifwacht entry reads yet."""
    if "energy" not in hass.config.components:
        return None
    try:
        # Imported here: without the energy dashboard nothing is suggested,
        # and a change to its internals only loses the suggestion.
        from homeassistant.components.energy.data import async_get_manager

        manager = await async_get_manager(hass)
        stats = grid_import_stats(manager.data)
    except Exception as err:  # a suggestion must never block the setup
        _LOGGER.debug("No meter suggestion from the energy dashboard: %s", err)
        return None
    for stat in stats:
        if (
            stat.startswith("sensor.")
            and stat not in in_use
            and hass.states.get(stat) is not None
        ):
            return stat
    return None
