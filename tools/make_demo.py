#!/usr/bin/env python3
"""Build the data of the demo (docs/demo/): made-up prices, real logic.

Usage (from the repo root):
    uv run tools/make_demo.py

Everything here is invented: the exchange prices, two households and three
tariffs (no real supplier, grid operator or price sheet). The integration's
own code books them (`Engine`, `tariff_from_data`, `costs_between`), quarter
hour by quarter hour, for a year from 1 November 2025, as in Home Assistant.

The page shows two moments (a winter and a summer evening) and the year in
review; for each moment the files hold what the dashboard, the devices and
the blueprint "Monatsübersicht" would show then.
"""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.tarifwacht.const import BERLIN  # noqa: E402
from custom_components.tarifwacht.engine import Engine, PeriodCosts  # noqa: E402
from custom_components.tarifwacht.meter import MeterTracker  # noqa: E402
from custom_components.tarifwacht.tariff_config import tariff_from_data  # noqa: E402
from custom_components.tarifwacht.timeslots import QUARTER  # noqa: E402

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
    "haus": ("Haus mit E-Auto und Wärmepumpe", ("fixed", "dynamic", "modul3")),
}

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


def market_prices(rng: random.Random) -> dict[datetime, float]:
    """Exchange price per quarter hour (EUR/kWh, net): plausible, invented.

    Night trough, morning and evening peak, a midday dip from solar power that
    goes below zero on sunny summer weekends; a windy or calm day moves it all.
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
            * (0.02 + 0.055 * summer * (1.5 if sunny else 0.6))
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
            # The car: 22 kWh at 11 kW in the cheap hours, two nights a week.
            if local.weekday() in (0, 3) and 1 <= hour < 3:
                kw += 11.0
        energy[slot] = kw * 0.25 * (0.8 + 0.4 * rng.random())
        slot += QUARTER
    return energy


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


def compare(engine: Engine, keys: tuple[str, ...], start: datetime, end: datetime, now: datetime) -> dict[str, Any]:  # fmt: skip
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
    return {
        "start": costs.start.astimezone(BERLIN).isoformat(),
        "end": costs.end.astimezone(BERLIN).isoformat(),
        "energy_kwh": round(costs.energy, 4),
        "quarter_hours": costs.quarter_hours,
        "cheapest": rows[0]["tariff"],
        "tariffs": rows,
        "months": months,
    }


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


def snapshot(engine: Engine, keys: tuple[str, ...], now: datetime, prices: dict[datetime, float], energy: dict[datetime, float]) -> dict[str, Any]:  # fmt: skip
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
    return {
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
    }  # fmt: skip


def main() -> None:
    rng = random.Random(4006)  # RAL 4006, the brand colour
    prices = market_prices(rng)
    OUT.mkdir(parents=True, exist_ok=True)
    for household, (name, keys) in HOUSEHOLDS.items():
        energy = consumption(household, random.Random(household))
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
                moments[key] = snapshot(engine, keys, now, prices, energy)
        result = {
            "name": name,
            "device": household.capitalize(),
            "setup": SETUP.isoformat(),
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
            "year": compare(engine, keys, SETUP, END, END),
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
        for key, view in moments.items():
            print(
                f"  {key}: heute {view['today']}, Monat {view['month']}, günstigster {view['cheapest']}"
            )
    low = min(prices.values()) * 100
    high = max(prices.values()) * 100
    print(f"Börsenpreis {low:.1f} … {high:.1f} ct/kWh netto")


if __name__ == "__main__":
    main()
