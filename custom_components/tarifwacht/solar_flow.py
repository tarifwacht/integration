"""Subentry flow "PV and battery": the meters and what feed-in earns.

At most one per entry. Prefilled from an Einspeisewacht entry if there is
one (feed-in meter, rate, the negative price rule, exchange price sensor);
copied once, no dependency at runtime. Whether the battery sits behind the PV
inverter is asked in plain words, with the answer the data suggest.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import ATTR_STATE_CLASS, SensorStateClass
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHARGED_ENTITY,
    CONF_DISCHARGED_ENTITY,
    CONF_FEED_IN_ENTITY,
    CONF_FEED_IN_RATE,
    CONF_MARKET_ENTITY,
    CONF_METER,
    CONF_NEGATIVE_UNPAID,
    CONF_PV_ENTITY,
    CONF_SAME_INVERTER,
    SUBENTRY_SOLAR,
)
from .meter import UNIT_FACTORS
from .runtime import own_entity
from .solar import HourFlows, detect_same_inverter

# Section 51 EEG (Solarspitzengesetz): plants commissioned from this day on
# get nothing in quarter hours with a negative day-ahead price.
SECTION_51_FROM = date(2025, 2, 25)
# Hours of statistics read to tell the coupling.
DETECT_DAYS = 30
TITLE = "PV"

ENERGY_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="energy")
)
PRICE_SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
RATE = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=100,
        step=0.001,
        unit_of_measurement="ct/kWh",
        mode=selector.NumberSelectorMode.BOX,
    )
)
METERS = (
    CONF_FEED_IN_ENTITY,
    CONF_PV_ENTITY,
    CONF_CHARGED_ENTITY,
    CONF_DISCHARGED_ENTITY,
)


def from_einspeisewacht(hass: HomeAssistant) -> dict[str, Any]:
    """Suggested values from an Einspeisewacht entry (the first one)."""
    entries = hass.config_entries.async_entries("einspeisewacht")
    if not entries:
        return {}
    data = entries[0].data
    found: dict[str, Any] = {}
    if meter := data.get("meter_entity"):
        found[CONF_FEED_IN_ENTITY] = meter
    rates = data.get("rates") or []
    if rates:
        found[CONF_FEED_IN_RATE] = float(rates[0])
    if price := data.get("price_entity"):
        found[CONF_MARKET_ENTITY] = price
    try:
        commissioned = date.fromisoformat(data.get("commissioned") or "")
    except ValueError:
        commissioned = None
    if commissioned is not None:
        found[CONF_NEGATIVE_UNPAID] = bool(
            commissioned >= SECTION_51_FROM and data.get("smart_meter")
        )
    return found


def validate_meter(hass: HomeAssistant, entity_id: str, purchase: str) -> str | None:
    """Error code for an unusable energy meter, None if it is fine."""
    if entity_id == purchase:
        return "same_as_purchase"
    if own_entity(hass, entity_id):
        return "own_entity"
    state = hass.states.get(entity_id)
    if state is None:
        return "entity_missing"
    if state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) not in UNIT_FACTORS:
        return "meter_unit"
    if state.attributes.get(ATTR_STATE_CLASS) not in (
        SensorStateClass.TOTAL,
        SensorStateClass.TOTAL_INCREASING,
    ):
        return "meter_state_class"
    return None


async def async_detect_same_inverter(
    hass: HomeAssistant, pv: str, charged: str, discharged: str
) -> bool | None:
    """The coupling from the last DETECT_DAYS of hourly statistics."""
    if "recorder" not in hass.config.components:
        return None
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import (
        statistics_during_period,
    )

    end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    try:
        rows = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            end - timedelta(days=DETECT_DAYS),
            end,
            {pv, charged, discharged},
            "hour",
            {"energy": UnitOfEnergy.KILO_WATT_HOUR},
            {"change"},
        )
    except Exception:  # detection is a suggestion only
        return None

    def series(entity: str) -> dict[Any, float]:
        return {
            row["start"]: max(0.0, row["change"])
            for row in rows.get(entity, [])
            if row.get("change") is not None
        }

    p, c, d = series(pv), series(charged), series(discharged)
    hours = {
        h: HourFlows(pv=p[h], charged=c[h], discharged=d[h])
        for h in set(p) & set(c) & set(d)
    }
    return detect_same_inverter(hours)


def _schema(values: dict[str, Any]) -> vol.Schema:
    def suggested(key: str) -> dict[str, Any]:
        return {"suggested_value": values.get(key)}

    return vol.Schema(
        {
            vol.Required(
                CONF_FEED_IN_ENTITY, description=suggested(CONF_FEED_IN_ENTITY)
            ): ENERGY_SENSOR,
            vol.Required(
                CONF_PV_ENTITY, description=suggested(CONF_PV_ENTITY)
            ): ENERGY_SENSOR,
            vol.Optional(
                CONF_CHARGED_ENTITY, description=suggested(CONF_CHARGED_ENTITY)
            ): ENERGY_SENSOR,
            vol.Optional(
                CONF_DISCHARGED_ENTITY, description=suggested(CONF_DISCHARGED_ENTITY)
            ): ENERGY_SENSOR,
            vol.Required(
                CONF_FEED_IN_RATE, description=suggested(CONF_FEED_IN_RATE)
            ): RATE,
            vol.Required(
                CONF_NEGATIVE_UNPAID,
                default=bool(values.get(CONF_NEGATIVE_UNPAID, False)),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_MARKET_ENTITY, description=suggested(CONF_MARKET_ENTITY)
            ): PRICE_SENSOR,
        }
    )


class SolarSubentryFlow(ConfigSubentryFlow):
    """Add or change PV and battery."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._detected: bool | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        if any(s.subentry_type == SUBENTRY_SOLAR for s in entry.subentries.values()):
            return self.async_abort(reason="single_solar")
        return await self._async_meters(
            "user", user_input, from_einspeisewacht(self.hass)
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_meters(
            "reconfigure", user_input, dict(self._get_reconfigure_subentry().data)
        )

    async def _async_meters(
        self, step_id: str, user_input: dict[str, Any] | None, values: dict[str, Any]
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values = dict(user_input)
            purchase = self._get_entry().data[CONF_METER]
            for key in METERS:
                if (entity := user_input.get(key)) and (
                    error := validate_meter(self.hass, entity, purchase)
                ):
                    errors[key] = error
            charged = user_input.get(CONF_CHARGED_ENTITY)
            discharged = user_input.get(CONF_DISCHARGED_ENTITY)
            if bool(charged) != bool(discharged):
                errors["base"] = "battery_both"
            if user_input[CONF_NEGATIVE_UNPAID] and not (
                user_input.get(CONF_MARKET_ENTITY) or self._has_market_tariff()
            ):
                errors[CONF_MARKET_ENTITY] = "market_required"
            if not errors:
                self._data = {
                    k: v for k, v in user_input.items() if v not in (None, "")
                }
                if charged and discharged:
                    self._detected = await async_detect_same_inverter(
                        self.hass, user_input[CONF_PV_ENTITY], charged, discharged
                    )
                    return await self._async_battery(None)
                self._data[CONF_SAME_INVERTER] = False
                return self._finish()
        return self.async_show_form(
            step_id=step_id, data_schema=_schema(values), errors=errors
        )

    def _has_market_tariff(self) -> bool:
        return any(
            s.data.get("kind") == "dynamic_market"
            for s in self._get_entry().subentries.values()
        )

    # One step per detection result, so that each has its own text (the
    # placeholders of a form are not translated).
    async def async_step_battery_same(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_battery(user_input)

    async def async_step_battery_own(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_battery(user_input)

    async def async_step_battery_unknown(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_battery(user_input)

    async def _async_battery(
        self, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        """Battery behind the PV inverter (hybrid) or with its own inverter."""
        if user_input is not None:
            self._data[CONF_SAME_INVERTER] = user_input[CONF_SAME_INVERTER]
            return self._finish()
        if self._detected is not None:
            default = self._detected
        elif self.source == "reconfigure":
            default = bool(
                self._get_reconfigure_subentry().data.get(CONF_SAME_INVERTER, False)
            )
        else:
            default = False
        step = {True: "same", False: "own", None: "unknown"}[self._detected]
        return self.async_show_form(
            step_id=f"battery_{step}",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SAME_INVERTER, default=default
                    ): selector.BooleanSelector()
                }
            ),
        )

    def _finish(self) -> SubentryFlowResult:
        if self.source == "reconfigure":
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), data=self._data
            )
        return self.async_create_entry(title=TITLE, data=self._data)
