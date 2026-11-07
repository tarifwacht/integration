"""Sensors: purchased energy and the cheapest tariff per meter; costs per tariff.

With a PV and battery subentry, each tariff also shows what PV and battery
saved under it since the start of the period (solar.py, from the long-term
statistics, recomputed every hour).

Each tariff (subentry) has its own device. Unique ids are
`{entry_id}_{tariff key}_{sensor}`; the two tariffs of 0.1.0b1 keep the keys
"fixed" and "dynamic", so their entities keep their ids and history.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TarifwachtConfigEntry
from .const import CONF_CHARGED_ENTITY, CONF_DISCHARGED_ENTITY, DOMAIN, VERSION
from .entity import MeterEntity
from .runtime import MeterRuntime, TariffInfo
from .solar import SolarTotals
from .tariffs import TariffTotals


@dataclass(frozen=True, kw_only=True)
class TariffSensorDescription(SensorEntityDescription):
    """A value of one tariff's totals."""

    value: Callable[[MeterRuntime, TariffInfo], float | None]
    attributes: Callable[[MeterRuntime], dict[str, Any]] | None = None


def _left_out(runtime: MeterRuntime) -> dict[str, Any]:
    """Energy not compared because a tariff has no price for it (kWh)."""
    left_out = runtime.engine.comparison.energy_left_out
    return {"energy_left_out_kwh": round(left_out, 3)} if left_out else {}


def _totals(runtime: MeterRuntime, tariff: TariffInfo) -> TariffTotals:
    return runtime.engine.totals[tariff.key]


def _average_ct(runtime: MeterRuntime, tariff: TariffInfo) -> float | None:
    average = _totals(runtime, tariff).average_price
    return None if average is None else average * 100


def _difference(runtime: MeterRuntime, tariff: TariffInfo) -> float | None:
    """Positive: this tariff would have cost more than the current one.

    Only quarter hours priced in every tariff count (see `Comparison`).
    """
    current = runtime.current
    if current is None:
        return None
    engine = runtime.engine
    cost, current_cost = (
        engine.compared_cost(tariff.key),
        engine.compared_cost(current.key),
    )
    if cost is None or current_cost is None:
        return None
    return cost - current_cost


def _money(
    key: str,
    value: Callable[[MeterRuntime, TariffInfo], float | None],
    attributes: Callable[[MeterRuntime], dict[str, Any]] | None = None,
) -> TariffSensorDescription:
    # Home Assistant allows only "total" for monetary sensors.
    return TariffSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value=value,
        attributes=attributes,
    )


def _solar(runtime: MeterRuntime, tariff: TariffInfo) -> SolarTotals | None:
    result = runtime.solar_result
    return None if result is None else result.totals.get(tariff.key)


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _saving_pv_attributes(runtime: MeterRuntime, tariff: TariffInfo) -> dict[str, Any]:
    totals = _solar(runtime, tariff)
    if totals is None:
        return {}
    return {
        "cost_without_pv_and_battery": _r(totals.without),
        "cost_pv_without_battery": _r(totals.pv_only),
        "cost_actual": _r(totals.actual),
        "consumption_kwh": _r(totals.consumption, 1),
        "pv_kwh": _r(totals.pv, 1),
        "purchase_kwh": _r(totals.purchase, 1),
        "feed_in_kwh": _r(totals.feed_in, 1),
        "feed_in_unpaid_kwh": _r(totals.feed_in_unpaid, 1),
        "hours": totals.hours,
        "hours_left_out": totals.hours_left_out,
    }


def _saving_battery_attributes(
    runtime: MeterRuntime, tariff: TariffInfo
) -> dict[str, Any]:
    totals = _solar(runtime, tariff)
    if totals is None:
        return {}
    value = totals.battery_value
    return {
        "charged_kwh": _r(totals.charged, 1),
        "discharged_kwh": _r(totals.discharged, 1),
        "value_per_kwh_ct": None if value is None else round(value * 100, 1),
        "hours": totals.hours,
        "hours_left_out": totals.hours_left_out,
    }


TARIFF_SENSORS = (
    _money("consumption_cost", lambda r, t: _totals(r, t).consumption_cost),
    _money("cost", lambda r, t: _totals(r, t).cost),
    TariffSensorDescription(
        key="average_price",
        translation_key="average_price",
        native_unit_of_measurement="ct/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value=_average_ct,
    ),
)
DIFFERENCE = _money("difference", _difference, _left_out)


