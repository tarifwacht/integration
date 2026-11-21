"""Actions: tarifwacht.compare (costs of every tariff in a chosen period),
tarifwacht.import_statistics (history before the statistics; with `replace`
the statistics from the start on recalculated), tarifwacht.backfill_price (a
user-confirmed constant price for missing quarter-hours), and
tarifwacht.simulate_battery (what an imagined battery would have saved)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta
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

from .battery_sim import (
    DEFAULT_C_RATE,
    DEFAULT_EFFICIENCY,
    DEFAULT_SIZES,
    LIFETIMES,
    YEAR_DAYS,
    SimResult,
    SimSettings,
    SimTotals,
    per_year,
)
from .const import DOMAIN
from .payback import payback_attributes
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
SERVICE_SIMULATE_BATTERY = "simulate_battery"
SERVICE_BACKFILL_PRICE = "backfill_price"
ATTR_CONFIG_ENTRY = "config_entry"
ATTR_START = "start"
ATTR_END = "end"
ATTR_REPLACE = "replace"
ATTR_SIZES = "sizes"
ATTR_POWER = "power"
ATTR_EFFICIENCY = "efficiency"
ATTR_GRID_CHARGING = "grid_charging"
ATTR_GRID_POWER = "grid_power"
ATTR_PRICE_ENTITY = "price_entity"
ATTR_PRICE = "price"
# Without a start the simulation looks back a year.
SIMULATION_DAYS = 365
MAX_SIZES = 6
# A backfill builds the whole range in the event loop; more than a year
# (and a leap day) would block it for no sensible price gap.
BACKFILL_MAX_SPAN = timedelta(days=366)

COMPARE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
    }
)


def _sizes(value: Any) -> list[float]:
    """Sizes in kWh from the select (texts, "7,5" allowed) or a list."""
    items = value if isinstance(value, list) else [value]
    sizes: list[float] = []
    for item in items:
        try:
            size = float(str(item).replace(",", ".").strip())
        except ValueError as err:
            raise vol.Invalid(f"not a size in kWh: {item}") from err
        if not 0 < size <= 100:
            raise vol.Invalid(f"size out of range: {item}")
        if size not in sizes:
            sizes.append(size)
    if not sizes or len(sizes) > MAX_SIZES:
        raise vol.Invalid("one to six sizes")
    return sorted(sizes)


SIMULATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
        vol.Optional(ATTR_SIZES): _sizes,
        vol.Optional(ATTR_POWER): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=50)
        ),
        vol.Optional(ATTR_EFFICIENCY): vol.All(
            vol.Coerce(float), vol.Range(min=50, max=100)
        ),
        vol.Optional(ATTR_GRID_CHARGING, default=False): cv.boolean,
        vol.Optional(ATTR_GRID_POWER): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=50)
        ),
    }
)
IMPORT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Required(ATTR_START): cv.date,
        vol.Optional(ATTR_REPLACE, default=False): cv.boolean,
    }
)
BACKFILL_PRICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Required(ATTR_PRICE_ENTITY): cv.entity_id,
        vol.Required(ATTR_START): cv.datetime,
        vol.Required(ATTR_END): cv.datetime,
        vol.Required(ATTR_PRICE): vol.Coerce(float),
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
    if runtime.payback:
        # As the saving sensors show it now, whatever the period.
        response["payback"] = [
            {
                "tariff": tariff.title,
                **{
                    part: payback_attributes(state)
                    for part, state in runtime.payback.get(tariff.key, {}).items()
                },
            }
            for tariff in runtime.tariffs.values()
        ]
    return response


def _simulation_response(
    runtime: MeterRuntime,
    simulated: SimResult,
    real: SolarResult,
    batteries: list[SimSettings],
) -> dict[str, Any]:
    """Per tariff and size: saving, per year, cycles, purchase price it pays
    off up to; per month the saving only."""
    days = simulated.days
    has_battery = any(t.discharged > 0 for t in real.totals.values())
    grid = batteries[0].grid_charging

    def size_row(sim: SimSettings, t: SimTotals, *, details: bool) -> dict[str, Any]:
        row: dict[str, Any] = {
            "size_kwh": sim.size,
            "saving": round(t.saving, 2),
        }
        if grid:
            row["saving_grid_at_best"] = round(t.saving_grid, 2)
        if not details:
            return row
        yearly = per_year(t.saving, days)
        row |= {
            "power_kw": sim.power,
            "saving_per_year": None if yearly is None else round(yearly, 2),
            "full_cycles": round(t.discharged / sim.size, 1),
            "full_cycles_per_year": None
            if (cycles := per_year(t.discharged / sim.size, days)) is None
            else round(cycles),
            "pays_off_up_to": None
            if yearly is None or yearly <= 0
            else {f"{years}_years": round(yearly * years) for years in LIFETIMES},
            "hours_left_out": t.hours_left_out,
        }
        if grid:
            row["grid_charged_kwh"] = round(t.grid_charged, 1)
        return row

    tariffs = []
    for tariff in runtime.tariffs.values():
        per_size = simulated.totals[tariff.key]
        entry: dict[str, Any] = {
            "tariff": tariff.title,
            "sizes": [
                size_row(sim, per_size[sim.size], details=True) for sim in batteries
            ],
        }
        if has_battery:
            entry["your_battery_saving"] = round(
                real.totals[tariff.key].saving_battery, 2
            )
        tariffs.append(entry)
    months = [
        {
            "month": month,
            "tariffs": [
                {
                    "tariff": tariff.title,
                    "sizes": [
                        size_row(sim, per_tariff[tariff.key][sim.size], details=False)
                        for sim in batteries
                    ],
                }
                for tariff in runtime.tariffs.values()
                if tariff.key in per_tariff
            ],
        }
        for month, per_tariff in simulated.months.items()
    ]
    first = batteries[0]
    assumptions: dict[str, Any] = {
        "efficiency_percent": round(first.efficiency * 100, 1),
        "grid_charging": grid,
    }
    if grid:
        assumptions["grid_power_kw"] = first.grid_power
    return {
        "days": days,
        "rough": days < YEAR_DAYS,
        "assumptions": assumptions,
        "tariffs": tariffs,
        "months": months,
    }


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
            placeholders: dict[str, str] = {}
            if err.key == "prices_missing":
                placeholders = {
                    "tariffs": ", ".join(err.skipped),
                    "details": "; ".join(
                        f"{detail['tariff']}: {missing['tariff']} at {missing['from']}"
                        for detail in err.skipped_details
                        for missing in detail.get("missing_prices", [])
                    )
                    or "No first missing quarter hour could be identified.",
                }
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=f"import_{err.key}",
                translation_placeholders=placeholders,
            ) from err
        except SmardError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="smard_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return result if call.return_response else None

    async def backfill_price(call: ServiceCall) -> ServiceResponse:
        entry: TarifwachtConfigEntry = service.async_get_config_entry(
            hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY]
        )
        runtime: MeterRuntime = entry.runtime_data
        source = call.data[ATTR_PRICE_ENTITY]
        start, end = _as_utc(call.data[ATTR_START]), _as_utc(call.data[ATTR_END])
        price = call.data[ATTR_PRICE]
        started = runtime.engine.started
        now = dt_util.utcnow()
        if (
            started is None
            or source not in runtime.price_entities
            or start >= end
            or end - start > BACKFILL_MAX_SPAN
            or start < started
            or end > now
            or start.minute % 15
            or start.second
            or start.microsecond
            or end.minute % 15
            or end.second
            or end.microsecond
            or not math.isfinite(price)
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="backfill_price_invalid"
            )
        slots, already = await runtime.async_backfill_prices(source, start, end, price)
        if not slots:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="backfill_price_no_gaps"
            )
        return {
            "price_entity": source,
            "start": dt_util.as_local(start).isoformat(),
            "end": dt_util.as_local(end).isoformat(),
            "price_eur_per_kwh": price,
            "slots_filled": slots,
            "already_priced_slots": already,
            "statistics_recalculation_required": True,
        }

    async def simulate_battery(call: ServiceCall) -> ServiceResponse:
        entry: TarifwachtConfigEntry = service.async_get_config_entry(
            hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY]
        )
        runtime = entry.runtime_data
        now = dt_util.utcnow()
        end = _as_utc(call.data[ATTR_END]) if ATTR_END in call.data else now
        start = (
            _as_utc(call.data[ATTR_START])
            if ATTR_START in call.data
            else end - timedelta(days=SIMULATION_DAYS)
        )
        if start >= end:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="start_after_end"
            )
        efficiency = call.data.get(ATTR_EFFICIENCY)
        batteries = [
            SimSettings(
                size=size,
                power=call.data.get(ATTR_POWER, size * DEFAULT_C_RATE),
                efficiency=DEFAULT_EFFICIENCY
                if efficiency is None
                else efficiency / 100,
                grid_charging=call.data[ATTR_GRID_CHARGING],
                grid_power=call.data.get(ATTR_GRID_POWER),
            )
            for size in call.data.get(ATTR_SIZES, DEFAULT_SIZES)
        ]
        try:
            lookback = await runtime.async_lookback(start)
            outcome = await runtime.async_battery_simulation(
                start, end, lookback, batteries
            )
        except SmardError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="smard_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if outcome is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="simulation_no_solar"
            )
        simulated, real, used_smard, implausible = outcome
        if simulated.hours == 0:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="simulation_no_hours"
            )
        response: dict[str, Any] = {
            "start": dt_util.as_local(start).isoformat(),
            "end": dt_util.as_local(end).isoformat(),
            **_simulation_response(runtime, simulated, real, batteries),
        }
        if used_smard or (lookback is not None and lookback.uses_smard):
            response["exchange_prices"] = ATTRIBUTION
        if summary := implausible_summary(implausible):
            response["hours_implausible"] = summary
        return response

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPARE,
        compare,
        schema=COMPARE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BACKFILL_PRICE,
        backfill_price,
        schema=BACKFILL_PRICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SIMULATE_BATTERY,
        simulate_battery,
        schema=SIMULATE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_STATISTICS,
        import_statistics,
        schema=IMPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
