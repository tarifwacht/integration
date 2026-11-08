#!/usr/bin/env python3
"""Build the data of the demo (docs/demo/): made-up prices, real logic.

Usage (from the repo root):
    uv run tools/make_demo.py

Everything here is invented: the exchange prices, two households and three
tariffs (no real supplier, grid operator or price sheet), the house's PV
system and battery. The integration's own code books them (`Engine`,
`tariff_from_data`, `costs_between`, `solar_totals`), quarter hour by quarter
hour, for a year from 1 November 2025, as in Home Assistant.

The page shows two moments (a winter and a summer evening) and the year in
review; for each moment the files hold what the dashboard, the devices and
the blueprint "Monatsübersicht" would show then, and what the long-term
statistics would answer the card (frontend/tarifwacht-card.js) then.
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.tarifwacht.const import BERLIN  # noqa: E402
from custom_components.tarifwacht.engine import Engine, PeriodCosts  # noqa: E402
from custom_components.tarifwacht.meter import MeterTracker  # noqa: E402
from custom_components.tarifwacht.payback import (  # noqa: E402
    Purchase,
    payback,
    payback_attributes,
)
from custom_components.tarifwacht.solar import (  # noqa: E402
    HourFlows,
    SolarResult,
    SolarSettings,
    SolarTotals,
    detect_same_inverter,
    solar_totals,
)
from custom_components.tarifwacht.tariff_config import tariff_from_data  # noqa: E402
from custom_components.tarifwacht.timeslots import QUARTER, slot_start  # noqa: E402

OUT = ROOT / "docs" / "demo" / "data"
MARKET = "sensor.boersenpreis"

SETUP = datetime(2025, 11, 1, tzinfo=BERLIN)
END = datetime(2026, 11, 1, tzinfo=BERLIN)
MOMENTS = {
    "winter": datetime(2026, 1, 28, 18, 0, tzinfo=BERLIN),  # a Wednesday
    "summer": datetime(2026, 6, 24, 18, 0, tzinfo=BERLIN),  # a Wednesday
}

# The tariffs as the config flow stores them (ct/kWh, EUR per month, %).
FIXED = {
    "kind": "fixed",
    "price": 28.4,
    "base_price": 12.0,
    "base_period": "month",
    "current": True,
}
DYNAMIC = {
    "kind": "dynamic_market",
    "price_entity": MARKET,
    "grid_fee": 9.0,
    "levies": 3.4,
    "margin": 1.6,
    "vat": 19.0,
    "base_price": 14.9,
    "base_period": "month",
}
MODUL3 = DYNAMIC | {
    "modul3": {
        "active": True,
        "ht": 13.0,
        "nt": 2.5,
        "quarters": [1, 2, 3, 4],
        "ht_windows": "17:00-20:00",
        "nt_windows": "00:00-06:00",
    }
}

# key: (title, entity id slug, data)
TARIFFS = {
    "fixed": ("Festpreis", "festpreis", FIXED),
    "dynamic": ("Dynamisch", "dynamisch", DYNAMIC),
    "modul3": ("Dynamisch + Modul 3", "dynamisch_modul_3", MODUL3),
}
# Modul 3 needs a controllable device (heat pump, wallbox): only in the house.
HOUSEHOLDS = {
    "wohnung": ("Wohnung", ("fixed", "dynamic")),
    "haus": (
        "Haus mit PV, Speicher, E-Auto und Wärmepumpe",
        ("fixed", "dynamic", "modul3"),
    ),
}

# The house's PV system and battery behind a hybrid inverter (made up).
PV_KWP = 9.0
BATTERY_KWH = 10.0
BATTERY_KW = 5.0
BATTERY_RESERVE = 0.05  # share kept for emergency power
BATTERY_LOSS = 0.97  # into and out of the cells, each way
INVERTER = 0.95  # DC to AC
# As the subentry "PV und Speicher" stores it (ct/kWh); § 51 EEG applies.
SOLAR = {"same_inverter": True, "feed_in_rate": 7.9, "negative_unpaid": True}
# Made-up purchase (section "Anschaffung"): both running since the setup.
PURCHASES = {
    "pv": Purchase(12_600.0, SETUP.date()),
    "battery": Purchase(4_500.0, SETUP.date()),
}
SOLAR_SETTINGS = SolarSettings(
    same_inverter=True, feed_in_rate=SOLAR["feed_in_rate"] / 100, negative_unpaid=True
)
HOUR = timedelta(hours=1)

MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]  # fmt: skip


# ---- Made-up prices and consumption ---------------------------------------------


def _bump(hour: float, centre: float, width: float) -> float:
    return math.exp(-((hour - centre) ** 2) / width)


def _winter(day: date) -> float:
    """1 in mid January, -1 in mid July."""
    return math.cos(2 * math.pi * (day.timetuple().tm_yday - 15) / 365)


def market_prices(
    rng: random.Random, sunny_days: dict[date, bool] | None = None
) -> dict[datetime, float]:
    """Exchange price per quarter hour (EUR/kWh, net): plausible, invented.

    Night trough, morning and evening peak, a midday dip from solar power that
    goes below zero on sunny summer weekends; a windy or calm day moves it all.
    `sunny_days` gets the sunny days (for the PV system of the house).
    """
    prices: dict[datetime, float] = {}
    slot = SETUP.astimezone(UTC)
    weather = 0.0
    day = None
    while slot < END.astimezone(UTC):
        local = slot.astimezone(BERLIN)
        if local.date() != day:
            day = local.date()
            weather = 0.6 * weather + rng.gauss(0, 0.018)  # wind comes and goes
            sunny = rng.random() < 0.35 + 0.35 * (1 - _winter(day)) / 2
            if sunny_days is not None:
                sunny_days[day] = sunny
        w = _winter(local.date())
        summer = (1 - w) / 2
        weekend = local.weekday() >= 5
        hour = local.hour + local.minute / 60
        solar = max(0.0, math.sin(math.pi * (hour - 6) / 14)) if 6 < hour < 20 else 0.0
        price = (
            0.088
            + 0.028 * w
            - (0.012 if weekend else 0.0)
            - 0.018 * _bump(hour, 3.5, 4.0)
            + (0.4 if weekend else 1.0) * 0.032 * _bump(hour, 7.8, 1.2)
            + (0.055 + 0.02 * summer) * _bump(hour, 19.0, 2.5)
            - solar
            * (0.02 + 0.04 * summer * (1.5 if sunny else 0.6))
            * (1.35 if weekend else 1.0)
            + weather
            + rng.gauss(0, 0.004)
        )
        prices[slot] = round(price, 5)
        slot += QUARTER
    return prices


def outdoor(local: datetime, offsets: dict[date, float]) -> float:
    """Made-up outdoor temperature (°C): season, day and night."""
    hour = local.hour + local.minute / 60
    base = 9.5 - 9.5 * _winter(local.date()) + offsets[local.date()]
    return base + 3.5 * math.sin(math.pi * (hour - 9) / 12)


def consumption(household: str, rng: random.Random) -> dict[datetime, float]:
    """kWh per quarter hour of an invented household."""
    energy: dict[datetime, float] = {}
    offsets: dict[date, float] = {}
    slot = SETUP.astimezone(UTC)
    while slot < END.astimezone(UTC):
        local = slot.astimezone(BERLIN)
        day = local.date()
        if day not in offsets:
            offsets[day] = 0.7 * offsets.get(day - timedelta(days=1), 0.0) + rng.gauss(
                0, 1.6
            )
        hour = local.hour + local.minute / 60
        weekend = local.weekday() >= 5
        w = _winter(day)
        kw = (
            0.17
            + 0.35 * _bump(hour, 9.0 if weekend else 7.2, 0.9)
            + (0.45 if weekend else 0.22) * _bump(hour, 12.5, 1.5)
            + 0.85 * _bump(hour, 19.5, 2.0)
        ) * (1 + 0.15 * w)
        if household == "haus":
            kw *= 1.1
            heat = max(0.0, 15.0 - outdoor(local, offsets)) * 0.085
            kw += heat + 1.6 * _bump(hour, 13.5, 0.25)  # heating, hot water
            if car_charging(local):
                kw += 11.0
        energy[slot] = kw * 0.25 * (0.8 + 0.4 * rng.random())
        slot += QUARTER
    return energy


def car_charging(local: datetime) -> bool:
    """The car: 22 kWh at 11 kW in the cheap hours, two nights a week."""
    return local.weekday() in (0, 3) and 1 <= local.hour < 3


def pv_output(
    sunny_days: dict[date, bool], rng: random.Random
) -> dict[datetime, float]:
    """DC energy (kWh) per quarter hour of an invented PV system: a roof
    facing south at 30° in central Germany (51° N, 10° E), the sun's course
    over day and year, sunny or cloudy days."""
    lat, tilt = math.radians(51.0), math.radians(30.0)
    energy: dict[datetime, float] = {}
    clouds: dict[date, float] = {}
    slot = SETUP.astimezone(UTC)
    while slot < END.astimezone(UTC):
        day = slot.astimezone(BERLIN).date()
        if day not in clouds:
            clouds[day] = (
                rng.uniform(0.85, 1.0) if sunny_days[day] else rng.uniform(0.12, 0.55)
            )
        declination = math.radians(23.44) * -math.cos(
            2 * math.pi * (day.timetuple().tm_yday + 10) / 365
        )
        solar_time = slot.hour + slot.minute / 60 + 0.125 + 10 / 15  # mid slot
        hour_angle = math.radians(15 * (solar_time - 12))
        # sin of the sun's elevation
        sun = math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(
            declination
        ) * math.cos(hour_angle)
        kw = 0.0
        if sun > 0:
            # Direct light on the tilted roof (thinner through a low sun's
            # long way through the air) plus some diffuse light.
            incidence = math.sin(lat - tilt) * math.sin(declination) + math.cos(
                lat - tilt
            ) * math.cos(declination) * math.cos(hour_angle)
            direct = max(0.0, incidence) * sun**0.3
            kw = PV_KWP * 0.76 * (direct + 0.1 * sun)
            kw *= clouds[day]
            if not sunny_days[day]:
                kw *= 0.6 + 0.8 * rng.random()
        energy[slot] = min(kw, PV_KWP * 0.85) * 0.25
        slot += QUARTER
    return energy


@dataclass
class QuarterFlows:
    """What the meters of the house count in a quarter hour (kWh)."""

    purchase: float
    feed_in: float
    inverter: float  # AC output of the hybrid inverter, battery included
    charged: float
    discharged: float


def run_battery(load: dict[datetime, float], pv: dict[datetime, float]) -> dict[datetime, QuarterFlows]:  # fmt: skip
    """Self-consumption first, as most home batteries do: charge with the PV
    surplus, discharge to cover the house, never into the car; behind a
    hybrid inverter (battery on the DC side, inverter efficiency on the AC
    side)."""
    flows: dict[datetime, QuarterFlows] = {}
    soc = BATTERY_KWH / 2
    limit = BATTERY_KW / 4
    for slot in sorted(load):
        used, dc = load[slot], pv[slot]
        charged = discharged = 0.0
        if dc * INVERTER >= used:
            room = (BATTERY_KWH - soc) / BATTERY_LOSS
            charged = max(0.0, min(dc - used / INVERTER, limit, room))
        elif not car_charging(slot.astimezone(BERLIN)):
            stored = (soc - BATTERY_RESERVE * BATTERY_KWH) * BATTERY_LOSS
            discharged = max(0.0, min((used - dc * INVERTER) / INVERTER, limit, stored))
        soc += charged * BATTERY_LOSS - discharged / BATTERY_LOSS
        inverter = (dc - charged + discharged) * INVERTER
        flows[slot] = QuarterFlows(
            purchase=max(0.0, used - inverter),
            feed_in=max(0.0, inverter - used),
            inverter=inverter,
            charged=charged,
            discharged=discharged,
        )
    return flows


def hourly(flows: dict[datetime, QuarterFlows]) -> dict[datetime, HourFlows]:
    """The quarter hours summed per UTC hour, as the long-term statistics."""
    sums: dict[datetime, list[float]] = {}
    for slot, f in flows.items():
        row = sums.setdefault(slot.replace(minute=0), [0.0] * 5)
        for i, value in enumerate((f.purchase, f.feed_in, f.inverter, f.charged, f.discharged)):  # fmt: skip
            row[i] += value
    return {hour: HourFlows(*row) for hour, row in sums.items()}


# ---- Booking with the integration's engine -------------------------------------------


def build_engine(keys: tuple[str, ...], prices: dict[datetime, float]) -> Engine:
    engine = Engine(meter=MeterTracker(max_power_kw=30), tariffs={}, tz=BERLIN)
    engine.tariffs = {
        key: tariff_from_data(TARIFFS[key][2], engine.price_table) for key in keys
    }
    engine.price_table(MARKET).merge(prices)
    return engine


def _rows(costs: PeriodCosts, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Like services._tariff_rows (details): cheapest first."""
    current = costs.totals["fixed"]
    rows = []
    for key in keys:
        totals = costs.totals[key]
        average = totals.average_price
        rows.append(
            {
                "tariff": TARIFFS[key][0],
                "current": key == "fixed",
                "consumption_cost": round(totals.consumption_cost, 4),
                "base_cost": round(totals.base_cost, 4),
                "bonus": round(totals.bonus, 4),
                "average_price_ct": None
                if average is None
                else round(average * 100, 3),
                "cost": round(totals.cost, 4),
                "difference_to_current": round(totals.cost - current.cost, 4),
                "energy_without_price_kwh": round(totals.energy_without_price, 4),
            }
        )
    rows.sort(key=lambda r: r["cost"])
    return rows


