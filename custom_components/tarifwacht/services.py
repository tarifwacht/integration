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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.selector import ConfigEntrySelector
from homeassistant.util import dt as dt_util

from .const import DOMAIN

if TYPE_CHECKING:
    from . import TarifwachtConfigEntry

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
        result = engine.costs_between(start, end, now)
        current = runtime.current
        current_cost = result.totals[current.key].cost if current is not None else None
        tariffs: list[dict[str, Any]] = []
        for tariff in runtime.tariffs.values():
            totals = result.totals[tariff.key]
            average = totals.average_price
            tariffs.append(
                {
                    "tariff": tariff.title,
                    "current": tariff.current,
                    "cost": round(totals.cost, 4),
                    "consumption_cost": round(totals.consumption_cost, 4),
                    "base_cost": round(totals.base_cost, 4),
                    "average_price_ct": None
                    if average is None
                    else round(average * 100, 3),
                    "difference_to_current": None
                    if current_cost is None
                    else round(totals.cost - current_cost, 4),
                    "energy_without_price_kwh": round(totals.energy_without_price, 4),
                }
            )
        tariffs.sort(key=lambda t: t["cost"])
        return {
            "start": dt_util.as_local(result.start).isoformat(),
            "end": dt_util.as_local(result.end).isoformat(),
            "energy_kwh": round(result.energy, 4),
            "quarter_hours": result.quarter_hours,
            "cheapest": tariffs[0]["tariff"] if tariffs else None,
            "tariffs": tariffs,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPARE,
        compare,
        schema=COMPARE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
