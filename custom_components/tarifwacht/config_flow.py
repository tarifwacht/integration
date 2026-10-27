"""Config flow: meter and two tariffs; more tariffs as subentries.

Setup asks for the meter, then a fixed price and a total-price sensor; both
become tariff subentries. "Add tariff" offers three kinds: fixed price, total
price sensor, exchange price plus surcharges. Reconfiguring the entry changes
name and meter; reconfiguring a tariff shows its form again. Every change
reloads the entry (update listener), which recomputes the whole period.
"""

from __future__ import annotations

from datetime import date
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
from homeassistant.util import dt as dt_util

from .const import (
    BERLIN,
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_CHANGES,
    CONF_CURRENT,
    CONF_DYNAMIC_BASE,
    CONF_DYNAMIC_PRICE,
    CONF_FIXED_BASE,
    CONF_FIXED_PRICE,
    CONF_FROM,
    CONF_GRID_FEE,
    CONF_KEY,
    CONF_KIND,
    CONF_LEVIES,
    CONF_MARGIN,
    CONF_METER,
    CONF_MODUL3,
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
from .modul3 import WindowError, overlaps, parse_windows
from .runtime import parse_price_state, price_unit_ok, tariff_subentries
from .tariff_config import (
    change_fields,
    default_titles,
    entry_data,
    initial_tariffs,
    state_at,
)
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


# Modul 3 form fields (stored together under "modul3").
M3_ACTIVE = "modul3_active"
M3_NT = "nt"
M3_HT = "ht"
M3_QUARTERS = "quarters"
M3_NT_WINDOWS = "nt_windows"
M3_HT_WINDOWS = "ht_windows"
QUARTERS = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=["1", "2", "3", "4"],
        multiple=True,
        translation_key=M3_QUARTERS,
        mode=selector.SelectSelectorMode.LIST,
    )
)


def _modul3_fields() -> dict[Any, Any]:
    return {
        vol.Required(M3_ACTIVE): selector.BooleanSelector(),
        vol.Optional(M3_NT): PRICE_NUMBER,
        vol.Optional(M3_HT): PRICE_NUMBER,
        vol.Optional(M3_QUARTERS): QUARTERS,
        vol.Optional(M3_NT_WINDOWS): selector.TextSelector(),
        vol.Optional(M3_HT_WINDOWS): selector.TextSelector(),
    }


def _modul3_suggested(modul3: dict[str, Any] | None) -> dict[str, Any]:
    modul3 = modul3 or {}
    return {
        M3_ACTIVE: bool(modul3.get("active")),
        M3_NT: modul3.get("nt"),
        M3_HT: modul3.get("ht"),
        M3_QUARTERS: [str(q) for q in modul3.get("quarters", [1, 2, 3, 4])],
        M3_NT_WINDOWS: modul3.get("nt_windows", ""),
        M3_HT_WINDOWS: modul3.get("ht_windows", ""),
    }