@dataclass(frozen=True, kw_only=True)
class SolarSensorDescription(TariffSensorDescription):
    """A saving of PV or battery under one tariff."""

    solar_attributes: Callable[[MeterRuntime, TariffInfo], dict[str, Any]]


def _saving(
    key: str,
    value: Callable[[SolarTotals], float],
    attributes: Callable[[MeterRuntime, TariffInfo], dict[str, Any]],
) -> SolarSensorDescription:
    def read(runtime: MeterRuntime, tariff: TariffInfo) -> float | None:
        totals = _solar(runtime, tariff)
        return None if totals is None or not totals.hours else value(totals)

    return SolarSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value=read,
        solar_attributes=attributes,
    )


SAVING_PV = _saving("saving_pv", lambda t: t.saving_pv, _saving_pv_attributes)
SAVING_BATTERY = _saving(
    "saving_battery", lambda t: t.saving_battery, _saving_battery_attributes
)

ENERGY = SensorEntityDescription(
    key="energy",
    translation_key="energy",
    device_class=SensorDeviceClass.ENERGY,
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    state_class=SensorStateClass.TOTAL_INCREASING,
    suggested_display_precision=3,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TarifwachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Meter sensors on the entry; tariff sensors on their subentries."""
    runtime = entry.runtime_data
    async_add_entities([EnergySensor(entry, ENERGY), CheapestSensor(entry)])
    current = runtime.current
    solar = runtime.solar_data
    battery = solar is not None and bool(
        solar.get(CONF_CHARGED_ENTITY) and solar.get(CONF_DISCHARGED_ENTITY)
    )
    for tariff in runtime.tariffs.values():
        descriptions = list(TARIFF_SENSORS)
        if current is not None and tariff.key != current.key:
            descriptions.append(DIFFERENCE)
        if solar is not None:
            descriptions.append(SAVING_PV)
        if battery:
            descriptions.append(SAVING_BATTERY)
        async_add_entities(
            [TariffSensor(entry, tariff, d) for d in descriptions],
            config_subentry_id=tariff.subentry_id,
        )


class EnergySensor(MeterEntity, SensorEntity):
    """Purchased energy booked since the start of the period (kWh)."""

    def __init__(
        self, entry: TarifwachtConfigEntry, description: SensorEntityDescription
    ) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return self.runtime.engine.energy


class CheapestSensor(MeterEntity, SensorEntity):
    """The tariff with the lowest total cost so far.

    Ranked by the cost in the quarter hours priced in every tariff (see
    `Comparison`), so a failed price sensor does not make its tariff cheapest.
    """

    # The costs in the ranking change all the time; recording every change
    # would add a row of attributes per update.
    _unrecorded_attributes = frozenset({"ranking"})

    def __init__(self, entry: TarifwachtConfigEntry) -> None:
        super().__init__(entry, "cheapest")

    def _ranking(self) -> list[tuple[TariffInfo, float]]:
        engine = self.runtime.engine
        costs = (
            (t, engine.compared_cost(t.key)) for t in self.runtime.tariffs.values()
        )
        return sorted(
            ((t, cost) for t, cost in costs if cost is not None),
            key=lambda item: item[1],
        )

    @property
    def native_value(self) -> str | None:
        ranking = self._ranking()
        return ranking[0][0].title if ranking else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "ranking": [
                {"tariff": tariff.title, "cost": round(cost, 2)}
                for tariff, cost in self._ranking()
            ],
            **_left_out(self.runtime),
        }


class TariffSensor(SensorEntity):
    """A value of one tariff, on the tariff's own device."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: TariffSensorDescription

    def __init__(
        self,
        entry: TarifwachtConfigEntry,
        tariff: TariffInfo,
        description: TariffSensorDescription,
    ) -> None:
        self.runtime: MeterRuntime = entry.runtime_data
        self.tariff = tariff
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{tariff.key}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{tariff.key}")},
            name=f"{entry.title} {tariff.title}",
            manufacturer="Tarifwacht",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value(self.runtime, self.tariff)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        description = self.entity_description
        if isinstance(description, SolarSensorDescription):
            return description.solar_attributes(self.runtime, self.tariff)
        attributes = description.attributes
        return attributes(self.runtime) if attributes is not None else None
