"""Action tarifwacht.compare: costs of every tariff in a chosen period."""

from __future__ import annotations

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

if TYPE_CHECKING:
    from . import TarifwachtConfigEntry
    from .engine import PeriodCosts
    from .runtime import MeterRuntime

SERVICE_COMPARE = "compare"
ATTR_CONFIG_ENTRY = "config_entry"
ATTR_START = "start"
ATTR_END = "end"

COMPARE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
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
    """One row per tariff: complete ones (every kWh priced) by cost, then the rest."""
    current = runtime.current
    current_cost = costs.totals[current.key].cost if current is not None else None
    rows: list[dict[str, Any]] = []
    for tariff in runtime.tariffs.values():
        totals = costs.totals[tariff.key]
        row: dict[str, Any] = {"tariff": tariff.title}
        if details:
            average = totals.average_price
            row |= {
                "current": tariff.current,
                "consumption_cost": round(totals.consumption_cost, 4),
                "base_cost": round(totals.base_cost, 4),
                "average_price_ct": None
                if average is None
                else round(average * 100, 3),
            }
        row |= {
            "cost": round(totals.cost, 4),
            "difference_to_current": None
            if current_cost is None
            else round(totals.cost - current_cost, 4),
            "energy_without_price_kwh": round(totals.energy_without_price, 4),
        }
        rows.append(row)
    rows.sort(key=lambda r: (r["energy_without_price_kwh"] > 0, r["cost"]))
    return rows


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
                "exchange_prices": ATTRIBUTION,
            }
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
        return response

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPARE,
        compare,
        schema=COMPARE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
