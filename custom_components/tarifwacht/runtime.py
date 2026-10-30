"""Home Assistant side of one meter: listens to meter and price, stores state."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance, history
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_utc_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BERLIN,
    CONF_CURRENT,
    CONF_KIND,
    CONF_METER,
    CONF_NAME,
    CONF_PRICE_ENTITY,
    CONF_RENAMED,
    CONF_SMARD_FILL,
    DOMAIN,
    KIND_DYNAMIC_MARKET,
    KIND_DYNAMIC_TOTAL,
    MAX_GRID_POWER_KW,
    PRICE_UNITS,
    SUBENTRY_TARIFF,
)
from .engine import Engine, migrate_v1
from .lookback import (
    FallbackPrice,
    Lookback,
    hour_start,
    hours_without_energy,
    spread_hours,
)
from .meter import MeterTracker, to_kwh
from .prices import (
    ParsedPrices,
    PriceTable,
    parse_price_attributes,
    prices_from_states,
)
from .rename import renamed_storage
from .smard_cache import SmardError, smard_cache
from .tariff_config import price_entity, tariff_from_data, tariff_key
from .tariffs import PriceSource, Tariff
from .timeslots import slot_start

_LOGGER = logging.getLogger(__name__)

# 1: 0.1.0b1 (running totals); 2: consumption and prices per quarter hour;
# 3: closed days in yearly archives, the live file keeps yesterday and today.
STORAGE_VERSION = 3
ARCHIVE_VERSION = 1

# Few, small writes spare SD cards. The live state (a few KB) is written after
# each quarter-hour tick and on unload; a crash loses at most a quarter hour,
# which the next meter reading and the price forecast make good again. Each
# yearly archive is written once a day, when a UTC day closes.
SAVE_DELAY = 10
# Entities (and so the recorder) are updated at most this often, and at each
# quarter-hour tick, not on every meter reading.
NOTIFY_INTERVAL = timedelta(seconds=60)

# Recorder history is read from this long before the setup of the entry, so
# the reading in effect at the setup is found as the baseline.
BACKFILL_MARGIN = timedelta(hours=1)

# A price still missing this long after its quarter hour is reported as a
# repair issue (day-ahead prices are known the day before).
LATE_PRICE_GRACE = timedelta(hours=1)

# A source entity (meter, price sensor) that does not exist this long after
# the start is reported as a repair issue; other integrations may still be
# starting before that.
MISSING_GRACE = timedelta(minutes=10)


def parse_price_state(state: State, now: datetime | None = None) -> ParsedPrices | None:
    """Prices from a price sensor: known forecast attributes, else the state.

    A plain state is the price of the quarter hour `now` falls in (by default
    the one of its last update); the quarter-hour tick carries it on.
    """
    if (parsed := parse_price_attributes(state.attributes)) is not None:
        return parsed
    try:
        price = float(state.state)
    except ValueError:
        return None
    slot = slot_start(now or state.last_updated)
    return ParsedPrices(prices={slot: price}, format="state")


def price_unit_ok(state: State) -> bool:
    return state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) in PRICE_UNITS


def recorded_price(state: State) -> float | None:
    """Price of a recorded price state; None if not a number or another unit."""
    if not price_unit_ok(state):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


def meter_reading(state: State) -> float | None:
    """Meter state in kWh; None if unavailable, not numeric or in another unit."""
    if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        return to_kwh(
            float(state.state), state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        )
    except KeyError, ValueError:
        return None


@dataclass(frozen=True)
class TariffInfo:
    """A tariff subentry as the sensors see it."""

    key: str
    subentry_id: str
    title: str
    current: bool


def tariff_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    return [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TARIFF]


class TarifwachtStore(Store[dict[str, Any]]):
    """Storage of one entry; converts the format of 0.1.0b1."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._entry = entry

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: Any
    ) -> dict[str, Any]:
        if old_major_version == 1:
            # 0.1.0b1 had one price sensor: the one of its dynamic tariff.
            source = next(
                (
                    entity
                    for s in tariff_subentries(self._entry)
                    if (entity := price_entity(s.data))
                ),
                "",
            )
            return migrate_v1(old_data, source, self._entry.created_at)
        if old_major_version == 2:
            # Same format; the first start moves closed days to the archives.
            return dict(old_data)
        raise NotImplementedError


