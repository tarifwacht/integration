"""SMARD.de day-ahead prices shared by all entries, kept in yearly stores.

Fetched only when the compare action needs exchange prices from before the
setup of an entry. Past prices do not change, so each week is downloaded once;
a yearly store is written only after new weeks came in.
"""

from __future__ import annotations

import asyncio
from bisect import bisect_left
from datetime import UTC, date, datetime
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, USER_AGENT
from .prices import PriceTable
from .smard import (
    INDEX_URL,
    WEEK,
    parse_index,
    parse_week,
    week_start,
    week_url,
    weeks_covering,
)
from .timeslots import QUARTER, slot_start

STORAGE_VERSION = 1
# One request per week of history; be gentle with the website.
PAUSE = 0.5
TIMEOUT = aiohttp.ClientTimeout(total=30)

DATA_SMARD: HassKey[SmardCache] = HassKey(f"{DOMAIN}_smard")


class SmardError(Exception):
    """SMARD.de could not be reached or answered in an unknown format."""


def smard_cache(hass: HomeAssistant) -> SmardCache:
    if DATA_SMARD not in hass.data:
        hass.data[DATA_SMARD] = SmardCache(hass)
    return hass.data[DATA_SMARD]


class SmardCache:
    """Exchange prices (EUR/kWh) by quarter hour, loaded and fetched on demand."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.table = PriceTable()
        self._loaded: set[int] = set()
        self._lock = asyncio.Lock()

    def _store(self, year: int) -> Store[dict[str, Any]]:
        return Store(self.hass, STORAGE_VERSION, f"{DOMAIN}.smard.{year}")

    async def async_prices(
        self, start: datetime, end: datetime, *, fetch: bool = True
    ) -> PriceTable:
        """The table, complete for [start, end) as far as SMARD.de has prices.

        Without `fetch` only what is stored already (no network).
        """
        async with self._lock:
            for year in range(start.astimezone(UTC).year, end.astimezone(UTC).year + 1):
                if year not in self._loaded:
                    if data := await self._store(year).async_load():
                        self.table.restore(data, merge=True)
                    self._loaded.add(year)
            if fetch and (missing := self._missing(start, end)):
                await self._async_fetch(missing)
        return self.table

    def _missing(self, start: datetime, end: datetime) -> list[datetime]:
        slots = []
        slot = slot_start(start)
        while slot < end:
            if self.table.get(slot) is None:
                slots.append(slot)
            slot += QUARTER
        return slots

    async def _async_fetch(self, missing: list[datetime]) -> None:
        session = async_get_clientsession(self.hass)
        changed: set[int] = set()
        try:
            index = parse_index(await self._async_get_json(session, INDEX_URL))
            weeks = [
                week
                for week in weeks_covering(index, missing[0], missing[-1] + QUARTER)
                if (i := bisect_left(missing, week_start(week))) < len(missing)
                and missing[i] < week_start(week) + WEEK
            ]
            for n, week in enumerate(weeks):
                if n:
                    await asyncio.sleep(PAUSE)
                prices = parse_week(await self._async_get_json(session, week_url(week)))
                self.table.merge(prices)
                changed |= {slot.year for slot in prices}
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SmardError(str(err) or type(err).__name__) from err
        except (KeyError, TypeError, ValueError) as err:
            raise SmardError(f"unexpected format: {err}") from err
        finally:
            # Keep what came in, also when a later week failed.
            for year in changed:
                await self._store(year).async_save(
                    self.table.as_dict(start=date(year, 1, 1), end=date(year + 1, 1, 1))
                )

    @staticmethod
    async def _async_get_json(session: aiohttp.ClientSession, url: str) -> Any:
        async with session.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT
        ) as response:
            response.raise_for_status()
            return await response.json(content_type=None)
