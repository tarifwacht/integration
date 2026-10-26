"""Home Assistant side of one meter: listens to meter and price, stores state."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance, history
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_utc_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BERLIN,
    CONF_DYNAMIC_BASE,
    CONF_DYNAMIC_PRICE,
    CONF_FIXED_BASE,
    CONF_FIXED_PRICE,
    CONF_METER,
    CONF_NAME,
    DOMAIN,
    MAX_GRID_POWER_KW,
    PRICE_UNITS,
    TARIFF_DYNAMIC,
    TARIFF_FIXED,
)
from .engine import Engine, migrate_v1
from .meter import MeterTracker, to_kwh
from .prices import ParsedPrices, parse_interval_prices
from .tariffs import FixedPrice, Tariff
from .timeslots import slot_start

_LOGGER = logging.getLogger(__name__)

# 1: 0.1.0b1 (running totals); 2: consumption and prices per quarter hour.
STORAGE_VERSION = 2
# Bookings are written at most this often (and on unload).
SAVE_DELAY = 60

# Recorder history is read from this long before the setup of the entry, so
# the reading in effect at the setup is found as the baseline.
BACKFILL_MARGIN = timedelta(hours=1)

# Price sensors without a forecast attribute: the state is the current price.
FORECAST_ATTRIBUTE = "data"


def parse_price_state(state: State) -> ParsedPrices | None:
    """Prices from a price sensor: forecast attribute, else the current state."""
    forecast = state.attributes.get(FORECAST_ATTRIBUTE)
    if isinstance(forecast, list) and forecast:
        return parse_interval_prices(forecast)
    try:
        price = float(state.state)
    except ValueError:
        return None
    return ParsedPrices(prices={slot_start(state.last_updated): price})


def price_unit_ok(state: State) -> bool:
    return state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) in PRICE_UNITS


def meter_reading(state: State) -> float | None:
    """Meter state in kWh; None if unavailable, not numeric or in another unit."""
    if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        return to_kwh(
            float(state.state), state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        )
    except KeyError, ValueError:
        return None


def engine_from_config(config: Mapping[str, Any]) -> Engine:
    engine = Engine(
        meter=MeterTracker(max_power_kw=MAX_GRID_POWER_KW), tariffs={}, tz=BERLIN
    )
    engine.tariffs = {
        TARIFF_FIXED: Tariff(
            FixedPrice(float(config[CONF_FIXED_PRICE]) / 100),
            float(config.get(CONF_FIXED_BASE) or 0),
        ),
        TARIFF_DYNAMIC: Tariff(
            engine.price_table(config[CONF_DYNAMIC_PRICE]),
            float(config.get(CONF_DYNAMIC_BASE) or 0),
        ),
    }
    return engine


class TarifwachtStore(Store[dict[str, Any]]):
    """Storage of one entry; converts the format of 0.1.0b1."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._entry = entry

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: Any
    ) -> dict[str, Any]:
        if old_major_version == 1:
            return migrate_v1(
                old_data, self._entry.data[CONF_DYNAMIC_PRICE], self._entry.created_at
            )
        raise NotImplementedError


class MeterRuntime:
    """Feeds the engine and notifies entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        config = entry.data
        self.name: str = config[CONF_NAME]
        self.meter_entity: str = config[CONF_METER]
        self.price_entity: str = config[CONF_DYNAMIC_PRICE]
        self.engine = engine_from_config(config)
        self.unknown_unit: str | None = None
        self.wrong_price_unit: str | None = None
        self.backfill_error: str | None = None
        self._store = TarifwachtStore(hass, entry)
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []

    async def async_start(self) -> None:
        """Restore the stored state, read current values, start listening."""
        if data := await self._store.async_load():
            self.engine.restore(data)
        if self.engine.backfill_until is not None:
            await self._async_backfill()
        now = dt_util.utcnow()
        self.engine.start(now)
        if state := self.hass.states.get(self.price_entity):
            self._handle_price(state, now)
        if state := self.hass.states.get(self.meter_entity):
            self._handle_meter(state, now)
        self.engine.tick(now)
        self._unsubscribe = [
            async_track_state_change_event(
                self.hass, [self.meter_entity, self.price_entity], self._on_state_change
            ),
            async_track_utc_time_change(
                self.hass, self._on_tick, minute=[0, 15, 30, 45], second=1
            ),
        ]

    async def _async_backfill(self) -> None:
        """Read the consumption 0.1.0b1 did not keep from the recorder.

        From the setup of the entry up to the last reading 0.1.0b1 booked. If
        the recorder is not available, the next start tries again; live
        booking is not affected.
        """
        until = self.engine.backfill_until
        if until is None:
            return
        if "recorder" not in self.hass.config.components:
            self.backfill_error = "recorder not available"
            return
        created = self.entry.created_at
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                history.state_changes_during_period,
                self.hass,
                # Start earlier: a reading exactly at `created` would be
                # neither the start state nor a change after the start.
                created - BACKFILL_MARGIN,
                # The end is exclusive; the reading at `until` belongs to it.
                until + timedelta(microseconds=1),
                self.meter_entity,
            )
        except Exception as err:  # never block the setup
            self.backfill_error = f"{type(err).__name__}: {err}"
            _LOGGER.warning("%s: reading the recorder failed: %s", self.name, err)
            return
        readings = [
            (value, state.last_updated)
            for state in states.get(self.meter_entity.lower(), [])
            if (value := meter_reading(state)) is not None
        ]
        self.engine.backfill(readings, since=created)
        self.backfill_error = None
        _LOGGER.debug(
            "%s: %s readings read from the recorder", self.name, len(readings)
        )

    async def async_stop(self) -> None:
        """Stop listening and write the state."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []
        await self._store.async_save(self.engine.as_dict())

    async def async_remove(self) -> None:
        await self._store.async_remove()

    @callback
    def add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        if state is None:
            return
        now = dt_util.utcnow()
        if state.entity_id == self.meter_entity:
            self._handle_meter(state, now)
        else:
            self._handle_price(state, now)
        self._changed()

    @callback
    def _on_tick(self, now: datetime) -> None:
        self.engine.tick(now)
        self._changed()

    def _handle_meter(self, state: State, now: datetime) -> None:
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        try:
            value = to_kwh(float(state.state), unit)
        except KeyError:
            if self.unknown_unit != unit:
                _LOGGER.warning("%s: unsupported unit %s", self.meter_entity, unit)
            self.unknown_unit = unit
            return
        except ValueError:
            return
        self.unknown_unit = None
        update = self.engine.on_meter(value, state.last_updated, now)
        if update.event is not None:
            _LOGGER.debug(
                "%s: %s (delta %s kWh)", self.meter_entity, update.event, update.delta
            )

    def _handle_price(self, state: State, now: datetime) -> None:
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        if not price_unit_ok(state):
            # Prices are used as they are: a wrong unit would book nonsense.
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if self.wrong_price_unit != unit:
                _LOGGER.warning(
                    "%s: unsupported price unit %s (expected €/kWh)",
                    self.price_entity,
                    unit,
                )
            self.wrong_price_unit = unit
            return
        self.wrong_price_unit = None
        if (parsed := parse_price_state(state)) is not None:
            self.engine.on_prices(self.price_entity, parsed, now)

    def _changed(self) -> None:
        self._store.async_delay_save(self.engine.as_dict, SAVE_DELAY)
        for listener in list(self._listeners):
            listener()
