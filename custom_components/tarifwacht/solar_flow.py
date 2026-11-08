"""Subentry flow "PV and battery": the meters and what feed-in earns.

At most one per entry. Prefilled from an Einspeisewacht entry if there is
one (feed-in meter, rate, the negative price rule, exchange price sensor) and
from a Speicherwacht entry (battery meters); copied once, no dependency at
runtime. The form names the entries, or links the sisters if there is none.
Whether the battery sits behind the PV inverter is asked in plain words,
with the answer the data suggest. Rarely needed fields sit in collapsed
sections: the exchange price sensor for section 51 (the exchange price
tariff's sensor does without it) and the purchase of PV and battery
(payback.py). Stored flat, as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import ATTR_STATE_CLASS, SensorStateClass
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_COST,
    CONF_BATTERY_SINCE,
    CONF_CHARGED_ENTITY,
    CONF_DISCHARGED_ENTITY,
    CONF_FEED_IN_ENTITY,
    CONF_FEED_IN_RATE,
    CONF_MARKET_ENTITY,
    CONF_METER,
    CONF_NEGATIVE_UNPAID,
    CONF_PV_COST,
    CONF_PV_ENTITY,
    CONF_PV_SINCE,
    CONF_SAME_INVERTER,
    PURCHASE_KEYS,
    SECTION_MARKET,
    SECTION_PURCHASE,
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
# Selector units are not translated.
COST = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=1_000_000,
        step=1,
        unit_of_measurement="€",
        mode=selector.NumberSelectorMode.BOX,
    )
)
METERS = (
    CONF_FEED_IN_ENTITY,
    CONF_PV_ENTITY,
    CONF_CHARGED_ENTITY,
    CONF_DISCHARGED_ENTITY,
)


EINSPEISEWACHT = "einspeisewacht"
SPEICHERWACHT = "speicherwacht"
# The form links the sisters when none is set up.
SISTER_URLS = {
    "einspeisewacht_url": "https://github.com/einspeisewacht/integration",
    "speicherwacht_url": "https://github.com/speicherwacht/integration",
}


def from_einspeisewacht(data: Mapping[str, Any]) -> dict[str, Any]:
    """Suggested values from the data of an Einspeisewacht entry."""
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


def from_speicherwacht(data: Mapping[str, Any]) -> dict[str, Any]:
    """Suggested battery meters from the data of a Speicherwacht entry."""
    entities = data.get("entities") or {}
    charged, discharged = entities.get("charged"), entities.get("discharged")
    if not (charged and discharged):
        return {}
    return {CONF_CHARGED_ENTITY: charged, CONF_DISCHARGED_ENTITY: discharged}


def from_sisters(hass: HomeAssistant) -> tuple[dict[str, Any], dict[str, str]]:
    """Suggested values from the first Einspeisewacht and Speicherwacht entry,
    and the titles of the entries that gave some (by domain)."""
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for domain, read in (
        (EINSPEISEWACHT, from_einspeisewacht),
        (SPEICHERWACHT, from_speicherwacht),
    ):
        entries = hass.config_entries.async_entries(domain, include_ignore=False)
        if not entries:
            continue
        found = {k: v for k, v in read(entries[0].data).items() if k not in values}
        if found:
            values.update(found)
            sources[domain] = entries[0].title
    return values, sources


def suggestion_step(sources: Mapping[str, str]) -> str:
    """The step whose text names where the suggestions come from."""
    if not sources:
        return "user"
    if len(sources) > 1:
        return "suggested_both"
    return f"suggested_{next(iter(sources))}"


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


def purchase_values(data: Mapping[str, Any]) -> dict[str, Any]:
    """The stored purchase fields, as the section shows them."""
    return {key: data[key] for key in PURCHASE_KEYS if data.get(key) is not None}


def purchase_error(user_input: Mapping[str, Any]) -> str | None:
    """A cost needs its commissioning date (the battery: its own or the
    PV's), the battery's cost the battery meters."""
    values = user_input.get(SECTION_PURCHASE) or {}
    if values.get(CONF_PV_COST) and not values.get(CONF_PV_SINCE):
        return "purchase_date_required"
    if values.get(CONF_BATTERY_COST):
        if not (
            user_input.get(CONF_CHARGED_ENTITY)
            and user_input.get(CONF_DISCHARGED_ENTITY)
        ):
            return "battery_cost_without_meters"
        if not (values.get(CONF_BATTERY_SINCE) or values.get(CONF_PV_SINCE)):
            return "purchase_date_required"
    return None


def purchase_data(values: Mapping[str, Any]) -> dict[str, Any]:
    """What the subentry stores of the section: costs above 0 with dates."""
    data: dict[str, Any] = {}
    for cost, since in (
        (CONF_PV_COST, CONF_PV_SINCE),
        (CONF_BATTERY_COST, CONF_BATTERY_SINCE),
    ):
        if float(values.get(cost) or 0) > 0:
            data[cost] = float(values[cost])
        if values.get(since):
            data[since] = str(values[since])
    return data


def _schema(values: dict[str, Any]) -> vol.Schema:
    def suggested(key: str, source: Mapping[str, Any] = values) -> dict[str, Any]:
        return {"suggested_value": source.get(key)}

    shown = values.get(SECTION_PURCHASE)
    purchase = purchase_values(values) if shown is None else shown
    market = values.get(SECTION_MARKET)
    if market is None:
        market = {CONF_MARKET_ENTITY: values.get(CONF_MARKET_ENTITY)}

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
            # Collapsed sections: optional and without a default, the
            # frontend takes a section's default over the suggested values
            # of its fields (Wärmewacht 9c7e722); missing input keeps the
            # stored (or suggested) values.
            vol.Optional(SECTION_MARKET): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_MARKET_ENTITY,
                            description=suggested(CONF_MARKET_ENTITY, market),
                        ): PRICE_SENSOR
                    }
                ),
                {"collapsed": True},
            ),
            vol.Optional(SECTION_PURCHASE): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_PV_COST, description=suggested(CONF_PV_COST, purchase)
                        ): COST,
                        vol.Optional(
                            CONF_PV_SINCE,
                            description=suggested(CONF_PV_SINCE, purchase),
                        ): selector.DateSelector(),
                        vol.Optional(
                            CONF_BATTERY_COST,
                            description=suggested(CONF_BATTERY_COST, purchase),
                        ): COST,
                        vol.Optional(
                            CONF_BATTERY_SINCE,
                            description=suggested(CONF_BATTERY_SINCE, purchase),
                        ): selector.DateSelector(),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


class SolarSubentryFlow(ConfigSubentryFlow):
    """Add or change PV and battery."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._detected: bool | None = None
        self._placeholders: dict[str, str] = {}
        # Values suggested from the sisters: kept if a section does not
        # come back with the input.
        self._suggested: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        if any(s.subentry_type == SUBENTRY_SOLAR for s in entry.subentries.values()):
            return self.async_abort(reason="single_solar")
        if user_input is not None:
            return await self._async_meters("user", user_input, {})
        values, sources = from_sisters(self.hass)
        self._suggested = values
        self._placeholders = {**SISTER_URLS, **sources}
        return await self._async_meters(suggestion_step(sources), None, values)

    # One step per source of the suggestions, so that each has its own text
    # (see the battery steps below); "user" has none and shows the tip.
    async def async_step_suggested_einspeisewacht(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_meters("suggested_einspeisewacht", user_input, {})

    async def async_step_suggested_speicherwacht(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_meters("suggested_speicherwacht", user_input, {})

    async def async_step_suggested_both(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_meters("suggested_both", user_input, {})

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
            before = (
                self._get_reconfigure_subentry().data
                if self.source == "reconfigure"
                else self._suggested
            )
            if SECTION_PURCHASE not in values and self.source == "reconfigure":
                values |= purchase_values(before)
            if SECTION_MARKET in user_input:
                market_entity = user_input[SECTION_MARKET].get(CONF_MARKET_ENTITY)
            else:
                market_entity = before.get(CONF_MARKET_ENTITY)
                values[SECTION_MARKET] = {CONF_MARKET_ENTITY: market_entity}
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
                market_entity or self._has_market_tariff()
            ):
                # The field is in a collapsed section: the error on top.
                errors.setdefault("base", "market_required")
            if "base" not in errors and (error := purchase_error(user_input)):
                errors["base"] = error
            if not errors:
                self._data = {
                    k: v
                    for k, v in user_input.items()
                    if v not in (None, "")
                    and k not in (SECTION_PURCHASE, SECTION_MARKET)
                }
                if market_entity:
                    self._data[CONF_MARKET_ENTITY] = market_entity
                if SECTION_PURCHASE in user_input:
                    self._data |= purchase_data(user_input[SECTION_PURCHASE])
                elif self.source == "reconfigure":
                    # The section did not come back: keep what is stored.
                    self._data |= purchase_values(self._get_reconfigure_subentry().data)
                if charged and discharged:
                    self._detected = await async_detect_same_inverter(
                        self.hass, user_input[CONF_PV_ENTITY], charged, discharged
                    )
                    return await self._async_battery(None)
                self._data[CONF_SAME_INVERTER] = False
                return self._finish()
        return self.async_show_form(
            step_id=step_id,
            data_schema=_schema(values),
            errors=errors,
            description_placeholders=self._placeholders,
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