def solar_between(engine: Engine, hours: dict[datetime, HourFlows], start: datetime, end: datetime, *, daily: bool = False) -> SolarResult:  # fmt: skip
    """The complete hours in [start, end) booked by the integration's code."""
    utc_start, utc_end = start.astimezone(UTC), end.astimezone(UTC)
    flows = {h: f for h, f in hours.items() if utc_start <= h and h + HOUR <= utc_end}
    return solar_totals(
        flows,
        engine.tariffs,
        SOLAR_SETTINGS,
        BERLIN,
        engine.price_table(MARKET),
        daily=daily,
    )


def paybacks(result: SolarResult, keys: tuple[str, ...], now: datetime) -> dict[str, dict[str, Any]]:  # fmt: skip
    """Attributes of the payback per tariff and part, as
    runtime._update_payback and sensor._payback (no time before the setup)."""
    today = now.astimezone(BERLIN).date()
    return {
        key: {
            part: payback_attributes(
                payback(
                    purchase,
                    {d: v[index] for d, v in result.days[key].items()},
                    today,
                )
            )
            for index, (part, purchase) in enumerate(PURCHASES.items())
        }
        for key in keys
    }


def _solar_rows(totals: dict[str, SolarTotals], keys: tuple[str, ...], *, details: bool) -> list[dict[str, Any]]:  # fmt: skip
    """Like services._solar_rows."""
    rows: list[dict[str, Any]] = []
    for key in keys:
        t = totals[key]
        row: dict[str, Any] = {
            "tariff": TARIFFS[key][0],
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


def solar_response(result: SolarResult, keys: tuple[str, ...], payback_now: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:  # fmt: skip
    """Like services._solar_response: "pv_battery" in the compare response."""
    t = result.totals[keys[0]]
    response = {
        "tariffs": _solar_rows(result.totals, keys, details=True),
        "consumption_kwh": round(t.consumption, 3),
        "pv_kwh": round(t.pv, 3),
        "purchase_kwh": round(t.purchase, 3),
        "feed_in_kwh": round(t.feed_in, 3),
        "feed_in_unpaid_kwh": round(t.feed_in_unpaid, 3),
        "charged_kwh": round(t.charged, 3),
        "discharged_kwh": round(t.discharged, 3),
        "months": [
            {"month": month, "tariffs": _solar_rows(totals, keys, details=False)}
            for month, totals in result.months.items()
        ],
    }
    if payback_now:
        response["payback"] = [
            {"tariff": TARIFFS[key][0], **payback_now[key]} for key in keys
        ]
    return response


def solar_sensors(result: SolarResult, keys: tuple[str, ...], payback_now: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:  # fmt: skip
    """State and attributes of "Ersparnis PV" and "Ersparnis Speicher" per
    tariff (sensor._saving_pv_attributes, _saving_battery_attributes)."""
    sensors: dict[str, Any] = {}
    for key in keys:
        extra = (payback_now or {}).get(key, {})
        t = result.totals[key]
        value = t.battery_value
        sensors[key] = {
            "saving_pv": round(t.saving_pv, 2),
            "saving_battery": round(t.saving_battery, 2),
            "pv": {
                "cost_without_pv_and_battery": round(t.without, 2),
                "cost_pv_without_battery": round(t.pv_only, 2),
                "cost_actual": round(t.actual, 2),
                "consumption_kwh": round(t.consumption, 1),
                "pv_kwh": round(t.pv, 1),
                "purchase_kwh": round(t.purchase, 1),
                "feed_in_kwh": round(t.feed_in, 1),
                "feed_in_unpaid_kwh": round(t.feed_in_unpaid, 1),
                "hours": t.hours,
                "hours_left_out": t.hours_left_out,
                **extra.get("pv", {}),
            },
            "battery": {
                "charged_kwh": round(t.charged, 1),
                "discharged_kwh": round(t.discharged, 1),
                "value_per_kwh_ct": None if value is None else round(value * 100, 1),
                "hours": t.hours,
                "hours_left_out": t.hours_left_out,
                **extra.get("battery", {}),
            },
        }
    return sensors


def compare(engine: Engine, keys: tuple[str, ...], start: datetime, end: datetime, now: datetime, solar: dict[datetime, HourFlows] | None = None) -> dict[str, Any]:  # fmt: skip
    """The response of the action tarifwacht.compare (services.compare)."""
    costs = engine.costs_between(
        start.astimezone(UTC), end.astimezone(UTC), now.astimezone(UTC)
    )
    rows = _rows(costs, keys)
    months = []
    for month, part in costs.months.items():
        month_rows = [
            {k: r[k] for k in ("tariff", "cost", "difference_to_current", "energy_without_price_kwh")}
            for r in _rows(part, keys)
        ]  # fmt: skip
        months.append(
            {
                "month": month,
                "energy_kwh": round(part.energy, 4),
                "cheapest": month_rows[0]["tariff"],
                "tariffs": month_rows,
            }
        )
    response = {
        "start": costs.start.astimezone(BERLIN).isoformat(),
        "end": costs.end.astimezone(BERLIN).isoformat(),
        "energy_kwh": round(costs.energy, 4),
        "quarter_hours": costs.quarter_hours,
        "cheapest": rows[0]["tariff"],
        "tariffs": rows,
        "months": months,
    }
    if solar is not None:
        since_setup = solar_between(engine, solar, SETUP, now, daily=True)
        response["pv_battery"] = solar_response(
            solar_between(engine, solar, start, end),
            keys,
            paybacks(since_setup, keys, now),
        )
    return response


def _de(value: float, digits: int, sign: bool = False) -> str:
    text = f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"
    return text.replace(".", ",")


def month_notification(result: dict[str, Any], month_start: datetime) -> dict[str, str]:
    """Title and message of the blueprint "Monatsübersicht" (its template)."""
    lines = [f"Strombezug: {_de(result['energy_kwh'], 1)} kWh"]
    for row in result["tariffs"]:
        text = f"{row['tariff']}: {_de(row['cost'], 2)} €"
        if row["energy_without_price_kwh"] > 0:
            text += " (Preise fehlen)"
        elif row["difference_to_current"]:
            text += f" ({_de(row['difference_to_current'], 2, sign=True)} € gegenüber dem aktuellen Tarif)"
        lines.append(text)
    if result["cheapest"]:
        lines.append(f"Günstigster Tarif: {result['cheapest']}")
    return {
        "title": f"Strom im {MONTHS_DE[month_start.month - 1]} {month_start.year}",
        "message": "\n".join(lines),
    }


def _next_month(start: datetime) -> datetime:
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def card_statistics(engine: Engine, keys: tuple[str, ...], now: datetime, solar: dict[datetime, HourFlows] | None) -> dict[str, Any]:  # fmt: skip
    """What the long-term statistics answer the card at this moment: the
    change of the cumulative sensors in the calendar day, month and year
    ("recorder/statistic_during_period") and per month since the setup
    ("recorder/statistics_during_period"). The difference is the tariff's
    cost minus the current tariff's (as statistics_import.py writes it); the
    savings come from complete hours, as the sensors recompute them."""
    utc_now = now.astimezone(UTC)
    day = now.replace(hour=0, minute=0)

    def values(start: datetime, end: datetime) -> dict[str, dict[str, float]]:
        part = engine.costs_between(start.astimezone(UTC), end.astimezone(UTC), utc_now)
        cost = {k: part.totals[k].cost for k in keys}
        result = {
            "cost": {k: round(v, 4) for k, v in cost.items()},
            "difference": {k: round(cost[k] - cost["fixed"], 4) for k in keys if k != "fixed"},
        }  # fmt: skip
        if solar is not None:
            totals = solar_between(engine, solar, start, end).totals
            result["saving_pv"] = {k: round(totals[k].saving_pv, 4) for k in keys}
            result["saving_battery"] = {k: round(totals[k].saving_battery, 4) for k in keys}  # fmt: skip
        return result

    starts = {
        "day": day,
        "month": day.replace(day=1),
        "year": max(day.replace(month=1, day=1), SETUP),
    }
    months = []
    start = SETUP
    while start < now:
        end = min(_next_month(start), now)
        months.append({"month": start.strftime("%Y-%m")} | values(start, end))
        start = _next_month(start)
    return {
        "periods": {period: values(start, now) for period, start in starts.items()},
        "months": months,
    }


def snapshot(engine: Engine, keys: tuple[str, ...], now: datetime, energy: dict[datetime, float], solar: dict[datetime, HourFlows] | None) -> dict[str, Any]:  # fmt: skip
    """What Home Assistant shows at this moment."""
    utc_now = now.astimezone(UTC)
    day = now.replace(hour=0, minute=0)
    month = day.replace(day=1)

    def costs(start: datetime, end: datetime) -> dict[str, float]:
        part = engine.costs_between(start.astimezone(UTC), end.astimezone(UTC), utc_now)
        return {k: round(part.totals[k].cost, 4) for k in keys}

    current = engine.compared_cost("fixed")
    ranking = sorted(((k, engine.compared_cost(k)) for k in keys), key=lambda kv: kv[1])
    tariffs = {}
    for key in keys:
        totals = engine.totals[key]
        tariffs[key] = {
            "title": TARIFFS[key][0],
            "slug": TARIFFS[key][1],
            "consumption_cost": round(totals.consumption_cost, 2),
            "cost": round(totals.cost, 2),
            "average_ct": round(totals.average_price * 100, 2),
            # Sensor "Energy price now": the price of this quarter hour.
            "price_now_ct": round(engine.tariffs[key].price(slot_start(utc_now)) * 100, 2),
            "difference": None if key == "fixed" else round(engine.compared_cost(key) - current, 2),
        }  # fmt: skip
    days = []
    for back in range(29, -1, -1):
        start = day - timedelta(days=back)
        end = min(start + timedelta(days=1), now)
        days.append({"date": start.date().isoformat(), "costs": costs(start, end)})
    # Today, quarter hour by quarter hour: the price of each tariff, the
    # consumption up to now.
    today = []
    slot = day.astimezone(UTC)
    while slot < (day + timedelta(days=1)).astimezone(UTC):
        row: dict[str, Any] = {"t": slot.isoformat()}
        row["kwh"] = round(energy[slot], 4) if slot < utc_now else None
        row["ct"] = {
            k: round(engine.tariffs[k].at(slot).prices.get(slot) * 100, 3) for k in keys
        }
        today.append(row)
        slot += QUARTER
    last_month = (month - timedelta(days=1)).replace(day=1)
    notification = month_notification(
        compare(engine, keys, last_month, month, now), last_month
    )
    extra: dict[str, Any] = {}
    if solar is not None:
        # The sensors since the setup; today and this month as the
        # statistic cards would show their change.
        since_setup = solar_between(engine, solar, SETUP, now, daily=True)
        extra["solar"] = {
            "sensors": solar_sensors(
                since_setup, keys, paybacks(since_setup, keys, now)
            ),
            "month": solar_sensors(solar_between(engine, solar, month, now), keys),
        }
    return extra | {
        "now": now.isoformat(),
        "energy_kwh": round(engine.energy, 2),
        "cheapest": TARIFFS[ranking[0][0]][0],
        "ranking": [{"tariff": TARIFFS[k][0], "cost": round(c, 2)} for k, c in ranking],
        "tariffs": tariffs,
        "today": costs(day, now),
        "month": costs(month, now),
        "days": days,
        "curve": today,
        "notification": notification | {"at": month.replace(hour=8).isoformat()},
        "card": card_statistics(engine, keys, now, solar),
    }  # fmt: skip


def main() -> None:
    rng = random.Random(4006)  # RAL 4006, the brand colour
    sunny_days: dict[date, bool] = {}
    prices = market_prices(rng, sunny_days)
    OUT.mkdir(parents=True, exist_ok=True)
    for household, (name, keys) in HOUSEHOLDS.items():
        energy = consumption(household, random.Random(household))
        solar: dict[datetime, HourFlows] | None = None
        if household == "haus":
            # The meter of the integration counts what is bought from the grid.
            flows = run_battery(energy, pv_output(sunny_days, random.Random("pv")))
            energy = {slot: f.purchase for slot, f in flows.items()}
            solar = hourly(flows)
            print(
                f"  PV {sum(f.inverter for f in flows.values()):.0f} kWh AC, "
                f"Einspeisung {sum(f.feed_in for f in flows.values()):.0f} kWh, "
                f"Speicher {sum(f.discharged for f in flows.values()):.0f} kWh entladen, "
                f"Kopplung erkannt: {detect_same_inverter(solar)}"
            )
        engine = build_engine(keys, prices)
        engine.start(SETUP.astimezone(UTC))
        reading = 10_000.0
        engine.on_meter(reading, SETUP.astimezone(UTC), SETUP.astimezone(UTC))
        moments: dict[str, Any] = {}
        pending = sorted(MOMENTS.items(), key=lambda kv: kv[1])
        for slot in sorted(energy):
            end = slot + QUARTER
            reading += energy[slot]
            engine.on_meter(reading, end, end)
            engine.tick(end)
            while pending and end >= pending[0][1].astimezone(UTC):
                key, now = pending.pop(0)
                moments[key] = snapshot(engine, keys, now, energy, solar)
        result = {
            "name": name,
            "device": household.capitalize(),
            "setup": SETUP.isoformat(),
            **(
                {}
                if solar is None
                else {
                    "pv_system": SOLAR
                    | {
                        "kwp": PV_KWP,
                        "battery_kwh": BATTERY_KWH,
                        "battery_kw": BATTERY_KW,
                    }
                }
            ),
            "tariffs": [
                {
                    "key": k,
                    "title": TARIFFS[k][0],
                    "slug": TARIFFS[k][1],
                    **TARIFFS[k][2],
                }
                for k in keys
            ],
            "moments": moments,
            "year": compare(engine, keys, SETUP, END, END, solar),
        }
        path = OUT / f"{household}.json"
        with path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(result, file, ensure_ascii=False, separators=(",", ":"))
        year = result["year"]
        print(
            f"{household}: {year['energy_kwh']:.0f} kWh/Jahr, "
            + ", ".join(f"{r['tariff']} {r['cost']:.2f} €" for r in year["tariffs"])
            + f", {path.stat().st_size // 1024} KB"
        )
        if "pv_battery" in year:
            print(
                "  Ersparnis "
                + ", ".join(
                    f"{r['tariff']} PV {r['saving_pv']:.0f} € + Speicher {r['saving_battery']:.0f} € "
                    f"({r['battery_value_per_kwh_ct']} ct/kWh)"
                    for r in year["pv_battery"]["tariffs"]
                )
            )
        for key, view in moments.items():
            print(
                f"  {key}: heute {view['today']}, Monat {view['month']}, günstigster {view['cheapest']}"
            )
    low = min(prices.values()) * 100
    high = max(prices.values()) * 100
    print(f"Börsenpreis {low:.1f} … {high:.1f} ct/kWh netto")


if __name__ == "__main__":
    main()