class MeterRuntime:
    """Feeds the engine and notifies entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.data[CONF_NAME]
        self.meter_entity: str = entry.data[CONF_METER]
        self.engine = Engine(
            meter=MeterTracker(
                max_power_kw=MAX_GRID_POWER_KW, source=self.meter_entity
            ),
            tariffs={},
            tz=BERLIN,
        )
        self.tariffs: dict[str, TariffInfo] = {}
        self.price_entities: set[str] = set()
        for subentry in tariff_subentries(entry):
            key = tariff_key(subentry.subentry_id, subentry.data)
            self.engine.tariffs[key] = tariff_from_data(
                subentry.data, self.engine.price_table
            )
            self.tariffs[key] = TariffInfo(
                key=key,
                subentry_id=subentry.subentry_id,
                title=subentry.title,
                current=bool(subentry.data.get(CONF_CURRENT)),
            )
            if entity := price_entity(subentry.data):
                self.price_entities.add(entity)
        self.unknown_unit: str | None = None
        self.meter_unit_ok = True
        self.wrong_price_unit: dict[str, str | None] = {}
        self.backfill_error: str | None = None
        self.past_prices_error: str | None = None
        self._store = TarifwachtStore(hass, entry)
        self._archives: dict[int, Store[dict[str, Any]]] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._last_notify: datetime | None = None
        self._notify_later: CALLBACK_TYPE | None = None
        self._started_at: datetime | None = None
        # Repair issues currently shown: issue id -> (translation key, placeholders)
        self._issues: dict[str, tuple[str, dict[str, str]]] = {}

    async def async_lookback(self, start: datetime) -> Lookback | None:
        """Consumption and tariffs for the quarter hours from `start` to the setup.

        None if `start` is not before the setup. Exchange prices of that time
        are fetched from SMARD.de, only if a tariff needs them; raises
        SmardError if that fails.
        """
        until = self.engine.started
        if until is None or slot_start(start) >= until:
            return None
        hourly = await self._async_hourly_energy(hour_start(start), until)
        smard: PriceTable = PriceTable()
        market = self._market_tariffs()
        if market:
            end = max(until, *(self._smard_until(data) for data in market))
            smard = await smard_cache(self.hass).async_prices(start, end)
        return Lookback(
            consumption=spread_hours(hourly, start, until),
            tariffs=self._build_tariffs(smard),
            until=until,
            hours_without_energy=hours_without_energy(hourly, start, until),
            uses_smard=bool(market),
        )

    def _total_price_entities(self) -> set[str]:
        """Price sensors of the total-price tariffs."""
        return {
            s.data[CONF_PRICE_ENTITY]
            for s in tariff_subentries(self.entry)
            if s.data.get(CONF_KIND) == KIND_DYNAMIC_TOTAL
        }

    def _market_tariffs(self) -> list[Mapping[str, Any]]:
        """Data of the exchange price tariffs."""
        return [
            s.data
            for s in tariff_subentries(self.entry)
            if s.data.get(CONF_KIND) == KIND_DYNAMIC_MARKET
        ]

    def _smard_until(self, data: Mapping[str, Any]) -> datetime:
        """Exchange prices before this come from SMARD.de where the sensor has none.

        The setup; for a tariff whose sensor Tarifwacht read only later (added
        later or given another sensor), its first price, but only if the user
        agreed to fill that time from SMARD.de (`smard_fill`).
        """
        started = self.engine.started
        assert started is not None
        if not data.get(CONF_SMARD_FILL):
            return started
        return self.engine.unpriced_until(data[CONF_PRICE_ENTITY]) or started

    def _smard_gaps(self) -> list[Mapping[str, Any]]:
        """Exchange price tariffs with time to fill from SMARD.de (agreed to)."""
        started = self.engine.started
        return [d for d in self._market_tariffs() if self._smard_until(d) != started]

    def _build_tariffs(self, smard: PriceSource | None = None) -> dict[str, Tariff]:
        """The engine's tariffs; with `smard`, exchange prices completed from it."""
        tariffs: dict[str, Tariff] = {}
        for subentry in tariff_subentries(self.entry):
            data = subentry.data

            def market(entity: str, data: Mapping[str, Any] = data) -> PriceSource:
                table = self.engine.price_table(entity)
                if smard is None:
                    return table
                return FallbackPrice(table, smard, self._smard_until(data))

            key = tariff_key(subentry.subentry_id, data)
            tariffs[key] = tariff_from_data(data, self.engine.price_table, market)
        return tariffs

    async def _async_fill_past_prices(self) -> None:
        """Prices for the time before Tarifwacht read a tariff's price sensor.

        A tariff added later, or given another price sensor, would otherwise
        leave that time out of every comparison. Exchange prices come from
        SMARD.de (stored for all entries), only for tariffs whose user agreed
        to it in the tariff's form; a total price only from the sensor's own
        recorded states (local), never from SMARD.de. Runs in the background;
        what fails or cannot be found stays without a price, and the next
        start tries again.
        """
        engine = self.engine
        added = False
        for entity in sorted(self._total_price_entities()):
            if (until := engine.unpriced_until(entity)) is not None:
                added |= await self._async_recorded_prices(entity, until)
        smard: PriceTable | None = None
        market = self._smard_gaps()
        if market and engine.started is not None:
            end = max(self._smard_until(data) for data in market)
            try:
                smard = await smard_cache(self.hass).async_prices(engine.started, end)
            except SmardError as err:
                self.past_prices_error = f"SMARD.de: {err}"
                _LOGGER.warning(
                    "%s: exchange prices from SMARD.de failed: %s", self.name, err
                )
            else:
                engine.tariffs = self._build_tariffs(smard)
        if not added and smard is None:
            return
        now = dt_util.utcnow()
        engine.recompute(now)
        self._update_issues(now)
        self._notify()
        if added:
            self._store.async_delay_save(engine.as_dict, SAVE_DELAY)
            await self._async_archive(now)

    async def _async_recorded_prices(self, entity: str, until: datetime) -> bool:
        """Fill a total-price sensor's prices before `until` from the recorder.

        The recorder keeps states for some days (10 by default); older time
        stays without a price. True if prices were added.
        """
        started = self.engine.started
        if started is None or "recorder" not in self.hass.config.components:
            return False
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                history.state_changes_during_period,
                self.hass,
                started,
                # Up to now: the state after `until` tells whether the last
                # one before it held (see `prices_from_states`).
                dt_util.utcnow(),
                entity,
            )
        except Exception as err:  # never block the setup
            self.past_prices_error = f"{entity}: {type(err).__name__}: {err}"
            _LOGGER.warning("%s: reading the recorder failed: %s", self.name, err)
            return False
        recorded = [
            (state.last_updated, recorded_price(state))
            for state in states.get(entity.lower(), [])
        ]
        prices = prices_from_states(recorded, started, until)
        _LOGGER.debug(
            "%s: %s prices of %s from the recorder", self.name, len(prices), entity
        )
        return self.engine.add_past_prices(entity, prices)

    async def _async_hourly_energy(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        """The meter's energy per hour (kWh) from the long-term statistics."""
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            {self.meter_entity},
            "hour",
            {"energy": UnitOfEnergy.KILO_WATT_HOUR},
            {"change"},
        )
        return [
            (dt_util.utc_from_timestamp(row["start"]), row["change"])
            for row in rows.get(self.meter_entity, [])
            if row.get("change") is not None
        ]

    @property
    def current(self) -> TariffInfo | None:
        """The tariff the others are compared with (first marked one)."""
        return next((t for t in self.tariffs.values() if t.current), None)

    def _archive_store(self, year: int) -> Store[dict[str, Any]]:
        if year not in self._archives:
            self._archives[year] = Store(
                self.hass, ARCHIVE_VERSION, f"{DOMAIN}.{self.entry.entry_id}.{year}"
            )
        return self._archives[year]

    def _archive_years(self, now: datetime) -> range:
        """Years that may have an archive, from the start of the period."""
        first = self.engine.started.year if self.engine.started else now.year
        return range(first, now.year + 1)

    async def async_start(self) -> None:
        """Restore the stored state, read current values, start listening."""
        now = dt_util.utcnow()
        self._started_at = now
        # Sources renamed since the last start: their stored prices and the
        # meter's last reading move to the new ids (rename.py).
        renames: dict[str, str] = dict(self.entry.data.get(CONF_RENAMED) or {})
        if data := await self._store.async_load():
            self.engine.restore(dict(renamed_storage(data, renames)))
        for year in self._archive_years(now):
            if archived := await self._archive_store(year).async_load():
                self.engine.restore_archive(dict(renamed_storage(archived, renames)))
        if renames:
            # The archives are written again under the new ids (below).
            self.engine.archived_until = None
        if self.engine.backfill_until is not None:
            await self._async_backfill()
        self.engine.start(now)
        for entity in sorted(self.price_entities):
            if state := self.hass.states.get(entity):
                self._handle_price(state, now)
        if state := self.hass.states.get(self.meter_entity):
            self._handle_meter(state, now)
        self.engine.tick(now)
        self._unsubscribe = [
            async_track_state_change_event(
                self.hass,
                [self.meter_entity, *sorted(self.price_entities)],
                self._on_state_change,
            ),
            async_track_utc_time_change(
                self.hass, self._on_tick, minute=[0, 15, 30, 45], second=1
            ),
        ]
        await self._async_archive(now)
        if renames:
            await self._store.async_save(self.engine.as_dict())
            self._forget_renames(renames)
        # Issues of an earlier run are dropped unless still valid.
        self._issues = {issue_id: ("", {}) for issue_id in self._stored_issue_ids()}
        self._update_issues(now)
        if self._smard_gaps() or any(
            self.engine.unpriced_until(e) is not None
            for e in self._total_price_entities()
        ):
            self.entry.async_create_background_task(
                self.hass, self._async_fill_past_prices(), f"{DOMAIN} past prices"
            )

    def _forget_renames(self, done: Mapping[str, str]) -> None:
        """Drop the renames whose stored state has moved.

        Called during the setup, before the update listener is added: no
        reload. A rename noted meanwhile stays (its own reload follows).
        """
        renames = self.entry.data.get(CONF_RENAMED) or {}
        left = {s: c for s, c in renames.items() if done.get(s) != c}
        data = {k: v for k, v in self.entry.data.items() if k != CONF_RENAMED}
        if left:
            data[CONF_RENAMED] = left
        self.hass.config_entries.async_update_entry(self.entry, data=data)

    def _stored_issue_ids(self) -> list[str]:
        prefix = f"{self.entry.entry_id}_"
        return [
            issue_id
            for domain, issue_id in ir.async_get(self.hass).issues
            if domain == DOMAIN and issue_id.startswith(prefix)
        ]

    def _update_issues(self, now: datetime) -> None:
        """Show problems as repair issues; remove them once solved.

        Only changes are written to the issue registry (it is stored on disk).
        """
        prefix = f"{self.entry.entry_id}_"
        wanted: dict[str, tuple[str, dict[str, str]]] = {}
        for source, unit in self.wrong_price_unit.items():
            wanted[f"{prefix}price_unit_{source}"] = (
                "price_unit",
                {"name": self.name, "entity": source, "unit": str(unit)},
            )
        if not self.meter_unit_ok:
            wanted[f"{prefix}meter_unit"] = (
                "meter_unit",
                {
                    "name": self.name,
                    "entity": self.meter_entity,
                    "unit": str(self.unknown_unit),
                },
            )
        missing = [
            entity
            for entity in (self.meter_entity, *sorted(self.price_entities))
            if self.hass.states.get(entity) is None
        ]
        started = self._started_at
        if missing and started is not None and now - started >= MISSING_GRACE:
            wanted[f"{prefix}missing_entity"] = (
                "missing_entity",
                {"name": self.name, "entities": ", ".join(missing)},
            )
        if late := self.engine.late_prices(now, LATE_PRICE_GRACE):
            titles = sorted(self.tariffs[key].title for key in late)
            wanted[f"{prefix}late_prices"] = (
                "late_prices",
                {"name": self.name, "tariffs": ", ".join(titles)},
            )
        if self.backfill_error is not None:
            wanted[f"{prefix}backfill_failed"] = (
                "backfill_failed",
                {"name": self.name, "error": self.backfill_error},
            )
        for issue_id in self._issues.keys() - wanted.keys():
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        for issue_id, (key, placeholders) in wanted.items():
            if self._issues.get(issue_id) != (key, placeholders):
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=key,
                    translation_placeholders=placeholders,
                )
        self._issues = wanted

    async def _async_archive(self, now: datetime) -> None:
        """Move closed UTC days (before yesterday) to the yearly archives.

        Writes once a day: each year from the last archived day up to now, so
        late changes to days of the current year are kept as well. Then the
        live state is saved without them.
        """
        cutoff = now.astimezone(UTC).date() - timedelta(days=1)
        since = self.engine.archived_until
        if since is not None and since >= cutoff:
            return
        years = self.engine.years()
        first = since.year if since else min(years, default=cutoff.year)
        for year in range(first, cutoff.year + 1):
            data = self.engine.archive_dict(year, cutoff)
            if data["consumption"] or any(data["prices"].values()):
                await self._archive_store(year).async_save(data)
        self.engine.archived_until = cutoff
        self._store.async_delay_save(self.engine.as_dict, SAVE_DELAY)

    async def _async_backfill(self) -> None:
        """Read the consumption 0.1.0b1 did not keep from the recorder.

        From the setup of the entry up to the last reading 0.1.0b1 booked. If
        the recorder is not available, the next start tries again; live
        booking is not affected.
        """
        until = self.engine.backfill_until
        if until is None:
            return
        if "recorder" not in self.hass.config.components:
            self.backfill_error = "recorder not available"
            return
        created = self.entry.created_at
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                history.state_changes_during_period,
                self.hass,
                # Start earlier: a reading exactly at `created` would be
                # neither the start state nor a change after the start.
                created - BACKFILL_MARGIN,
                # The end is exclusive; the reading at `until` belongs to it.
                until + timedelta(microseconds=1),
                self.meter_entity,
            )
        except Exception as err:  # never block the setup
            self.backfill_error = f"{type(err).__name__}: {err}"
            _LOGGER.warning("%s: reading the recorder failed: %s", self.name, err)
            return
        readings = [
            (value, state.last_updated)
            for state in states.get(self.meter_entity.lower(), [])
            if (value := meter_reading(state)) is not None
        ]
        self.engine.backfill(readings, since=created)
        self.backfill_error = None
        _LOGGER.debug(
            "%s: %s readings read from the recorder", self.name, len(readings)
        )

    async def async_stop(self) -> None:
        """Stop listening and write the state."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []
        if self._notify_later is not None:
            self._notify_later()
            self._notify_later = None
        await self._async_archive(dt_util.utcnow())
        await self._store.async_save(self.engine.as_dict())

    async def async_remove(self) -> None:
        """Delete the live state and all yearly archives."""
        now = dt_util.utcnow()
        if data := await self._store.async_load():
            self.engine.restore(data)
        for year in self._archive_years(now):
            await self._archive_store(year).async_remove()
        await self._store.async_remove()
        for issue_id in self._stored_issue_ids():
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @callback
    def add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        if state is None:
            return
        now = dt_util.utcnow()
        if state.entity_id == self.meter_entity:
            self._handle_meter(state, now)
        else:
            self._handle_price(state, now)
        self._update_issues(now)
        self._changed()

    @callback
    def _on_tick(self, now: datetime) -> None:
        # A sensor without a forecast only shows the current price and may
        # keep it for an hour without a state change: it holds for the quarter
        # hour that just began, too.
        for entity in sorted(self.price_entities):
            if state := self.hass.states.get(entity):
                self._handle_price(state, now)
        self.engine.tick(now)
        self._update_issues(now)
        self._notify()
        self._store.async_delay_save(self.engine.as_dict, SAVE_DELAY)
        cutoff = now.astimezone(UTC).date() - timedelta(days=1)
        if self.engine.archived_until is None or self.engine.archived_until < cutoff:
            self.entry.async_create_background_task(
                self.hass, self._async_archive(now), f"{DOMAIN} archive"
            )

    def _handle_meter(self, state: State, now: datetime) -> None:
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        try:
            value = to_kwh(float(state.state), unit)
        except KeyError:
            if self.unknown_unit != unit:
                _LOGGER.warning("%s: unsupported unit %s", self.meter_entity, unit)
            self.unknown_unit = unit
            self.meter_unit_ok = False
            return
        except ValueError:
            return
        self.unknown_unit = None
        self.meter_unit_ok = True
        update = self.engine.on_meter(value, state.last_updated, now)
        if update.event is not None:
            _LOGGER.debug(
                "%s: %s (delta %s kWh)", self.meter_entity, update.event, update.delta
            )

    def _handle_price(self, state: State, now: datetime) -> None:
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        source = state.entity_id
        if not price_unit_ok(state):
            # Prices are used as they are: a wrong unit would book nonsense.
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if self.wrong_price_unit.get(source) != unit:
                _LOGGER.warning(
                    "%s: unsupported price unit %s (expected €/kWh)", source, unit
                )
            self.wrong_price_unit[source] = unit
            return
        self.wrong_price_unit.pop(source, None)
        if (parsed := parse_price_state(state, now)) is not None:
            self.engine.on_prices(source, parsed, now)

    def _changed(self) -> None:
        """Notify entities now, or once the minute since the last time is over."""
        if self._notify_later is not None:
            return
        now = dt_util.utcnow()
        if self._last_notify is None or now - self._last_notify >= NOTIFY_INTERVAL:
            self._notify()
            return
        self._notify_later = async_call_later(
            self.hass, self._last_notify + NOTIFY_INTERVAL - now, self._on_notify_later
        )

    @callback
    def _on_notify_later(self, _now: datetime) -> None:
        self._notify_later = None
        self._notify()

    def _notify(self) -> None:
        if self._notify_later is not None:
            self._notify_later()
            self._notify_later = None
        self._last_notify = dt_util.utcnow()
        for listener in list(self._listeners):
            listener()
