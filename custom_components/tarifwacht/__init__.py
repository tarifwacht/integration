"""Tarifwacht: what your grid purchase would have cost under other tariffs."""

from __future__ import annotations

from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import CONF_KEY, DOMAIN, SUBENTRY_TARIFF, TARIFF_DYNAMIC
from .runtime import MeterRuntime
from .services import async_setup_services
from .tariff_config import default_titles, entry_data, initial_tariffs

PLATFORMS: list[Platform] = [Platform.SENSOR]

type TarifwachtConfigEntry = ConfigEntry[MeterRuntime]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions (once, for all entries)."""
    async_setup_services(hass)
    return True


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
