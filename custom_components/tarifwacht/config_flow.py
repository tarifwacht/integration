"""Config flow: meter and two tariffs; more tariffs as subentries.

Setup asks for the meter, then a fixed price and a total-price sensor; both
become tariff subentries. "Add tariff" offers three kinds: fixed price, total
price sensor, exchange price plus surcharges. Reconfiguring the entry changes
name and meter; reconfiguring a tariff shows its form again. Every change
reloads the entry (update listener), which recomputes the whole period.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import ATTR_STATE_CLASS, SensorStateClass
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_CURRENT,
    CONF_DYNAMIC_BASE,
    CONF_DYNAMIC_PRICE,
    CONF_FIXED_BASE,
    CONF_FIXED_PRICE,
    CONF_GRID_FEE,
    CONF_KEY,
    CONF_KIND,
    CONF_LEVIES,
    CONF_MARGIN,
    CONF_METER,
    CONF_NAME,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    CONF_VAT,
    DEFAULT_VAT,
    DOMAIN,
    KIND_DYNAMIC_MARKET,
    KIND_DYNAMIC_TOTAL,
    KIND_FIXED,
    KINDS,
    SUBENTRY_TARIFF,
)
from .meter import UNIT_FACTORS
from .runtime import parse_price_state, price_unit_ok, tariff_subentries
from .tariff_config import default_titles, entry_data, initial_tariffs
from .tariffs import BasePeriod


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
# Selector units are not translated; "per month/year" is in the field label.
BASE_NUMBER = _number("€", 0.01, 10000)
VAT_NUMBER = _number("%", 0.1, 100)
PRICE_SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
BASE_PERIOD = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[p.value for p in BasePeriod],
        translation_key=CONF_BASE_PERIOD,
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


def validate_price_entity(hass: HomeAssistant, entity_id: str) -> str | None:
    """Error code for an unusable price sensor, None if it is fine."""
    state = hass.states.get(entity_id)
    if state is None:
        return "entity_missing"
    if not price_unit_ok(state):
        return "price_unit"
    parsed = parse_price_state(state)
    if parsed is None or not parsed.prices:
        return "price_invalid"
    return None


class TarifwachtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a grid purchase meter and the tariffs to compare."""

    # 1: 0.1.0b1, tariffs in the entry data; 2: tariffs as subentries.
    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TARIFF: TariffSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: name and meter."""
        return await self._async_meter_step("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change name and meter; tariffs are changed in their subentries."""
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
                if self.source == SOURCE_RECONFIGURE:
                    # The update listener reloads the entry.
                    return self.async_update_and_abort(
                        self._get_reconfigure_entry(),
                        unique_id=meter,
                        title=name,
                        data=entry_data(self._data),
                    )
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
        """Step 2: fixed price and total-price sensor, optional base prices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_FIXED_PRICE):
                errors[CONF_FIXED_PRICE] = "price_required"
            if error := validate_price_entity(
                self.hass, user_input[CONF_DYNAMIC_PRICE]
            ):
                errors[CONF_DYNAMIC_PRICE] = error
            if not errors:
                return await self._async_create(user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_FIXED_PRICE): PRICE_NUMBER,
                vol.Optional(CONF_FIXED_BASE): BASE_NUMBER,
                vol.Required(CONF_DYNAMIC_PRICE): PRICE_SENSOR,
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

    async def _async_create(self, tariffs: dict[str, Any]) -> ConfigFlowResult:
        meter = self._data[CONF_METER]
        await self.async_set_unique_id(meter)
        self._abort_if_unique_id_configured()
        titles = default_titles(self.hass.config.language)
        return self.async_create_entry(
            title=self._data[CONF_NAME],
            data=entry_data(self._data),
            subentries=[
                ConfigSubentryData(
                    data=data,
                    subentry_type=SUBENTRY_TARIFF,
                    title=title,
                    unique_id=None,
                )
                for title, data in initial_tariffs(tariffs, titles)
            ],
        )


def _tariff_schema(kind: str) -> vol.Schema:
    fields: dict[Any, Any] = {vol.Required(CONF_NAME): selector.TextSelector()}
    if kind == KIND_FIXED:
        fields[vol.Required(CONF_PRICE)] = PRICE_NUMBER
    else:
        fields[vol.Required(CONF_PRICE_ENTITY)] = PRICE_SENSOR
    if kind == KIND_DYNAMIC_MARKET:
        for key in (CONF_GRID_FEE, CONF_LEVIES, CONF_MARGIN):
            fields[vol.Optional(key)] = PRICE_NUMBER
        fields[vol.Required(CONF_VAT)] = VAT_NUMBER
    fields[vol.Optional(CONF_BASE_PRICE)] = BASE_NUMBER
    fields[vol.Required(CONF_BASE_PERIOD)] = BASE_PERIOD
    fields[vol.Required(CONF_CURRENT)] = selector.BooleanSelector()
    return vol.Schema(fields)


def _tariff_data(kind: str, user_input: dict[str, Any]) -> dict[str, Any]:
    """What a tariff subentry stores (the name is its title)."""
    data: dict[str, Any] = {CONF_KIND: kind}
    if kind == KIND_FIXED:
        data[CONF_PRICE] = float(user_input[CONF_PRICE])
    else:
        data[CONF_PRICE_ENTITY] = user_input[CONF_PRICE_ENTITY]
    if kind == KIND_DYNAMIC_MARKET:
        for key in (CONF_GRID_FEE, CONF_LEVIES, CONF_MARGIN):
            data[key] = float(user_input.get(key) or 0)
        data[CONF_VAT] = float(user_input[CONF_VAT])
    data[CONF_BASE_PRICE] = float(user_input.get(CONF_BASE_PRICE) or 0)
    data[CONF_BASE_PERIOD] = user_input[CONF_BASE_PERIOD]
    data[CONF_CURRENT] = bool(user_input[CONF_CURRENT])
    return data


class TariffSubentryFlow(ConfigSubentryFlow):
    """Add or change one tariff."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose the kind of tariff."""
        return self.async_show_menu(step_id="user", menu_options=list(KINDS))

    async def async_step_fixed(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_tariff_step(KIND_FIXED, user_input)

    async def async_step_dynamic_total(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_tariff_step(KIND_DYNAMIC_TOTAL, user_input)

    async def async_step_dynamic_market(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_tariff_step(KIND_DYNAMIC_MARKET, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the form of the tariff's kind, prefilled."""
        kind = self._get_reconfigure_subentry().data[CONF_KIND]
        return await self._async_tariff_step(kind, None)

    async def _async_tariff_step(
        self, kind: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = (
            self._get_reconfigure_subentry()
            if self.source == SOURCE_RECONFIGURE
            else None
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            elif any(
                s.title.casefold() == name.casefold()
                and (subentry is None or s.subentry_id != subentry.subentry_id)
                for s in tariff_subentries(entry)
            ):
                errors[CONF_NAME] = "name_in_use"
            if kind == KIND_FIXED and not user_input.get(CONF_PRICE):
                errors[CONF_PRICE] = "price_required"
            if kind != KIND_FIXED and (
                error := validate_price_entity(self.hass, user_input[CONF_PRICE_ENTITY])
            ):
                errors[CONF_PRICE_ENTITY] = error
            if not errors:
                data = _tariff_data(kind, user_input)
                if subentry is not None and subentry.data.get(CONF_KEY):
                    data[CONF_KEY] = subentry.data[CONF_KEY]
                if data[CONF_CURRENT]:
                    self._clear_current(entry, subentry)
                if subentry is not None:
                    return self.async_update_and_abort(
                        entry, subentry, title=name, data=data
                    )
                return self.async_create_entry(title=name, data=data)

        if user_input is not None:
            suggested = user_input
        elif subentry is not None:
            suggested = {CONF_NAME: subentry.title, **subentry.data}
        else:
            suggested = {
                CONF_VAT: DEFAULT_VAT,
                CONF_BASE_PERIOD: BasePeriod.MONTH.value,
                CONF_CURRENT: False,
            }
        return self.async_show_form(
            step_id=kind,
            data_schema=self.add_suggested_values_to_schema(
                _tariff_schema(kind), suggested
            ),
            errors=errors,
        )

    def _clear_current(self, entry: ConfigEntry, keep: Any) -> None:
        """Only one tariff is the current one."""
        for other in tariff_subentries(entry):
            if other.data.get(CONF_CURRENT) and (
                keep is None or other.subentry_id != keep.subentry_id
            ):
                self.hass.config_entries.async_update_subentry(
                    entry, other, data={**other.data, CONF_CURRENT: False}
                )
