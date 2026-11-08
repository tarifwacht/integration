"""Actions: tarifwacht.compare (costs of every tariff in a chosen period) and
tarifwacht.import_statistics (history before the statistics; with `replace`
the statistics from the start on recalculated)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.selector import ConfigEntrySelector
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .smard import ATTRIBUTION
from .smard_cache import SmardError
from .statistics_import import (
    StatisticsImportError,
    async_import_history,
    async_recalculate,
    implausible_summary,
)

if TYPE_CHECKING:
    from . import TarifwachtConfigEntry
    from .engine import PeriodCosts
    from .runtime import MeterRuntime
    from .solar import SolarResult, SolarTotals

SERVICE_COMPARE = "compare"
SERVICE_IMPORT_STATISTICS = "import_statistics"
ATTR_CONFIG_ENTRY = "config_entry"
ATTR_START = "start"
ATTR_END = "end"
ATTR_REPLACE = "replace"

COMPARE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
    }
)
IMPORT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Required(ATTR_START): cv.date,
        vol.Optional(ATTR_REPLACE, default=False): cv.boolean,
    }
)


def _as_utc(moment: datetime) -> datetime:
    """Times without zone are local time of Home Assistant."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(moment)


def _tariff_rows(
    runtime: MeterRuntime, costs: PeriodCosts, *, details: bool
) -> list[dict[str, Any]]:
    """One row per tariff: complete ones (every kWh priced) by cost, then the rest.

    `cost` is consumption cost plus base price less a one-off bonus whose
    date lies in the period (`bonus`).

    The difference to the current tariff only if both priced every kWh: a
    tariff with energy without price would look cheaper than it is.
    """
    current = runtime.current
    current_totals = costs.totals[current.key] if current is not None else None
    rows: list[dict[str, Any]] = []
    for tariff in runtime.tariffs.values():
        totals = costs.totals[tariff.key]
        difference = None
        if current_totals is not None and not (
            current_totals.energy_without_price or totals.energy_without_price
        ):
            difference = round(totals.cost - current_totals.cost, 4)
        row: dict[str, Any] = {"tariff": tariff.title}
        if details:
            average = totals.average_price
            row |= {
                "current": tariff.current,
                "consumption_cost": round(totals.consumption_cost, 4),
                "base_cost": round(totals.base_cost, 4),
                "bonus": round(totals.bonus, 4),
                "average_price_ct": None
                if average is None
                else round(average * 100, 3),
            }
        elif totals.bonus:
            # Per month only in the month the bonus falls in.
            row["bonus"] = round(totals.bonus, 4)
        row |= {
            "cost": round(totals.cost, 4),
            "difference_to_current": difference,
            "energy_without_price_kwh": round(totals.energy_without_price, 4),
        }
        rows.append(row)
    rows.sort(key=lambda r: (r["energy_without_price_kwh"] > 0, r["cost"]))
    return rows


def _solar_rows(
    runtime: MeterRuntime, totals: Mapping[str, SolarTotals], *, details: bool
) -> list[dict[str, Any]]:
    """One row per tariff: what PV and battery saved under it (EUR)."""
    rows: list[dict[str, Any]] = []
    for tariff in runtime.tariffs.values():
        t = totals[tariff.key]
        row: dict[str, Any] = {
            "tariff": tariff.title,
            "saving_pv": round(t.saving_pv, 2),
            "saving_battery": round(t.saving_battery, 2),
        }
        if details:
            value = t.battery_value
            row |= {
                "cost_without_pv_and_battery": round(t.without, 2),
                "cost_pv_without_battery": round(t.pv_only, 2),
                "cost_actual": round(t.actual, 2),
                "battery_value_per_kwh_ct": None
                if value is None
                else round(value * 100, 1),
                "hours_left_out": t.hours_left_out,
            }
        rows.append(row)
    return rows


