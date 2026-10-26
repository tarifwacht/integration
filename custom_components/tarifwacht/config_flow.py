"""Config flow: meter, then a fixed and a dynamic tariff. One entry per meter.

The same steps serve reconfiguration; the last step then updates the entry.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import ATTR_STATE_CLASS, SensorStateClass
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.helpers import selector

from .const import (
    CONF_DYNAMIC_BASE,
    CONF_DYNAMIC_PRICE,
    CONF_FIXED_BASE,
    CONF_FIXED_PRICE,
    CONF_METER,
    CONF_NAME,
    DOMAIN,
)
from .meter import UNIT_FACTORS
from .runtime import parse_price_state, price_unit_ok


def _number(unit: str, step: float, maximum: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


PRICE_NUMBER = _number("ct/kWh", 0.001, 200)
# Selector units are not translated; "per month" is in the field label.
BASE_NUMBER = _number("€", 0.01, 1000)


class TarifwachtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a grid purchase meter and the tariffs to compare."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: name and meter."""
        return await self._async_meter_step("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change an existing entry: the same steps, prefilled."""
        if not self._data:
            self._data = dict(self._get_reconfigure_entry().data)
        return await self._async_meter_step("reconfigure", user_input)

    async def _async_meter_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            meter = user_input[CONF_METER]
            if not name:
                errors[CONF_NAME] = "name_required"
            else:
                errors = self._validate_meter(meter)
            if not errors:
                self._data[CONF_NAME] = name
                self._data[CONF_METER] = meter
                return await self.async_step_tariffs()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_METER): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="energy"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or self._data
            ),
            errors=errors,
        )

    def _validate_meter(self, meter: str) -> dict[str, str]:
        current = (
            self._get_reconfigure_entry().entry_id
            if self.source == SOURCE_RECONFIGURE
            else None
        )
        state = self.hass.states.get(meter)
        if any(
            e.unique_id == meter and e.entry_id != current
            for e in self._async_current_entries()
        ):
            return {CONF_METER: "meter_in_use"}
        if state is None:
            return {CONF_METER: "entity_missing"}
        if state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) not in UNIT_FACTORS:
            return {CONF_METER: "meter_unit"}
        if state.attributes.get(ATTR_STATE_CLASS) not in (
            SensorStateClass.TOTAL,
            SensorStateClass.TOTAL_INCREASING,
        ):
            return {CONF_METER: "meter_state_class"}
        return {}

    async def async_step_tariffs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: fixed price and dynamic price sensor, optional base prices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_FIXED_PRICE):
                errors[CONF_FIXED_PRICE] = "price_required"
            errors.update(self._validate_price(user_input[CONF_DYNAMIC_PRICE]))
            if not errors:
                self._data.update(
                    {
                        CONF_FIXED_PRICE: float(user_input[CONF_FIXED_PRICE]),
                        CONF_FIXED_BASE: float(user_input.get(CONF_FIXED_BASE) or 0),
                        CONF_DYNAMIC_PRICE: user_input[CONF_DYNAMIC_PRICE],
                        CONF_DYNAMIC_BASE: float(
                            user_input.get(CONF_DYNAMIC_BASE) or 0
                        ),
                    }
                )
                return await self._async_finish()

        schema = vol.Schema(
            {
                vol.Required(CONF_FIXED_PRICE): PRICE_NUMBER,
                vol.Optional(CONF_FIXED_BASE): BASE_NUMBER,
                vol.Required(CONF_DYNAMIC_PRICE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_DYNAMIC_BASE): BASE_NUMBER,
            }
        )
        return self.async_show_form(
            step_id="tariffs",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or self._data
            ),
            errors=errors,
        )

    def _validate_price(self, price: str) -> dict[str, str]:
        state = self.hass.states.get(price)
        if state is None:
            return {CONF_DYNAMIC_PRICE: "entity_missing"}
        if not price_unit_ok(state):
            return {CONF_DYNAMIC_PRICE: "price_unit"}
        parsed = parse_price_state(state)
        if parsed is None or not parsed.prices:
            return {CONF_DYNAMIC_PRICE: "price_invalid"}
        return {}

    async def _async_finish(self) -> ConfigFlowResult:
        meter = self._data[CONF_METER]
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                unique_id=meter,
                title=self._data[CONF_NAME],
                data=self._data,
            )
        await self.async_set_unique_id(meter)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
