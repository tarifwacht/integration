"""Config flow: meter and two tariffs; more tariffs as subentries.

Setup asks for the meter, the fixed price, then how the dynamic tariff is
priced: exchange price plus surcharges (recommended, the only kind that can
look back before the setup) or a total-price sensor; both tariffs become
subentries. "Add tariff" offers the same three kinds. Reconfiguring the entry changes
name and meter; reconfiguring a tariff shows its form again. Every change
reloads the entry (update listener), which recomputes the whole period.

Forms show the prices at first glance; what is rarely changed (VAT, base
price per year, bonus, Modul 3 in a price change) sits in collapsed
sections. Sections only shape the form: the stored keys stay flat.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    BERLIN,
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_BONUS,
    CONF_BONUS_DATE,
    CONF_CHANGES,
    CONF_CURRENT,
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
    CONF_RENAMED,
    CONF_SMARD_FILL,
    CONF_VAT,
    DEFAULT_VAT,
    DOMAIN,
    KIND_DYNAMIC_MARKET,
    KIND_DYNAMIC_TOTAL,
    KIND_FIXED,
    KINDS,
    SECTION_BONUS,
    SECTION_DETAILS,
    SECTION_MODUL3,
    SUBENTRY_SOLAR,
    SUBENTRY_TARIFF,
    TARIFF_DYNAMIC,
)
from .meter import UNIT_FACTORS
from .modul3 import WindowError, overlaps, parse_windows
from .runtime import (
    own_entity,
    parse_price_state,
    price_unit_ok,
    tariff_subentries,
)
from .solar_flow import SolarSubentryFlow
from .suggest import async_suggested_meter, suggested_price
from .tariff_config import (
    MODUL3_STANDARD,
    MODUL3_VAT,
    change_fields,
    default_titles,
    entry_data,
    initial_fixed_tariff,
    price_entity,
    state_at,
)
from .tariff_summary import edit_hint, summary
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
    if own_entity(hass, entity_id):
        return "own_entity"
    state = hass.states.get(entity_id)
    if state is None:
        return "entity_missing"
    # Before the unit: a sensor of an integration that is not loaded keeps
    # its unit from the registry, and "no price found" would mislead.
    if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return "price_unavailable"
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
        # Meter of the energy dashboard, looked up once when the form opens.
        self._suggested_meter: str | None = None

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TARIFF: TariffSubentryFlow, SUBENTRY_SOLAR: SolarSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: name and meter, the grid import of the energy dashboard
        suggested."""
        if self._async_current_entries(include_ignore=False):
            return await self.async_step_user_more(user_input)
        if user_input is None and CONF_METER not in self._data:
            self._suggested_meter = await async_suggested_meter(self.hass, set())
        return await self._async_meter_step("user", user_input)

    async def async_step_user_more(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 with an entry set up already: more tariffs for its meter
        belong under "Add tariff" there, so the form says so and suggests no
        meter (one from the energy dashboard mostly measures the same grid
        connection, and a second entry would compute everything twice)."""
        entries = self._async_current_entries(include_ignore=False)
        return await self._async_meter_step(
            "user_more",
            user_input,
            {"entries": ", ".join(entry.title for entry in entries)},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change name and meter; tariffs are changed in their subentries."""
        if not self._data:
            self._data = dict(self._get_reconfigure_entry().data)
        return await self._async_meter_step("reconfigure", user_input)

    async def _async_meter_step(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            meter = user_input[CONF_METER]
            if self.source == SOURCE_RECONFIGURE:
                current = self._get_reconfigure_entry().data[CONF_METER]
                if meter == self._data[CONF_METER] != current:
                    # Renamed while the form was open: it still showed the
                    # old id, which no longer exists.
                    meter = current
            if not name:
                errors[CONF_NAME] = "name_required"
            else:
                errors = self._validate_meter(meter)
            if not errors:
                self._data[CONF_NAME] = name
                self._data[CONF_METER] = meter
                if self.source == SOURCE_RECONFIGURE:
                    data = entry_data(self._data)
                    entry = self._get_reconfigure_entry()
                    if renamed := entry.data.get(CONF_RENAMED):
                        # Stored state still to move to renamed sources (as
                        # of now, not of opening the form).
                        data[CONF_RENAMED] = renamed
                    # The update listener reloads the entry.
                    return self.async_update_and_abort(
                        self._get_reconfigure_entry(),
                        unique_id=meter,
                        title=name,
                        data=data,
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
        suggested = user_input or self._data
        if user_input is None and self._suggested_meter and CONF_METER not in suggested:
            suggested = {**suggested, CONF_METER: self._suggested_meter}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _validate_meter(self, meter: str) -> dict[str, str]:
        current = (
            self._get_reconfigure_entry().entry_id
            if self.source == SOURCE_RECONFIGURE
            else None
        )
        if own_entity(self.hass, meter):
            return {CONF_METER: "own_entity"}
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
        """Step 2: the fixed price (the current tariff), optional base price."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_FIXED_PRICE):
                errors[CONF_FIXED_PRICE] = "price_required"
            else:
                self._data[CONF_FIXED_PRICE] = user_input[CONF_FIXED_PRICE]
                self._data[CONF_FIXED_BASE] = user_input.get(CONF_FIXED_BASE)
                return await self.async_step_dynamic()

        schema = vol.Schema(
            {
                vol.Optional(CONF_FIXED_PRICE): PRICE_NUMBER,
                vol.Optional(CONF_FIXED_BASE): BASE_NUMBER,
            }
        )
        return self.async_show_form(
            step_id="tariffs",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or self._data
            ),
            errors=errors,
        )

    async def async_step_dynamic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: how the dynamic tariff is priced, the recommended way first."""
        return self.async_show_menu(
            step_id="dynamic", menu_options=[KIND_DYNAMIC_MARKET, KIND_DYNAMIC_TOTAL]
        )

    async def async_step_dynamic_market(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_dynamic_step(KIND_DYNAMIC_MARKET, user_input)

    async def async_step_dynamic_total(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_dynamic_step(KIND_DYNAMIC_TOTAL, user_input)

    async def _async_dynamic_step(
        self, kind: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Step 4: the dynamic tariff's fields; its base price is per month."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := validate_price_entity(self.hass, user_input[CONF_PRICE_ENTITY]):
                errors[CONF_PRICE_ENTITY] = error
            else:
                return await self._async_create(
                    _tariff_data(
                        kind,
                        {
                            **flatten_details(user_input, {CONF_VAT: DEFAULT_VAT}),
                            CONF_BASE_PERIOD: BasePeriod.MONTH.value,
                            CONF_CURRENT: False,
                        },
                    )
                )

        suggested: dict[str, Any] = {SECTION_DETAILS: {CONF_VAT: DEFAULT_VAT}}
        if price := suggested_price(self.hass, kind):
            suggested[CONF_PRICE_ENTITY] = price
        return self.async_show_form(
            step_id=kind,
            data_schema=self.add_suggested_values_to_schema(
                _tariff_schema(kind, setup=True), user_input or suggested
            ),
            errors=errors,
        )

    async def _async_create(self, dynamic: dict[str, Any]) -> ConfigFlowResult:
        meter = self._data[CONF_METER]
        await self.async_set_unique_id(meter)
        self._abort_if_unique_id_configured()
        fixed_title, dynamic_title = default_titles(self.hass.config.language)
        tariffs = [
            (fixed_title, initial_fixed_tariff(self._data)),
            (dynamic_title, {CONF_KEY: TARIFF_DYNAMIC, **dynamic}),
        ]
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
                for title, data in tariffs
            ],
        )


def _collapsed(fields: dict[Any, Any], collapsed: bool = True) -> section:
    """A form section. Put it under vol.Optional without a default: the
    frontend takes a section's default over the suggested values of its
    fields (Wärmewacht 9c7e722); a missing section keeps what is stored."""
    return section(vol.Schema(fields), {"collapsed": collapsed})


# Rarely changed fields of a tariff and a price change (section "More"):
# VAT (exchange price only) and whether the base price is per month or year.
DETAILS = (CONF_VAT, CONF_BASE_PERIOD)


def _details_fields(kind: str, *, base_period: bool = True) -> dict[Any, Any]:
    fields: dict[Any, Any] = {}
    if kind == KIND_DYNAMIC_MARKET:
        fields[vol.Optional(CONF_VAT)] = VAT_NUMBER
    if base_period:
        fields[vol.Optional(CONF_BASE_PERIOD)] = BASE_PERIOD
    return fields


def flatten_details(
    user_input: dict[str, Any], fallback: Mapping[str, Any]
) -> dict[str, Any]:
    """The input with the fields of the section "More" at the top level, as
    stored. A field missing (or the section) takes the `fallback` value:
    the stored one when editing, the default when adding."""
    flat = {k: v for k, v in user_input.items() if k != SECTION_DETAILS}
    details = user_input.get(SECTION_DETAILS) or {}
    for key in DETAILS:
        if details.get(key) not in (None, ""):
            flat[key] = details[key]
        elif key in fallback:
            flat[key] = fallback[key]
    return flat


def details_suggested(values: Mapping[str, Any]) -> dict[str, Any]:
    """The section "More" filled from flat values."""
    return {key: values[key] for key in DETAILS if key in values}


def _tariff_schema(kind: str, *, setup: bool = False) -> vol.Schema:
    """The form of a tariff: name, prices and "my current tariff" at first
    glance. At the setup without name, current, SMARD.de and bonus (no time
    before to fill; a bonus is added in the tariff later), the base price
    per month."""
    fields: dict[Any, Any] = {}
    if not setup:
        fields[vol.Required(CONF_NAME)] = selector.TextSelector()
    if kind == KIND_FIXED:
        # Optional: a required number field shows its minimum (0) instead of
        # staying empty; the step reports a missing price itself.
        fields[vol.Optional(CONF_PRICE)] = PRICE_NUMBER
    else:
        fields[vol.Required(CONF_PRICE_ENTITY)] = PRICE_SENSOR
    if kind == KIND_DYNAMIC_MARKET:
        for key in (CONF_GRID_FEE, CONF_LEVIES, CONF_MARGIN):
            fields[vol.Optional(key)] = PRICE_NUMBER
    fields[vol.Optional(CONF_BASE_PRICE)] = BASE_NUMBER
    if not setup:
        fields[vol.Required(CONF_CURRENT)] = selector.BooleanSelector()
    if kind == KIND_DYNAMIC_MARKET and not setup:
        # Missing means no consent. Visible: the owner's decision of 30.10.
        fields[vol.Optional(CONF_SMARD_FILL)] = selector.BooleanSelector()
    if details := _details_fields(kind, base_period=not setup):
        fields[vol.Optional(SECTION_DETAILS)] = _collapsed(details)
    if setup:
        return vol.Schema(fields)
    fields[vol.Optional(SECTION_BONUS)] = _bonus_section()
    return vol.Schema(fields)


def _bonus_section() -> Any:
    """The collapsed section "Bonus": amount and the day it is credited on.
    In the tariff form and in a price change (the bonus of a new contract)."""
    return section(
        vol.Schema(
            {
                vol.Optional(CONF_BONUS): BASE_NUMBER,
                vol.Optional(CONF_BONUS_DATE): selector.DateSelector(),
            }
        ),
        {"collapsed": True},
    )


def bonus_error(user_input: dict[str, Any]) -> str | None:
    """A bonus needs the date it is credited on."""
    bonus = user_input.get(SECTION_BONUS) or {}
    if bonus.get(CONF_BONUS) and not bonus.get(CONF_BONUS_DATE):
        return "bonus_date_required"
    return None


def bonus_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """The bonus of the form's section as stored: {} without one."""
    bonus = user_input.get(SECTION_BONUS) or {}
    if float(bonus.get(CONF_BONUS) or 0) > 0 and bonus.get(CONF_BONUS_DATE):
        return {
            CONF_BONUS: float(bonus[CONF_BONUS]),
            CONF_BONUS_DATE: str(bonus[CONF_BONUS_DATE]),
        }
    return {}


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
    if kind == KIND_DYNAMIC_MARKET and CONF_SMARD_FILL in user_input:
        data[CONF_SMARD_FILL] = bool(user_input[CONF_SMARD_FILL])
    data.update(bonus_data(user_input))
    return data


# Modul 3 form fields (stored together under "modul3").
M3_ACTIVE = "modul3_active"
M3_NT = "nt"
M3_HT = "ht"
M3_QUARTERS = "quarters"
M3_NT_WINDOWS = "nt_windows"
M3_HT_WINDOWS = "ht_windows"
# Fixed price only: the standard grid fee contained in it, VAT on the difference.
M3_STANDARD = "standard_fee"
M3_VAT = CONF_VAT
QUARTERS = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=["1", "2", "3", "4"],
        multiple=True,
        translation_key=M3_QUARTERS,
        mode=selector.SelectSelectorMode.LIST,
    )
)


def _modul3_fields(kind: str, *, in_section: bool = False) -> dict[Any, Any]:
    if kind != KIND_FIXED and not in_section:
        fields: dict[Any, Any] = {vol.Required(M3_ACTIVE): selector.BooleanSelector()}
    elif kind != KIND_FIXED:
        fields = {vol.Optional(M3_ACTIVE): selector.BooleanSelector()}
    else:
        # Optional: a price change of a fixed tariff without the Modul 3
        # fields (as before) keeps the Modul 3 values valid until then.
        fields = {
            vol.Optional(M3_ACTIVE): selector.BooleanSelector(),
            vol.Optional(M3_STANDARD): PRICE_NUMBER,
            vol.Optional(M3_VAT): VAT_NUMBER,
        }
    return fields | {
        vol.Optional(M3_NT): PRICE_NUMBER,
        vol.Optional(M3_HT): PRICE_NUMBER,
        vol.Optional(M3_QUARTERS): QUARTERS,
        vol.Optional(M3_NT_WINDOWS): selector.TextSelector(),
        vol.Optional(M3_HT_WINDOWS): selector.TextSelector(),
    }


def _modul3_suggested(modul3: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    modul3 = modul3 or {}
    fixed: dict[str, Any] = {}
    if kind == KIND_FIXED:
        fixed = {
            M3_STANDARD: modul3.get(MODUL3_STANDARD),
            M3_VAT: modul3.get(MODUL3_VAT, DEFAULT_VAT),
        }
    return fixed | {
        M3_ACTIVE: bool(modul3.get("active")),
        M3_NT: modul3.get("nt"),
        M3_HT: modul3.get("ht"),
        M3_QUARTERS: [str(q) for q in modul3.get("quarters", [1, 2, 3, 4])],
        M3_NT_WINDOWS: modul3.get("nt_windows", ""),
        M3_HT_WINDOWS: modul3.get("ht_windows", ""),
    }


def _modul3_from_input(
    user_input: dict[str, Any], kind: str
) -> tuple[dict[str, Any], dict[str, str]]:
    """Stored Modul 3 values and form errors (only checked when active).

    A fixed price also keeps the standard grid fee it contains and the VAT
    on the difference (tariff_config.MODUL3_STANDARD, MODUL3_VAT).
    """
    modul3: dict[str, Any] = {
        "active": bool(user_input.get(M3_ACTIVE)),
        "nt": float(user_input.get(M3_NT) or 0),
        "ht": float(user_input.get(M3_HT) or 0),
        "quarters": sorted(int(q) for q in user_input.get(M3_QUARTERS) or []),
        "nt_windows": (user_input.get(M3_NT_WINDOWS) or "").strip(),
        "ht_windows": (user_input.get(M3_HT_WINDOWS) or "").strip(),
    }
    if kind == KIND_FIXED:
        vat = user_input.get(M3_VAT)
        modul3[MODUL3_STANDARD] = float(user_input.get(M3_STANDARD) or 0)
        modul3[MODUL3_VAT] = float(DEFAULT_VAT if vat is None else vat)
    errors: dict[str, str] = {}
    if not modul3["active"]:
        return modul3, errors
    if kind == KIND_FIXED and not modul3[MODUL3_STANDARD]:
        errors[M3_STANDARD] = "price_required"
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


def modul3_base_error(errors: Mapping[str, str]) -> str:
    """An error of a Modul 3 field in the price change's section, shown on
    top of the form (errors of fields inside a section have no place of
    their own)."""
    key = next(iter(errors.values()))
    return "modul3_price_required" if key == "price_required" else key


class TariffSubentryFlow(ConfigSubentryFlow):
    """Add or change one tariff."""

    # The price sensor the edit form showed (to follow a rename meanwhile).
    _shown_price: str | None = None

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
        if data[CONF_KIND] in (KIND_DYNAMIC_MARKET, KIND_FIXED):
            options.append("modul3")
        options.append("add_change")
        if data.get(CONF_CHANGES):
            options.append("remove_change")
        # On top what applies today and every price state: the list of
        # subentries shows only the tariff's name.
        sensor_name = None
        if entity := price_entity(data):
            state = self.hass.states.get(entity)
            sensor_name = state.name if state is not None else entity
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=options,
            description_placeholders={
                "summary": summary(
                    data,
                    dt_util.now(BERLIN).date(),
                    german=self._german,
                    sensor_name=sensor_name,
                )
            },
        )

    @property
    def _german(self) -> bool:
        return self.hass.config.language.startswith("de")

    async def async_step_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """ "Edit prices from the start": the form of the tariff's kind,
        prefilled with the values from the start (also name, current tariff
        and bonus)."""
        kind = self._get_reconfigure_subentry().data[CONF_KIND]
        return await self._async_tariff_step(kind, None)

    async def async_step_modul3(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Time-variable grid fee (values from the start of the tariff)."""
        if self._get_reconfigure_subentry().data[CONF_KIND] == KIND_FIXED:
            return await self.async_step_modul3_fixed(user_input)
        return await self._async_modul3_step("modul3", user_input)

    async def async_step_modul3_fixed(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Modul 3 passed on by a fixed-price supplier: the form also asks
        for the standard grid fee contained in the price."""
        return await self._async_modul3_step("modul3_fixed", user_input)

    async def _async_modul3_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        kind = subentry.data[CONF_KIND]
        errors: dict[str, str] = {}
        if user_input is not None:
            modul3, errors = _modul3_from_input(user_input, kind)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    data={**subentry.data, CONF_MODUL3: modul3},
                )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_modul3_fields(kind)),
                user_input or _modul3_suggested(subentry.data.get(CONF_MODUL3), kind),
            ),
            errors=errors,
            description_placeholders={
                "tariff": subentry.title,
                "grid_fee": f"{float(subentry.data.get(CONF_GRID_FEE) or 0):g}",
                "price": f"{float(subentry.data.get(CONF_PRICE) or 0):g}",
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
        # Prefilled with the values valid today; changes start at midnight
        # German time.
        today = state_at(subentry.data, dt_util.now(BERLIN).date())
        if user_input is not None:
            valid_from = user_input[CONF_FROM]
            flat = flatten_details(user_input, today)
            modul3_input = user_input.get(SECTION_MODUL3)
            if any(c[CONF_FROM] == valid_from for c in changes):
                errors[CONF_FROM] = "change_exists"
            elif kind == KIND_FIXED and not user_input.get(CONF_PRICE):
                errors[CONF_PRICE] = "price_required"
            elif error := bonus_error(user_input):
                errors["base"] = error
            else:
                # A new contract may bring its own bonus.
                change: dict[str, Any] = {CONF_FROM: valid_from}
                change.update(bonus_data(user_input))
                for key in change_fields(kind):
                    if key == CONF_MODUL3:
                        # Without the section (or, for a fixed price, its
                        # switch) the Modul 3 values before stay valid.
                        if modul3_input is None or (
                            kind == KIND_FIXED and M3_ACTIVE not in modul3_input
                        ):
                            continue
                        change[key], modul3_errors = _modul3_from_input(
                            modul3_input, kind
                        )
                        if modul3_errors:
                            errors["base"] = modul3_base_error(modul3_errors)
                    elif key == CONF_BASE_PERIOD:
                        change[key] = flat[key]
                    else:
                        change[key] = float(flat.get(key) or 0)
                if not errors:
                    changes = sorted([*changes, change], key=lambda c: c[CONF_FROM])
                    return self.async_update_and_abort(
                        self._get_entry(),
                        subentry,
                        data={**subentry.data, CONF_CHANGES: changes},
                    )

        # At first glance the prices; VAT, base price period and Modul 3 in
        # collapsed sections - Modul 3 open if the tariff uses it today.
        fields: dict[Any, Any] = {vol.Required(CONF_FROM): selector.DateSelector()}
        for key in change_fields(kind):
            if key in (CONF_MODUL3, *DETAILS):
                continue
            fields[vol.Optional(key)] = (
                BASE_NUMBER if key == CONF_BASE_PRICE else PRICE_NUMBER
            )
        fields[vol.Optional(SECTION_DETAILS)] = _collapsed(_details_fields(kind))
        modul3_today = today.get(CONF_MODUL3) or {}
        if CONF_MODUL3 in change_fields(kind):
            fields[vol.Optional(SECTION_MODUL3)] = _collapsed(
                _modul3_fields(kind, in_section=True),
                collapsed=not modul3_today.get("active"),
            )
        # Empty: the bonuses before stay with their tariff or change.
        fields[vol.Optional(SECTION_BONUS)] = _bonus_section()
        if user_input is not None:
            suggested = user_input
        else:
            suggested = {
                **today,
                SECTION_DETAILS: details_suggested(today),
                SECTION_MODUL3: _modul3_suggested(modul3_today, kind),
            }
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

        options = [
            selector.SelectOptionDict(
                value=c[CONF_FROM],
                label=date.fromisoformat(c[CONF_FROM]).strftime("%d.%m.%Y")
                if self._german
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
            # VAT and base price period: from the section "More"; missing,
            # the stored values (edit) or the defaults (add).
            raw = user_input
            user_input = flatten_details(
                user_input,
                subentry.data
                if subentry is not None
                else {CONF_VAT: DEFAULT_VAT, CONF_BASE_PERIOD: BasePeriod.MONTH.value},
            )
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
            if (
                subentry is not None
                and kind != KIND_FIXED
                and user_input[CONF_PRICE_ENTITY] == self._shown_price
                and (current := subentry.data.get(CONF_PRICE_ENTITY))
                != self._shown_price
            ):
                # Renamed while the form was open: it still showed the old id.
                user_input = {**user_input, CONF_PRICE_ENTITY: current}
            if kind != KIND_FIXED and (
                error := validate_price_entity(self.hass, user_input[CONF_PRICE_ENTITY])
            ):
                errors[CONF_PRICE_ENTITY] = error
            if error := bonus_error(user_input):
                errors["base"] = error
            if not errors:
                data = _tariff_data(kind, user_input)
                if subentry is not None:
                    # Keep the stable key, the price changes and Modul 3:
                    # the edit form does not show them. The bonus too if
                    # its section did not come back.
                    keeps = [CONF_KEY, CONF_CHANGES, CONF_MODUL3]
                    if SECTION_BONUS not in raw:
                        keeps += [CONF_BONUS, CONF_BONUS_DATE]
                    for keep in keeps:
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
            suggested = raw
        elif subentry is not None:
            # SMARD.de only with consent: unticked unless agreed before.
            suggested = {
                CONF_NAME: subentry.title,
                CONF_SMARD_FILL: False,
                **subentry.data,
                SECTION_DETAILS: details_suggested(subentry.data),
                SECTION_BONUS: {
                    key: subentry.data[key]
                    for key in (CONF_BONUS, CONF_BONUS_DATE)
                    if key in subentry.data
                },
            }
            self._shown_price = subentry.data.get(CONF_PRICE_ENTITY)
        else:
            suggested = {
                SECTION_DETAILS: {
                    CONF_VAT: DEFAULT_VAT,
                    CONF_BASE_PERIOD: BasePeriod.MONTH.value,
                },
                CONF_CURRENT: False,
                CONF_SMARD_FILL: True,
            }
            if kind != KIND_FIXED and (
                price := suggested_price(
                    self.hass, kind, (s.data for s in tariff_subentries(entry))
                )
            ):
                suggested[CONF_PRICE_ENTITY] = price
        return self.async_show_form(
            step_id=kind,
            data_schema=self.add_suggested_values_to_schema(
                _tariff_schema(kind), suggested
            ),
            errors=errors,
            # Editing shows the values from the start: say so, and where a
            # later price goes.
            description_placeholders={
                "edit_hint": edit_hint(self._german) if subentry is not None else ""
            },
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
