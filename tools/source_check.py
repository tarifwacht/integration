#!/usr/bin/env python3
"""Check SMARD.de against the live website with the real parser (smard.py).

Usage (from the repo root):
    uv run tools/source_check.py [--markdown report.md]

The chart_data endpoints are not documented as an API, so a format change
would only show up in a user's look back (compare action). Fetched: the index and
the two newest week files (three requests). A problem is: a request fails
twice, the format is no longer recognised, the index or the prices are not
current, the previous week has gaps in its quarter-hour grid, or a price is
implausible (unit changed?). Exit code 1 if there is a problem. Run weekly by
.github/workflows/source-check.yml; nothing is written except the report.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.tarifwacht.const import USER_AGENT
from custom_components.tarifwacht.smard import (
    INDEX_URL,
    parse_index,
    parse_week,
    week_url,
)

RETRY_AFTER_S = 60
BERLIN = ZoneInfo("Europe/Berlin")  # week files start on Monday 00:00 local time
TIMEOUT = aiohttp.ClientTimeout(total=30)
INDEX_MAX_AGE = timedelta(days=14)  # newest week file must start within this
PRICES_MAX_AGE = timedelta(days=2)  # day-ahead prices reach into tomorrow
FULL_WEEK_SLOTS = 7 * 96
MIN_WEEK_SHARE = 0.95
PRICE_RANGE = (-0.5, 5.0)  # EUR/kWh; market limits are -500 and +4000 EUR/MWh


class CheckError(Exception):
    """A request failed or its data could not be parsed."""


async def get_json(session: aiohttp.ClientSession, url: str) -> Any:
    for attempt in range(2):
        try:
            async with session.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT
            ) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            if attempt == 0:
                await asyncio.sleep(RETRY_AFTER_S)
                continue
            raise CheckError(
                f"{url.rsplit('/', 1)[-1]}: {err or type(err).__name__}"
            ) from err
    raise AssertionError("unreachable")


def ms_to_utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


async def run_checks(
    session: aiohttp.ClientSession,
) -> list[tuple[str, str, str | None]]:
    """Rows of (check, value, problem or None)."""
    now = datetime.now(UTC)
    rows: list[tuple[str, str, str | None]] = []
    try:
        index = parse_index(await get_json(session, INDEX_URL))
    except (KeyError, TypeError, ValueError) as err:
        return [("Index", "–", f"Format nicht erkannt ({err!r})")]
    except CheckError as err:
        return [("Index", "–", f"Fehler: {err}")]
    if len(index) < 2:
        return [("Index", f"{len(index)} Wochen", "zu wenige Wochen im Index")]
    newest = ms_to_utc(index[-1])
    rows.append(
        (
            "Index: neueste Woche",
            f"{newest.astimezone(BERLIN):%Y-%m-%d} ({len(index)} Wochen)",
            "Index veraltet" if now - newest > INDEX_MAX_AGE else None,
        )
    )

    weeks: list[dict[datetime, float]] = []
    for start in index[-2:]:
        try:
            weeks.append(parse_week(await get_json(session, week_url(start))))
        except (KeyError, TypeError, ValueError) as err:
            return [
                *rows,
                (
                    f"Woche {ms_to_utc(start):%Y-%m-%d}",
                    "–",
                    f"Format nicht erkannt ({err!r})",
                ),
            ]
        except CheckError as err:
            return [
                *rows,
                (f"Woche {ms_to_utc(start):%Y-%m-%d}", "–", f"Fehler: {err}"),
            ]
    previous, current = weeks
    prices = {**previous, **current}

    rows.append(
        (
            "Vorwoche: Viertelstunden mit Preis",
            f"{len(previous)} von {FULL_WEEK_SLOTS}",
            "Lücken im Viertelstundenraster (Zeitstempel geändert?)"
            if len(previous) < MIN_WEEK_SHARE * FULL_WEEK_SLOTS
            else None,
        )
    )
    if not prices:
        return [*rows, ("Preise", "keine", "keine Preise erkannt (Format geändert?)")]
    latest = max(prices)
    rows.append(
        (
            "Letzter Preis",
            f"{latest:%Y-%m-%d %H:%M} UTC",
            "Preise nicht aktuell" if now - latest > PRICES_MAX_AGE else None,
        )
    )
    low, high = min(prices.values()), max(prices.values())
    rows.append(
        (
            "Preisspanne (€/kWh)",
            f"{low:.4f} … {high:.4f}, Median {statistics.median(prices.values()):.4f}",
            "unplausible Preise (Einheit geändert?)"
            if low < PRICE_RANGE[0] or high > PRICE_RANGE[1]
            else None,
        )
    )
    return rows


def report(rows: list[tuple[str, str, str | None]]) -> str:
    problems = [r for r in rows if r[2]]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"## Quellen-Check SMARD.de {now}",
        "",
        f"**{len(problems)} Prüfungen mit Problemen.**"
        if problems
        else "SMARD.de liefert aktuelle Preise im erwarteten Format.",
        "",
        "| Prüfung | Ergebnis | Befund |",
        "|---|---|---|",
    ]
    lines += [
        f"| {check} | {value} | {problem or 'ok'} |" for check, value, problem in rows
    ]
    return "\n".join(lines) + "\n"


async def check_all() -> list[tuple[str, str, str | None]]:
    # Windows: aiodns (installed with Home Assistant) cannot find the DNS servers.
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        return await run_checks(session)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--markdown", help="also write the report to this file")
    args = parser.parse_args()
    rows = asyncio.run(check_all())
    text = report(rows)
    print(text)
    if args.markdown:
        Path(args.markdown).write_text(text, encoding="utf-8")
    sys.exit(1 if any(problem for _, _, problem in rows) else 0)