def _modul3_from_input(
    user_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Stored Modul 3 values and form errors (only checked when active)."""
    modul3 = {
        "active": bool(user_input.get(M3_ACTIVE)),
        "nt": float(user_input.get(M3_NT) or 0),
        "ht": float(user_input.get(M3_HT) or 0),
        "quarters": sorted(int(q) for q in user_input.get(M3_QUARTERS) or []),
        "nt_windows": (user_input.get(M3_NT_WINDOWS) or "").strip(),
        "ht_windows": (user_input.get(M3_HT_WINDOWS) or "").strip(),
    }
    errors: dict[str, str] = {}
    if not modul3["active"]:
        return modul3, errors
    windows: dict[str, list[tuple[int, int]]] = {}
    for field, key in ((M3_NT_WINDOWS, "nt_windows"), (M3_HT_WINDOWS, "ht_windows")):
        try:
            windows[field] = parse_windows(modul3[key])
        except WindowError as err:
            errors[field] = err.key
            continue
        if not windows[field]:
            # Each level must occur every day (BK8-22/010-A, tenor 3 c).
            errors[field] = "window_required"
    if not errors and overlaps(windows[M3_NT_WINDOWS], windows[M3_HT_WINDOWS]):
        errors[M3_HT_WINDOWS] = "window_overlap"
    for field, key in ((M3_NT, "nt"), (M3_HT, "ht")):
        if not modul3[key]:
            errors[field] = "price_required"
    if not modul3["quarters"]:
        errors[M3_QUARTERS] = "quarters_required"
    return modul3, errors


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
        """Edit the tariff, Modul 3, or add or remove a price change."""
        data = self._get_reconfigure_subentry().data
        options = ["edit"]
        if data[CONF_KIND] == KIND_DYNAMIC_MARKET:
            options.append("modul3")
        options.append("add_change")
        if data.get(CONF_CHANGES):
            options.append("remove_change")
        return self.async_show_menu(step_id="reconfigure", menu_options=options)

    async def async_step_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The form of the tariff's kind, prefilled (values from the start)."""
        kind = self._get_reconfigure_subentry().data[CONF_KIND]
        return await self._async_tariff_step(kind, None)

    async def async_step_modul3(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Time-variable grid fee (values from the start of the tariff)."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            modul3, errors = _modul3_from_input(user_input)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    data={**subentry.data, CONF_MODUL3: modul3},
                )
        return self.async_show_form(
            step_id="modul3",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_modul3_fields()),
                user_input or _modul3_suggested(subentry.data.get(CONF_MODUL3)),
            ),
            errors=errors,
            description_placeholders={
                "tariff": subentry.title,
                "grid_fee": f"{float(subentry.data.get(CONF_GRID_FEE) or 0):g}",
            },
        )

    async def async_step_add_change(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """New prices valid from a date (local midnight) on."""
        subentry = self._get_reconfigure_subentry()
        kind = subentry.data[CONF_KIND]
        changes: list[dict[str, Any]] = list(subentry.data.get(CONF_CHANGES, []))
        errors: dict[str, str] = {}
        if user_input is not None:
            valid_from = user_input[CONF_FROM]
            if any(c[CONF_FROM] == valid_from for c in changes):
                errors[CONF_FROM] = "change_exists"
            elif kind == KIND_FIXED and not user_input.get(CONF_PRICE):
                errors[CONF_PRICE] = "price_required"
            else:
                change: dict[str, Any] = {CONF_FROM: valid_from}
                for key in change_fields(kind):
                    if key == CONF_MODUL3:
                        change[key], errors = _modul3_from_input(user_input)
                    elif key == CONF_BASE_PERIOD:
                        change[key] = user_input[key]
                    else:
                        change[key] = float(user_input.get(key) or 0)
                if not errors:
                    changes = sorted([*changes, change], key=lambda c: c[CONF_FROM])
                    return self.async_update_and_abort(
                        self._get_entry(),
                        subentry,
                        data={**subentry.data, CONF_CHANGES: changes},
                    )

        fields: dict[Any, Any] = {vol.Required(CONF_FROM): selector.DateSelector()}
        for key in change_fields(kind):
            if key == CONF_MODUL3:
                fields.update(_modul3_fields())
            elif key == CONF_BASE_PERIOD:
                fields[vol.Required(key)] = BASE_PERIOD
            elif key == CONF_VAT:
                fields[vol.Required(key)] = VAT_NUMBER
            elif key == CONF_BASE_PRICE:
                fields[vol.Optional(key)] = BASE_NUMBER
            elif key == CONF_PRICE:
                fields[vol.Required(key)] = PRICE_NUMBER
            else:
                fields[vol.Optional(key)] = PRICE_NUMBER
        # Prefilled with the values valid today; changes start at midnight German time.
        if user_input is not None:
            suggested = user_input
        else:
            today = state_at(subentry.data, dt_util.now(BERLIN).date())
            suggested = {**today, **_modul3_suggested(today.get(CONF_MODUL3))}
        return self.async_show_form(
            step_id="add_change",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), suggested
            ),
            errors=errors,
            description_placeholders={"tariff": subentry.title},
        )

    async def async_step_remove_change(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Remove one price change."""
        subentry = self._get_reconfigure_subentry()
        changes: list[dict[str, Any]] = list(subentry.data.get(CONF_CHANGES, []))
        if user_input is not None:
            remaining = [c for c in changes if c[CONF_FROM] != user_input[CONF_FROM]]
            data = {**subentry.data, CONF_CHANGES: remaining}
            if not remaining:
                del data[CONF_CHANGES]
            return self.async_update_and_abort(self._get_entry(), subentry, data=data)

        german = self.hass.config.language.startswith("de")
        options = [
            selector.SelectOptionDict(
                value=c[CONF_FROM],
                label=date.fromisoformat(c[CONF_FROM]).strftime("%d.%m.%Y")
                if german
                else c[CONF_FROM],
            )
            for c in changes
        ]
        return self.async_show_form(
            step_id="remove_change",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FROM): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, mode=selector.SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            description_placeholders={"tariff": subentry.title},
        )

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
                if subentry is not None:
                    # Keep the stable key and the price changes.
                    for keep in (CONF_KEY, CONF_CHANGES):
                        if subentry.data.get(keep):
                            data[keep] = subentry.data[keep]
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
