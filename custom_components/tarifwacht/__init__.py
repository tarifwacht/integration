"""Tarifwacht: what your grid purchase would have cost under other tariffs."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from .runtime import MeterRuntime

PLATFORMS: list[Platform] = [Platform.SENSOR]

type TarifwachtConfigEntry = ConfigEntry[MeterRuntime]


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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TarifwachtConfigEntry) -> bool:
    """Unload; the runtime writes its state for the next setup."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: TarifwachtConfigEntry) -> None:
    """Delete the stored bookings."""
    await MeterRuntime(hass, entry).async_remove()