def _solar_response(runtime: MeterRuntime, result: SolarResult) -> dict[str, Any]:
    any_totals = next(iter(result.totals.values()), None)
    response: dict[str, Any] = {
        "tariffs": _solar_rows(runtime, result.totals, details=True)
    }
    if any_totals is not None:
        response |= {
            "consumption_kwh": round(any_totals.consumption, 3),
            "pv_kwh": round(any_totals.pv, 3),
            "purchase_kwh": round(any_totals.purchase, 3),
            "feed_in_kwh": round(any_totals.feed_in, 3),
            "feed_in_unpaid_kwh": round(any_totals.feed_in_unpaid, 3),
            "charged_kwh": round(any_totals.charged, 3),
            "discharged_kwh": round(any_totals.discharged, 3),
        }
    response["months"] = [
        {"month": month, "tariffs": _solar_rows(runtime, totals, details=False)}
        for month, totals in result.months.items()
    ]
    return response


def _cheapest(rows: list[dict[str, Any]]) -> str | None:
    """Only a tariff that priced every kWh can be the cheapest."""
    complete = [r for r in rows if r["energy_without_price_kwh"] == 0]
    return complete[0]["tariff"] if complete else None


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    async def compare(call: ServiceCall) -> ServiceResponse:
        entry: TarifwachtConfigEntry = service.async_get_config_entry(
            hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY]
        )
        runtime = entry.runtime_data
        engine = runtime.engine
        now = dt_util.utcnow()
        start = _as_utc(call.data[ATTR_START]) if ATTR_START in call.data else None
        end = _as_utc(call.data[ATTR_END]) if ATTR_END in call.data else now
        start = start or engine.started or now
        if start >= end:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="start_after_end"
            )
        try:
            lookback = await runtime.async_lookback(start)
        except SmardError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="smard_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        result = engine.costs_between(start, end, now, lookback)
        rows = _tariff_rows(runtime, result, details=True)
        response: dict[str, Any] = {
            "start": dt_util.as_local(result.start).isoformat(),
            "end": dt_util.as_local(result.end).isoformat(),
            "energy_kwh": round(result.energy, 4),
            "quarter_hours": result.quarter_hours,
            "cheapest": _cheapest(rows),
            "tariffs": rows,
        }
        if lookback is not None:
            response["estimate"] = {
                "until": dt_util.as_local(lookback.until).isoformat(),
                "energy_kwh": round(result.estimated_energy, 4),
                "hours_without_energy": lookback.hours_without_energy,
            }
            if lookback.uses_smard:
                response["estimate"]["exchange_prices"] = ATTRIBUTION
            if summary := implausible_summary(lookback.implausible_hours):
                response["estimate"]["hours_implausible"] = summary
        months = []
        for month, costs in result.months.items():
            month_rows = _tariff_rows(runtime, costs, details=False)
            months.append(
                {
                    "month": month,
                    "energy_kwh": round(costs.energy, 4),
                    "cheapest": _cheapest(month_rows),
                    "tariffs": month_rows,
                }
            )
        response["months"] = months
        try:
            solar = await runtime.async_solar_between(
                result.start, result.end, lookback
            )
        except SmardError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="smard_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if solar is not None:
            solar_result, used_smard, implausible = solar
            response["pv_battery"] = _solar_response(runtime, solar_result)
            if used_smard:
                response["pv_battery"]["exchange_prices"] = ATTRIBUTION
            if summary := implausible_summary(implausible):
                response["pv_battery"]["hours_implausible"] = summary
        return response

    async def import_statistics(call: ServiceCall) -> ServiceResponse:
        entry: TarifwachtConfigEntry = service.async_get_config_entry(
            hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY]
        )
        try:
            if call.data[ATTR_REPLACE]:
                result = await async_recalculate(hass, entry, call.data[ATTR_START])
            else:
                result = await async_import_history(hass, entry, call.data[ATTR_START])
        except StatisticsImportError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=f"import_{err.key}"
            ) from err
        except SmardError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="smard_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return result if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPARE,
        compare,
        schema=COMPARE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_STATISTICS,
        import_statistics,
        schema=IMPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
