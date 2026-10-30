"""Tarifwacht: what your grid purchase would have cost under other tariffs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigSubentry,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import CALLBACK_TYPE, Event, HassJob, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .const import CONF_KEY, DOMAIN, SUBENTRY_TARIFF, TARIFF_DYNAMIC
from .rename import renamed_data, renamed_tariff, renamed_unique_id, sources
from .runtime import MeterRuntime, tariff_subentries
from .services import async_setup_services
from .tariff_config import default_titles, entry_data, initial_tariffs

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

type TarifwachtConfigEntry = ConfigEntry[MeterRuntime]

# Renames come in bursts ("recreate entity IDs" of a device): the entries
# reload once, this long after the last one (as Wärmewacht and Speicherwacht).
RENAME_RELOAD_DELAY = timedelta(seconds=3)
# Entries whose sources were renamed and which wait for that reload.
RENAMED: HassKey[set[str]] = HassKey(f"{DOMAIN}_renamed")
# A reload picks up the renamed sources; a disabled or unloaded entry reads
# them (and moves its stored state) at its next setup.
RELOAD_STATES = (
    ConfigEntryState.LOADED,
    ConfigEntryState.SETUP_IN_PROGRESS,
    ConfigEntryState.SETUP_RETRY,
    ConfigEntryState.SETUP_ERROR,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions and follow renamed sources (once, for all entries)."""
    async_setup_services(hass)
    _async_follow_renames(hass)
    return True


@callback
def _async_follow_renames(hass: HomeAssistant) -> None:
    """Follow source entities renamed in the entity registry.

    One listener for all entries (as Wärmewacht and Speicherwacht) also sees
    entries that are reloading, disabled or failed to set up, and an id
    renamed again before the reload. Meter (entry data, unique id) and price
    sensors (tariff subentries) change at once; the entry data notes the
    rename, so the next start moves the stored prices and the meter's last
    reading to the new id (runtime.py). The reload follows when the burst is
    over. Removed entities are left to the repair issue "missing_entity".
    """
    waiting = hass.data.setdefault(RENAMED, set())
    cancel: CALLBACK_TYPE | None = None

    @callback
    def _reload(_now: datetime) -> None:
        nonlocal cancel
        cancel = None
        for entry_id in sorted(waiting):
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.state in RELOAD_STATES:
                hass.config_entries.async_schedule_reload(entry_id)
        waiting.clear()

    @callback
    def _is_rename(data: er.EventEntityRegistryUpdatedData) -> bool:
        return data["action"] == "update" and "old_entity_id" in data

    @callback
    def _on_rename(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        nonlocal cancel
        old: str = event.data["old_entity_id"]  # type: ignore[typeddict-item]
        new = event.data["entity_id"]
        for entry in hass.config_entries.async_entries(DOMAIN):
            tariffs = tariff_subentries(entry)
            used = sources(entry.data, [s.data for s in tariffs])
            if old not in used:
                continue
            if new in used:
                # Two sources would become one entity: leave it to the user.
                _LOGGER.warning(
                    "%s: %s was renamed to %s, which is already a source; "
                    "please reconfigure",
                    entry.title,
                    old,
                    new,
                )
                continue
            changes: dict[str, Any] = {"data": renamed_data(entry.data, old, new)}
            unique_id = renamed_unique_id(entry.unique_id, old, new)
            if unique_id and not hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, unique_id
            ):
                changes["unique_id"] = unique_id
            waiting.add(entry.entry_id)
            hass.config_entries.async_update_entry(entry, **changes)
            for subentry in tariffs:
                if (data := renamed_tariff(subentry.data, old, new)) is not None:
                    hass.config_entries.async_update_subentry(
                        entry, subentry, data=data
                    )
            _LOGGER.info("%s: source %s renamed to %s", entry.title, old, new)
        if waiting:
            if cancel is not None:
                cancel()
            cancel = async_call_later(
                hass,
                RENAME_RELOAD_DELAY,
                HassJob(_reload, "tarifwacht_renamed", cancel_on_shutdown=True),
            )

    hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, _on_rename, event_filter=_is_rename
    )


async def async_setup_entry(hass: HomeAssistant, entry: TarifwachtConfigEntry) -> bool:
    """Set up one meter with its tariffs."""
    runtime = MeterRuntime(hass, entry)
    await runtime.async_start()
    entry.runtime_data = runtime

    async def _async_on_stop(event: Event) -> None:
        await runtime.async_stop()

    # Stop listening and write the bookings when Home Assistant shuts down.
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_on_stop)
    )
    # Tariffs added, changed or removed: reload, which recomputes everything.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: TarifwachtConfigEntry
) -> None:
    if entry.entry_id in hass.data.get(RENAMED, ()):
        return  # renamed sources: the reload follows the burst
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TarifwachtConfigEntry) -> bool:
    """Unload; the runtime writes its state for the next setup."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: TarifwachtConfigEntry) -> None:
    """Delete the stored bookings."""
    await MeterRuntime(hass, entry).async_remove()


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Version 1 (0.1.0b1): both tariffs in the entry data -> subentries."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        devices = dr.async_get(hass)
        # Looked up within the entry: identifiers are unique per config entry only.
        meter_device = next(
            (
                d
                for d in dr.async_entries_for_config_entry(devices, entry.entry_id)
                if (DOMAIN, entry.entry_id) in d.identifiers
            ),
            None,
        )
        titles = default_titles(hass.config.language)
        for title, data in initial_tariffs(entry.data, titles):
            subentry = ConfigSubentry(
                data=MappingProxyType(data),
                subentry_type=SUBENTRY_TARIFF,
                title=title,
                unique_id=None,
            )
            hass.config_entries.async_add_subentry(entry, subentry)
            if meter_device is not None and meter_device.area_id:
                # The tariff sensors move to a device of their own; it keeps
                # the area the user gave the single device of 0.1.0b1.
                device = devices.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    config_subentry_id=subentry.subentry_id,
                    identifiers={(DOMAIN, f"{entry.entry_id}_{data[CONF_KEY]}")},
                    name=f"{entry.title} {title}",
                    manufacturer="Tarifwacht",
                    entry_type=dr.DeviceEntryType.SERVICE,
                )
                devices.async_update_device(device.id, area_id=meter_device.area_id)
        # "Extra cost dynamic" becomes the dynamic tariff's difference to the
        # current (fixed) tariff; keep its entity id and history.
        registry = er.async_get(hass)
        old = f"{entry.entry_id}_{TARIFF_DYNAMIC}_extra_cost"
        if entity_id := registry.async_get_entity_id("sensor", DOMAIN, old):
            registry.async_update_entity(
                entity_id,
                new_unique_id=f"{entry.entry_id}_{TARIFF_DYNAMIC}_difference",
            )
        hass.config_entries.async_update_entry(
            entry, data=entry_data(entry.data), version=2
        )
    return True
