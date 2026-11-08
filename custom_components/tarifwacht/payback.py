"""When PV and battery have paid for themselves (amortisation).

The purchase cost of the PV and of the battery against what each saved
under a tariff since its commissioning (the saving sensors of solar.py, per
local day). Remaining amount, the day the savings reached the cost, and a
forecast from the average saving per day: over the last full year of days
if there is one (summer and winter both in it), else over the days there
are - then the forecast is marked rough.

The days come from what is computed anyway: the hourly recomputation of the
savings since the setup and, before the setup, the long-term statistics of
the saving sensors (imported by the user), read once per start.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .const import (
    CONF_BATTERY_COST,
    CONF_BATTERY_SINCE,
    CONF_CHARGED_ENTITY,
    CONF_DISCHARGED_ENTITY,
    CONF_PV_COST,
    CONF_PV_SINCE,
)

PV = "pv"
BATTERY = "battery"

# Days averaged for the forecast: a full year evens out the seasons.
FORECAST_DAYS = 365
# Fewer complete days than this give no forecast at all.
MIN_FORECAST_DAYS = 7
# A forecast further out than this is none (a saving close to zero).
MAX_FORECAST_DAYS = 100 * 366


@dataclass(frozen=True)
class Purchase:
    """What a part cost (EUR) and when it began to save (local date)."""

    cost: float
    since: date


@dataclass(frozen=True)
class Payback:
    """The state of one part's payback under one tariff."""

    purchase: Purchase
    saved: float  # EUR since commissioning, as far as there are days
    paid_back_on: date | None
    forecast: date | None
    forecast_rough: bool
    per_day: float | None  # average saving per complete day (EUR)
    # First day with a saving counted: later than the commissioning when the
    # statistics begin later (then less is counted than was saved).
    counted_since: date | None

    @property
    def paid_back(self) -> bool:
        return self.paid_back_on is not None

    @property
    def remaining(self) -> float:
        return max(0.0, self.purchase.cost - self.saved)


def _day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def purchases(data: Mapping[str, Any]) -> dict[str, Purchase]:
    """The parts of the PV and battery subentry with a purchase cost and a
    commissioning date. The battery counts from the PV's date without its
    own, and only with both battery meters."""
    found: dict[str, Purchase] = {}
    pv_since = _day(data.get(CONF_PV_SINCE))
    if float(data.get(CONF_PV_COST) or 0) > 0 and pv_since is not None:
        found[PV] = Purchase(float(data[CONF_PV_COST]), pv_since)
    battery_since = _day(data.get(CONF_BATTERY_SINCE)) or pv_since
    if (
        float(data.get(CONF_BATTERY_COST) or 0) > 0
        and battery_since is not None
        and data.get(CONF_CHARGED_ENTITY)
        and data.get(CONF_DISCHARGED_ENTITY)
    ):
        found[BATTERY] = Purchase(float(data[CONF_BATTERY_COST]), battery_since)
    return found


def purchase_status(data: Mapping[str, Any] | None) -> str:
    """For the bug report and the diagnostics: which purchase costs are set,
    never the amounts or dates (they may be private)."""
    found = purchases(data or {})
    return (
        ", ".join(f"{part} cost set" for part in (PV, BATTERY) if part in found)
        or "none"
    )


def payback(purchase: Purchase, daily: Mapping[date, float], today: date) -> Payback:
    """The payback from the saving per local day (`daily`, EUR) up to today.

    Days before the commissioning do not count. Paid back on the first day
    the running sum reached the cost. The forecast averages the complete
    days of the last FORECAST_DAYS (from the first counted day if later; a
    day without a value counts as 0) and is rough with fewer than that.
    """
    days = sorted(d for d in daily if purchase.since <= d <= today)
    saved = 0.0
    paid_back_on: date | None = None
    for day in days:
        saved += daily[day]
        if paid_back_on is None and saved >= purchase.cost:
            paid_back_on = day
    counted_since = days[0] if days else None
    per_day: float | None = None
    forecast: date | None = None
    rough = True
    if counted_since is not None:
        first = max(today - timedelta(days=FORECAST_DAYS), counted_since)
        span = (today - first).days
        if span >= MIN_FORECAST_DAYS:
            per_day = sum(daily[d] for d in days if first <= d < today) / span
            rough = span < FORECAST_DAYS
    if paid_back_on is None and per_day is not None and per_day > 0:
        needed = math.ceil((purchase.cost - saved) / per_day)
        if needed <= MAX_FORECAST_DAYS:
            forecast = today + timedelta(days=needed)
    return Payback(
        purchase=purchase,
        saved=saved,
        paid_back_on=paid_back_on,
        forecast=forecast,
        forecast_rough=rough,
        per_day=per_day,
        counted_since=counted_since,
    )


def merge_days(*parts: Mapping[date, float]) -> dict[date, float]:
    """The savings per day of several sources added up (e.g. before the
    setup from the statistics, after it from the hourly recomputation)."""
    merged: dict[date, float] = {}
    for part in parts:
        for day, value in part.items():
            merged[day] = merged.get(day, 0.0) + value
    return merged


def payback_attributes(result: Payback | None) -> dict[str, Any]:
    """Attributes of a saving sensor (and the compare action): {} without a
    purchase cost."""
    if result is None:
        return {}

    def iso(day: date | None) -> str | None:
        return None if day is None else day.isoformat()

    return {
        "purchase_cost_eur": round(result.purchase.cost, 2),
        "commissioned_on": result.purchase.since.isoformat(),
        "saved_since_commissioning_eur": round(result.saved, 2),
        "remaining_eur": round(result.remaining, 2),
        "paid_back": result.paid_back,
        "paid_back_on": iso(result.paid_back_on),
        "paid_back_forecast": iso(result.forecast),
        "forecast_rough": result.forecast_rough,
        "saving_per_day_eur": None
        if result.per_day is None
        else round(result.per_day, 3),
        "counted_since": iso(result.counted_since),
    }
