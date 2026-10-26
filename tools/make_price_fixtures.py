"""Build price-sensor fixtures for Nord Pool (HACS) and ENTSO-E (HACS).

No captured attribute snapshots of these integrations exist. The fixtures are
therefore derived from REAL API data shipped in the projects' own test suites
(pinned commits, Apache-2.0), converted exactly as each integration's code
builds its sensor attributes (code references below). Run from the repo root:

    uv run python tools/make_price_fixtures.py

Writes tests/fixtures/nordpool_raw_2025-10-01.json and
tests/fixtures/entsoe_prices_2024-10-06.json.
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
LOCAL = ZoneInfo("Europe/Berlin")  # Home Assistant's time zone of a German user

# home-assistant/core 2026.10.4: Nord Pool Data Portal API response.
NORDPOOL_API = (
    "https://raw.githubusercontent.com/home-assistant/core/"
    "357cae5c598dfcd7a0ea7dc5b1facccd4ec6037b/"
    "tests/components/nordpool/fixtures/delivery_period_today.json"
)
# JaccoR/hass-entso-e v0.7.5: ENTSO-E transparency platform response (DE-LU).
ENTSOE_API = (
    "https://raw.githubusercontent.com/JaccoR/hass-entso-e/"
    "cbdf67ac0e73fd685a02e27ad7b6bef2c5af7ca6/"
    "custom_components/entsoe/test/datasets/DE_60M_15M_overlap.xml"
)


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def nordpool() -> dict:
    """custom-components/nordpool 0.0.18 (1eaa2490), sensor.py.

    raw_today: _add_raw (L401-421) -> {start, end, value}; start/end via
    dt_utils.as_local (_someday L329-347); value = _calc_price (L253-304):
    spot / _PRICE_IN["kWh"] (1000) * (1 + vat) + additional costs, rounded to
    `precision` (default 3). Here: VAT off, no additional costs. Times are
    datetime objects in Home Assistant; stored here as they serialize (ISO).
    """
    api = json.loads(fetch(NORDPOOL_API))
    area = "SE3"
    entries = []
    for item in api["multiAreaEntries"]:
        start = datetime.fromisoformat(item["deliveryStart"]).astimezone(LOCAL)
        end = datetime.fromisoformat(item["deliveryEnd"]).astimezone(LOCAL)
        value = round(item["entryPerArea"][area] / 1000 * (1 + 0.0) + 0.0, 3)
        entries.append(
            {"start": start.isoformat(), "end": end.isoformat(), "value": value}
        )
    entries.sort(key=lambda e: e["start"])
    return {
        "_source": NORDPOOL_API,
        "_note": "Attributes as built by custom-components/nordpool 0.0.18 from this API response; area SE3, VAT off, no additional costs, precision 3, Home Assistant time zone Europe/Berlin.",
        "state": entries[0]["value"],
        "attributes": {
            "unit": "kWh",
            "currency": "EUR",
            "region": area,
            "price_in_cents": False,
            "unit_of_measurement": "EUR/kWh",
            "raw_today": entries,
            "raw_tomorrow": [],
        },
    }


def entsoe_series(document: bytes) -> dict[datetime, float]:
    """api_client.py parse_price_document (L107-172) with the default period
    PT60M: periods of another resolution whose start is already known are
    skipped; missing positions repeat the previous price (process_points
    L174-193); other resolutions are averaged to the hour (L195-215)."""
    root = ET.fromstring(document)
    for element in root.iter():
        element.tag = element.tag.split("}")[-1]
    series: dict[datetime, float] = {}
    for timeseries in root.iter("TimeSeries"):
        out = timeseries.find(".//out_Domain.mRID")
        if out is not None and out.text == "10Y1001A1001A82H":
            sequence = timeseries.find(
                ".//classificationSequence_AttributeInstanceComponent.position"
            )
            if sequence is not None and sequence.text != "1":
                continue
        for period in timeseries.iter("Period"):
            resolution = period.findtext(".//resolution")
            if resolution in ("PT60M", "PT1H"):
                minutes = 60
            elif resolution == "PT15M":
                minutes = 15
            else:
                continue
            start = datetime.strptime(
                period.findtext(".//timeInterval/start"), "%Y-%m-%dT%H:%MZ"
            ).replace(tzinfo=UTC)
            start = start.replace(minute=0)
            if start in series:
                continue
            points = sorted(
                (int(p.findtext(".//position")), float(p.findtext(".//price.amount")))
                for p in period.iter("Point")
            )
            data: dict[datetime, float] = {}
            last = None
            for position in range(points[0][0], points[-1][0] + 1):
                if points and position == points[0][0]:
                    last = points.pop(0)[1]
                data[start + timedelta(minutes=(position - 1) * minutes)] = last
            if minutes != 60:
                buckets: dict[datetime, list[float]] = {}
                for moment, price in data.items():
                    hour = moment - timedelta(minutes=moment.minute % 60)
                    buckets.setdefault(hour, []).append(price)
                data = {h: round(sum(p) / len(p), 2) for h, p in buckets.items()}
            series.update(data)
    return series


def entsoe() -> dict:
    """hass-entso-e v0.7.5: coordinator.get_timestamped_prices (L251-256):
    {"time": str(datetime), "price": calc_price} with calc_price (L76-110) =
    round(template(spot / 1000) * (1 + vat), 5); defaults: template
    {{current_price}}, VAT 0. Times in local time (Europe/Berlin here)."""
    series = entsoe_series(fetch(ENTSOE_API))
    today = datetime(2024, 10, 6, tzinfo=LOCAL).date()

    def entry(moment: datetime, value: float) -> dict:
        return {"time": str(moment.astimezone(LOCAL)), "price": round(value / 1000, 5)}

    ordered = sorted(series.items())
    prices = [entry(m, v) for m, v in ordered]
    return {
        "_source": ENTSOE_API,
        "_note": "Attributes of the average-price sensor as built by JaccoR/hass-entso-e v0.7.5 from this API response; period PT60M (default), no template or VAT, time zone Europe/Berlin.",
        "state": prices[0]["price"],
        "attributes": {
            "unit_of_measurement": "€/kWh",
            "prices_today": [
                entry(m, v) for m, v in ordered if m.astimezone(LOCAL).date() == today
            ],
            "prices_tomorrow": [
                entry(m, v)
                for m, v in ordered
                if m.astimezone(LOCAL).date() == today + timedelta(days=1)
            ],
            "prices": prices,
        },
    }


if __name__ == "__main__":
    for name, build in (
        ("nordpool_raw_2025-10-01.json", nordpool),
        ("entsoe_prices_2024-10-06.json", entsoe),
    ):
        path = FIXTURES / name
        path.write_text(
            json.dumps(build(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print("written", path.relative_to(ROOT))
