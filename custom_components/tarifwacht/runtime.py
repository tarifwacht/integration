"""Home Assistant side of one meter: listens to meter and price, stores state."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

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
from .engine import Engine, TariffAccount
from .meter import MeterTracker, to_kwh
from .prices import ParsedPrices, PriceTable, parse_interval_prices
from .tariffs import FixedPrice
from .timeslots import slot_start

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Bookings are written at most this often (and on unload).
SAVE_DELAY = 60

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


def engine_from_config(config: Mapping[str, Any]) -> Engine:
    prices = PriceTable()
    return Engine(
        meter=MeterTracker(max_power_kw=MAX_GRID_POWER_KW),
        tariffs={
            TARIFF_FIXED: TariffAccount(
                FixedPrice(float(config[CONF_FIXED_PRICE]) / 100),
                float(config.get(CONF_FIXED_BASE) or 0),
            ),
            TARIFF_DYNAMIC: TariffAccount(
                prices, float(config.get(CONF_DYNAMIC_BASE) or 0)
            ),
        },
        tz=BERLIN,
        prices=prices,
    )


class MeterRuntime:
    """Feeds the engine and notifies entities."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, config: Mapping[str, Any]
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.name: str = config[CONF_NAME]
        self.meter_entity: str = config[CONF_METER]
        self.price_entity: str = config[CONF_DYNAMIC_PRICE]
        self.engine = engine_from_config(config)
        self.unknown_unit: str | None = None
        self.wrong_price_unit: str | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []

    async def async_start(self) -> None:
        """Restore the stored state, read current values, start listening."""
        if data := await self._store.async_load():
            self.engine.restore(data)
        now = dt_util.utcnow()
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
            self.engine.on_prices(parsed, now)

    def _changed(self) -> None:
        self._store.async_delay_save(self.engine.as_dict, SAVE_DELAY)
        for listener in list(self._listeners):
            listener()
