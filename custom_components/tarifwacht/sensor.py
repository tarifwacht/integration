"""Sensors: purchased energy, costs per tariff, extra cost of the dynamic tariff."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TarifwachtConfigEntry
from .const import TARIFF_DYNAMIC, TARIFF_FIXED
from .engine import Engine
from .entity import MeterEntity


@dataclass(frozen=True, kw_only=True)
class TarifwachtSensorDescription(SensorEntityDescription):
    """A value read from the engine."""

    value: Callable[[Engine], float]


def _money(key: str, value: Callable[[Engine], float]) -> TarifwachtSensorDescription:
    # Home Assistant allows only "total" for monetary sensors.
    return TarifwachtSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value=value,
    )


def _extra_cost(engine: Engine) -> float:
    """Positive: the dynamic tariff would have cost more."""
    return engine.totals[TARIFF_DYNAMIC].cost - engine.totals[TARIFF_FIXED].cost


SENSORS = (
    TarifwachtSensorDescription(
        key="energy",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        value=lambda e: e.energy,
    ),
    _money(
        "fixed_consumption_cost",
        lambda e: e.totals[TARIFF_FIXED].consumption_cost,
    ),
    _money("fixed_cost", lambda e: e.totals[TARIFF_FIXED].cost),
    _money(
        "dynamic_consumption_cost",
        lambda e: e.totals[TARIFF_DYNAMIC].consumption_cost,
    ),
    _money("dynamic_cost", lambda e: e.totals[TARIFF_DYNAMIC].cost),
    _money("dynamic_extra_cost", _extra_cost),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TarifwachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Running totals since setup."""
    async_add_entities(TarifwachtSensor(entry, d) for d in SENSORS)


class TarifwachtSensor(MeterEntity, SensorEntity):
    """Running total since setup (kWh or EUR)."""

    entity_description: TarifwachtSensorDescription

    def __init__(
        self, entry: TarifwachtConfigEntry, description: TarifwachtSensorDescription
    ) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return self.entity_description.value(self.runtime.engine)
