"""Statistics of the sensors: the history before them, and recalculated.

Import (action tarifwacht.import_statistics): the sensors only have
long-term statistics since they exist. This fills the hours before each
sensor's first statistic: before the setup from the lookback (hourly meter
statistics, prices as in the compare action), after it from the stored
quarter hours (a tariff added later). The later sums are shifted by the
imported total so the series stays continuous - the same adjustment Home
Assistant's own "fix statistics" uses (pattern of Einspeisewacht). A second
call finds nothing left.

Recalculation (button "Recalculate statistics", the action with `replace`):
a changed tariff applies to the whole period, the sensors show the new sums
at once - but the statistics of past hours keep the old prices. This
replaces the hourly rows (and the short-term rows of the last days) from
each sensor's first row (or the chosen day) up to the last compiled hour
with values computed like the import, and shifts the rows after it so Home
Assistant continues without a jump (statistics_rows.py, docs/ENTWICKLUNG.md
"Statistik neu berechnen").

A tariff without the price of a quarter hour in the period is skipped as a
whole: no gaps in the permanent statistics.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from itertools import chain
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.db_schema import StatisticsShortTerm
from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .lookback import (
    FIVE_MINUTES,
    HOUR,
    HourlyCosts,
    Lookback,
    hour_start,
    hourly_costs,
    period_costs,
    period_start,
)
from .outdated import async_clear_outdated
from .smard import ATTRIBUTION
from .statistics_rows import Row, add_values, build_rows, place_savings, total_between

if TYPE_CHECKING:
    from . import TarifwachtConfigEntry
    from .runtime import SolarHourly

# One import or recalculation per entry at a time (kept across reloads).
LOCKS: HassKey[dict[str, asyncio.Lock]] = HassKey(f"{DOMAIN}_statistics_locks")
# Implausible hours named in a result (the first ones).
IMPLAUSIBLE_SHOWN = 5
# Long-term statistics are read from here (before any sensor existed).
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
# Short-term rows are recalculated this far back: Home Assistant keeps them
# for 10 days by default. Older ones (with a longer `purge_keep_days`) stay
# as they are; only 5-minute graphs of that time show them.
SHORT_TERM_PERIOD = timedelta(days=10)


class StatisticsImportError(Exception):
    """Refused; `key` names the translated reason."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


# A sensor's value per hour from the hourly costs (None: not computable).
Series = Callable[[HourlyCosts], dict[datetime, float] | None]


def _series(entry: TarifwachtConfigEntry) -> dict[str, tuple[Series, str | None]]:
    """Unique id -> (value per hour, tariff it belongs to) for every sensor with a sum."""
    runtime = entry.runtime_data
    current = runtime.current

    def tariff_value(key: str, name: str) -> Series:
        def value(costs: HourlyCosts) -> dict[datetime, float] | None:
            if key in costs.incomplete:
                return None
            return getattr(costs, name)[key]

        return value

    def difference(key: str, current_key: str) -> Series:
        def value(costs: HourlyCosts) -> dict[datetime, float] | None:
            if costs.incomplete & {key, current_key}:
                return None
            ours, theirs = costs.cost[key], costs.cost[current_key]
            return {hour: ours[hour] - theirs[hour] for hour in ours}

        return value

    prefix = entry.entry_id
    series: dict[str, tuple[Series, str | None]] = {
        f"{prefix}_energy": (lambda costs: costs.energy, None)
    }
    for tariff in runtime.tariffs.values():
        for name in ("consumption_cost", "cost"):
            series[f"{prefix}_{tariff.key}_{name}"] = (
                tariff_value(tariff.key, name),
                tariff.title,
            )
        if current is not None and tariff.key != current.key:
            series[f"{prefix}_{tariff.key}_difference"] = (
                difference(tariff.key, current.key),
                tariff.title,
            )
    return series


def _solar_series(entry: TarifwachtConfigEntry) -> dict[str, tuple[str, int, str]]:
    """Unique id -> (tariff key, 0 PV / 1 battery, tariff title) of the
    saving sensors of PV and battery."""
    prefix = entry.entry_id
    series: dict[str, tuple[str, int, str]] = {}
    for tariff in entry.runtime_data.tariffs.values():
        for index, name in enumerate(("saving_pv", "saving_battery")):
            series[f"{prefix}_{tariff.key}_{name}"] = (tariff.key, index, tariff.title)
    return series


def _targets(
    hass: HomeAssistant, entry: TarifwachtConfigEntry
) -> tuple[dict[str, tuple[Series, str | None]], dict[str, tuple[str, int, str]]]:
    """Entity id -> what it is, for the sensors with a sum that exist."""
    registry = er.async_get(hass)
    targets: dict[str, tuple[Series, str | None]] = {}
    for unique_id, target in _series(entry).items():
        if entity_id := registry.async_get_entity_id("sensor", DOMAIN, unique_id):
            targets[entity_id] = target
    solar_targets: dict[str, tuple[str, int, str]] = {}
    for unique_id, solar_target in _solar_series(entry).items():
        if entity_id := registry.async_get_entity_id("sensor", DOMAIN, unique_id):
            solar_targets[entity_id] = solar_target
    return targets, solar_targets


def implausible_summary(hours: Iterable[datetime]) -> dict[str, Any] | None:
    """Hours left out as implausible: how many, and the first ones (local)."""
    found = sorted(set(hours))
    if not found:
        return None
    return {
        "count": len(found),
        "hours": [dt_util.as_local(h).isoformat() for h in found[:IMPLAUSIBLE_SHOWN]],
    }


def _lock(hass: HomeAssistant, entry: TarifwachtConfigEntry) -> asyncio.Lock:
    return hass.data.setdefault(LOCKS, {}).setdefault(entry.entry_id, asyncio.Lock())


def _rows(values: list[tuple[datetime, float]]) -> tuple[list[StatisticData], float]:
    """Running sums of hourly values, and their total."""
    rows: list[StatisticData] = []
    total = 0.0
    for hour, value in values:
        total += value
        rows.append(StatisticData(start=hour, state=total, sum=total))
    return rows, total


async def async_import_history(
    hass: HomeAssistant, entry: TarifwachtConfigEntry, first_day: date
) -> dict[str, Any]:
    """Import hourly statistics from `first_day` until each sensor's first one.

    Raises StatisticsImportError, or SmardError if exchange prices are needed
    and cannot be loaded.
    """
    lock = _lock(hass, entry)
    if lock.locked():
        raise StatisticsImportError("busy")
    async with lock:
        return await _async_import_history(hass, entry, first_day)


async def _async_import_history(
    hass: HomeAssistant, entry: TarifwachtConfigEntry, first_day: date
) -> dict[str, Any]:
    runtime = entry.runtime_data
    engine = runtime.engine
    if engine.started is None:
        raise StatisticsImportError("no_statistics_yet")
    started = engine.started
    start = dt_util.as_utc(dt_util.start_of_local_day(first_day))
    # Before the setup the sensors have no statistics, so the imported sums can
    # start at 0; a later start could fall into a gap after existing rows.
    if start >= started:
        raise StatisticsImportError("start_after_setup")
    targets, solar_targets = _targets(hass, entry)

    instance = get_instance(hass)
    existing = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        None,
        set(targets) | set(solar_targets),
        "hour",
        None,
        {"sum"},
    )
    firsts = {
        entity_id: dt_util.utc_from_timestamp(rows[0]["start"])
        for entity_id in (*targets, *solar_targets)
        if (rows := existing.get(entity_id))
    }
    if not firsts:
        raise StatisticsImportError("no_statistics_yet")
    if max(firsts.values()) <= start:
        raise StatisticsImportError("nothing_to_import")

    lookback = await runtime.async_lookback(start)
    if lookback is None:  # only if the start were not before the setup
        raise StatisticsImportError("start_after_setup")
    # No base prices for the time before the meter's first statistic.
    start = max(start, hour_start(min(lookback.consumption, default=started)))
    with_energy = {hour_start(slot) for slot in lookback.consumption}
    hours_missing, hour = 0, start
    while hour < started:
        hours_missing += hour not in with_energy
        hour += HOUR
    quarters = list(chain(lookback.consumption.items(), engine.consumption.items()))

    def costs(a: datetime, b: datetime) -> HourlyCosts:
        return hourly_costs(quarters, lookback.tariffs, a, b, engine.tz)

    metadata = await instance.async_add_executor_job(
        lambda: get_metadata(hass, statistic_ids=set(firsts))
    )
    result: dict[str, Any] = {
        "start": dt_util.as_local(start).isoformat(),
        "setup": dt_util.as_local(started).isoformat(),
        "hours_without_energy": hours_missing,
        "sensors": {},
        "skipped": [],
    }
    by_first: dict[datetime, tuple[HourlyCosts, HourlyCosts | None]] = {}
    # Some sensor already reaches back to the start (a repeated call).
    done_before = False
    for entity_id, first in sorted(firsts.items()):
        if first <= start:
            done_before = True
            continue
        if entity_id not in metadata or entity_id not in targets:
            continue
        if first not in by_first:
            # The quarter hours of the first statistics hour before the setup:
            # not counted by the sensor, added to that hour's change.
            extra = costs(first, started) if first < started else None
            by_first[first] = (costs(start, first), extra)
        before, extra = by_first[first]
        value, tariff_title = targets[entity_id]
        values = value(before)
        extra_values = value(extra) if extra is not None else {}
        if values is None or extra_values is None:
            if tariff_title not in result["skipped"]:
                result["skipped"].append(tariff_title)
            continue
        rows, total = _rows(sorted(values.items()))
        if not rows:
            continue
        meta = metadata[entity_id][1]
        async_import_statistics(hass, meta, rows)
        shift = total + sum(extra_values.values())
        # Shift every later sum (short- and long-term) by what was added before.
        instance.async_adjust_statistics(
            entity_id, first, shift, meta["unit_of_measurement"] or ""
        )
        result["sensors"][entity_id] = {
            "hours": len(rows),
            "added": round(shift, 4),
            "until": dt_util.as_local(first - HOUR).isoformat(),
        }

    # Saving by PV and battery. Each hour's state holds the complete hours
    # before it (hourly update), so [start, first) is exactly what is missing.
    used_smard = lookback.uses_smard
    implausible = list(lookback.implausible_hours)
    solar_by_first: dict[datetime, dict[str, Any]] = {}
    for entity_id, first in sorted(firsts.items()):
        if (
            first <= start
            or entity_id not in solar_targets
            or entity_id not in metadata
        ):
            continue
        if first not in solar_by_first:
            computed = await runtime.async_solar_hourly(start, first, lookback)
            if computed is None:
                break
            solar_by_first[first], smard, solar_implausible = computed
            used_smard |= smard
            implausible += solar_implausible
        key, index, tariff_title = solar_targets[entity_id]
        hourly = solar_by_first[first].get(key)
        if hourly is None:
            if tariff_title not in result["skipped"]:
                result["skipped"].append(tariff_title)
            continue
        rows, total = _rows([(hour, v[index]) for hour, v in sorted(hourly.items())])
        if not rows:
            continue
        meta = metadata[entity_id][1]
        async_import_statistics(hass, meta, rows)
        instance.async_adjust_statistics(
            entity_id, first, total, meta["unit_of_measurement"] or ""
        )
        result["sensors"][entity_id] = {
            "hours": len(rows),
            "added": round(total, 4),
            "until": dt_util.as_local(first - HOUR).isoformat(),
        }
    if used_smard:
        result["exchange_prices"] = ATTRIBUTION
    if summary := implausible_summary(implausible):
        result["hours_implausible"] = summary
    if not result["sensors"]:
        raise StatisticsImportError(
            "prices_missing"
            if result["skipped"] and not done_before
            else "nothing_to_import"
        )
    return result


# Recalculation


@dataclass
class _Plan:
    """What is recalculated of one sensor."""

    # First recalculated moment: an hour, or the setup (the first quarter hour
    # the sensor counted itself).
    start: datetime
    # The sum before `start` (0 from the first row on).
    base: float
    # End: the hour of the latest short-term row; that row and those after
    # it stay as Home Assistant wrote them and are shifted.
    end: datetime
    # Short-term rows to rewrite (their starts) and the hour they begin in.
    short: set[datetime]
    short_from: datetime | None
    # The old sum at `end`, and the latest short-term row (start, state, sum).
    old_end: float | None
    latest: tuple[datetime, float | None, float] | None
    # Rows reach back to the sensor's first one (nothing old left before).
    from_first: bool


@dataclass
class _Costs:
    """Costs of one recalculated period, split at the setup."""

    pre: HourlyCosts | None  # [start, setup): lookback
    post: HourlyCosts  # [max(start, setup), end): stored quarter hours
    before: HourlyCosts | None  # [setup, start): for the sensor's value only
    pre5: HourlyCosts | None  # the same per 5 minutes, for short-term rows
    post5: HourlyCosts | None


def _values(
    value: Series, costs: HourlyCosts | None, *, complete: bool = True
) -> dict[datetime, float] | None:
    """A sensor's values from the costs of a part ({} for none). Not
    `complete`: missing prices do not matter (already checked hourly)."""
    if costs is None:
        return {}
    if not complete:
        costs = replace(costs, incomplete=set())
    return value(costs)


def _read_statistics(
    hass: HomeAssistant, ids: set[str], now: datetime
) -> tuple[dict[str, list[Any]], dict[str, list[Any]]]:
    """All hourly rows and the short-term rows of the last days."""
    hours = statistics_during_period(hass, EPOCH, None, ids, "hour", None, {"sum"})
    short = statistics_during_period(
        hass,
        period_start(now - SHORT_TERM_PERIOD, HOUR),
        None,
        ids,
        "5minute",
        None,
        {"state", "sum"},
    )
    return hours, short


def _merge_savings(
    parts: list[SolarHourly],
) -> dict[str, dict[datetime, tuple[float, float]] | None]:
    """Savings per tariff and hour of several periods (None: a gap in one)."""
    merged: dict[str, dict[datetime, tuple[float, float]] | None] = {}
    for savings, _, _ in parts:
        for key, hourly in savings.items():
            if key in merged and merged[key] is None:
                continue
            if hourly is None:
                merged[key] = None
                continue
            merged[key] = {**(merged.get(key) or {}), **hourly}
    return merged


async def async_recalculate(
    hass: HomeAssistant, entry: TarifwachtConfigEntry, first_day: date | None = None
) -> dict[str, Any]:
    """Recalculate the statistics of every sensor with a sum, from its first
    row (or from `first_day`, filling the time before the first row like the
    import) up to the last compiled hour, with the current tariffs.

    Raises StatisticsImportError, or SmardError if exchange prices are needed
    and cannot be loaded.
    """
    lock = _lock(hass, entry)
    if lock.locked():
        raise StatisticsImportError("busy")
    async with lock:
        result, from_first = await _async_recalculate(hass, entry, first_day)
    if from_first:
        async_clear_outdated(hass, entry.entry_id)
    return result


async def _async_recalculate(
    hass: HomeAssistant, entry: TarifwachtConfigEntry, first_day: date | None
) -> tuple[dict[str, Any], bool]:
    runtime = entry.runtime_data
    engine = runtime.engine
    if engine.started is None:
        raise StatisticsImportError("no_statistics_yet")
    started = engine.started
    setup_hour = hour_start(started)
    targets, solar_targets = _targets(hass, entry)
    ids = set(targets) | set(solar_targets)
    instance = get_instance(hass)
    # Rows still in the recorder's queue or session are written first.
    await instance.async_block_till_done()
    hours_read, short_read = await instance.async_add_executor_job(
        _read_statistics, hass, ids, dt_util.utcnow()
    )

    requested: datetime | None = None
    lookback: Lookback | None = None
    if first_day is not None:
        requested = dt_util.as_utc(dt_util.start_of_local_day(first_day))
        if requested < started and (
            lookback := await runtime.async_lookback(requested)
        ):
            # Not before the meter's first statistic (only base prices there).
            requested = max(
                requested, hour_start(min(lookback.consumption, default=started))
            )

    plans: dict[str, _Plan] = {}
    with_rows = False
    for entity_id in sorted(ids):
        old = [
            (dt_util.utc_from_timestamp(r["start"]), r["sum"])
            for r in hours_read.get(entity_id, [])
            if r.get("sum") is not None
        ]
        if not old:
            continue  # no statistics: left alone
        with_rows = True
        short = [
            (dt_util.utc_from_timestamp(r["start"]), r.get("state"), r["sum"])
            for r in short_read.get(entity_id, [])
            if r.get("sum") is not None
        ]
        first = old[0][0]
        whole = requested is None or requested <= first
        if whole:
            start, base = requested or first, 0.0
        else:
            start = requested
            base = next(total for moment, total in reversed(old) if moment < start)
        if start >= setup_hour:
            # From the setup on: what the sensor counted itself.
            start = max(start, started)
        end = hour_start(short[-1][0]) if short else old[-1][0] + HOUR
        if start >= end:
            continue
        keep = {moment for moment, _, _ in short if start <= moment < end}
        plans[entity_id] = _Plan(
            start=start,
            base=base,
            end=end,
            short=keep,
            short_from=max(start, hour_start(min(keep))) if keep else None,
            old_end=next(
                (total for moment, total in reversed(old) if moment < end), None
            ),
            latest=short[-1] if short else None,
            from_first=whole,
        )
    if not plans:
        raise StatisticsImportError(
            "nothing_to_recalculate" if with_rows else "no_statistics_yet"
        )
    low = min(plan.start for plan in plans.values())
    if low < started and lookback is None:
        lookback = await runtime.async_lookback(low)

    # Costs, computed in the executor (a year of quarter hours).
    quarters = list(engine.consumption.items())
    past_quarters = list(lookback.consumption.items()) if lookback else []
    live_tariffs = dict(engine.tariffs)
    past_tariffs = dict(lookback.tariffs) if lookback else live_tariffs
    tz = engine.tz

    def compute(start: datetime, end: datetime, short_from: datetime | None) -> _Costs:
        def costs(
            items: list[tuple[datetime, float]],
            tariffs: Mapping[str, Any],
            a: datetime,
            b: datetime,
            width: timedelta = HOUR,
        ) -> HourlyCosts:
            return period_costs(items, tariffs, a, b, tz, width)

        five = FIVE_MINUTES
        return _Costs(
            pre=costs(past_quarters, past_tariffs, start, min(started, end))
            if start < started
            else None,
            post=costs(quarters, live_tariffs, max(start, started), end),
            before=costs(quarters, live_tariffs, started, start)
            if start > started
            else None,
            pre5=costs(past_quarters, past_tariffs, short_from, started, five)
            if short_from is not None and short_from < started
            else None,
            post5=costs(quarters, live_tariffs, max(short_from, started), end, five)
            if short_from is not None
            else None,
        )

    groups: dict[tuple[datetime, datetime, datetime | None], _Costs] = {}
    for entity_id, plan in plans.items():
        key = (plan.start, plan.end, plan.short_from)
        if entity_id in targets and key not in groups:
            groups[key] = await hass.async_add_executor_job(compute, *key)

    # Saving by PV and battery: hourly, before the setup as the import
    # computes it, after it as the sensors do.
    used_smard = lookback.uses_smard if lookback else False
    implausible = list(lookback.implausible_hours) if lookback else []
    solar_plans = [p for e, p in plans.items() if e in solar_targets]
    savings: dict[str, dict[datetime, tuple[float, float]] | None] | None = None
    if solar_plans:
        solar_low = min(plan.start for plan in solar_plans)
        solar_end = max(plan.end for plan in solar_plans)
        parts: list[SolarHourly] = []
        if solar_low < setup_hour and (
            pre := await runtime.async_solar_hourly(solar_low, setup_hour, lookback)
        ):
            parts.append(pre)
        if (
            post := await runtime.async_solar_hourly(
                setup_hour, solar_end, None, smard=False
            )
        ) is not None:
            parts.append(post)
        if parts:
            savings = _merge_savings(parts)
            for _, smard, hours in parts:
                used_smard |= smard
                implausible += hours

    metadata = await instance.async_add_executor_job(
        lambda: get_metadata(hass, statistic_ids=set(plans))
    )
    result: dict[str, Any] = {
        "start": dt_util.as_local(low).isoformat(),
        "end": dt_util.as_local(max(p.end for p in plans.values())).isoformat(),
        "setup": dt_util.as_local(started).isoformat(),
        "sensors": {},
        "skipped": [],
    }
    from_first = True
    started_at = runtime.started_at
    for entity_id, plan in plans.items():
        if entity_id not in metadata:
            continue
        hourly: dict[datetime, float]
        five: dict[datetime, float] = {}
        if entity_id in targets:
            value, title = targets[entity_id]
            costs = groups[(plan.start, plan.end, plan.short_from)]
            pre = _values(value, costs.pre)
            post = _values(value, costs.post)
            if pre is None or post is None:
                if title not in result["skipped"]:
                    result["skipped"].append(title)
                continue
            hourly = add_values(pre, post)
            before = _values(value, costs.before, complete=False) or {}
            # sum - state from the setup on (see statistics_rows.py).
            offset = plan.base + sum(pre.values()) - sum(before.values())
            if plan.short_from is not None:
                five = add_values(
                    _values(value, costs.pre5, complete=False) or {},
                    _values(value, costs.post5, complete=False) or {},
                )
        else:
            if savings is None:
                continue
            key, index, title = solar_targets[entity_id]
            per_hour = savings.get(key)
            if per_hour is None:
                if title not in result["skipped"]:
                    result["skipped"].append(title)
                continue
            values = {hour: pair[index] for hour, pair in per_hour.items()}
            hourly = place_savings(values, setup_hour, HOUR)
            five = place_savings(values, setup_hour, FIVE_MINUTES)
            first_hour = period_start(plan.start, HOUR)
            offset = (
                plan.base
                + total_between(hourly, first_hour, started)
                - total_between(hourly, started, plan.start)
            )
        rows = build_rows(
            hourly,
            start=plan.start,
            end=plan.end,
            width=HOUR,
            base=plan.base,
            offset=offset,
            started=started,
        )
        short_rows: list[Row] = []
        if plan.short_from is not None:
            short_rows = build_rows(
                five,
                start=plan.short_from,
                end=plan.end,
                width=FIVE_MINUTES,
                base=plan.base
                + total_between(
                    hourly,
                    period_start(plan.start, HOUR),
                    period_start(plan.short_from, HOUR),
                ),
                offset=offset,
                started=started,
                keep=plan.short,
            )
        new_end = rows[-1][2] if rows else plan.base
        # The rows from `end` on continue from the new ones: shifted by the
        # change of the sum at `end`, so their own changes stay. If the
        # entry was reloaded since (a tariff change: the jump of the sensor's
        # value may be in them), by the offset instead, so that
        # sum - state of the latest row equals the new offset.
        delta = 0.0
        latest = plan.latest
        if latest is not None:
            reloaded = started_at is not None and started_at >= plan.end
            if plan.old_end is not None and not reloaded:
                delta = new_end - plan.old_end
            elif latest[1] is not None:
                delta = offset - (latest[2] - latest[1])
            elif plan.old_end is not None:
                delta = new_end - plan.old_end
        meta = metadata[entity_id][1]
        async_import_statistics(
            hass,
            meta,
            [
                StatisticData(start=t, state=state, sum=total)
                for t, state, total in rows
            ],
        )
        if short_rows:
            instance.async_import_statistics(
                meta,
                [
                    StatisticData(start=t, state=state, sum=total)
                    for t, state, total in short_rows
                ],
                StatisticsShortTerm,
            )
        if latest is not None and delta:
            instance.async_adjust_statistics(
                entity_id, plan.end, delta, meta["unit_of_measurement"] or ""
            )
        from_first &= plan.from_first
        result["sensors"][entity_id] = {
            "from": dt_util.as_local(plan.start).isoformat(),
            "until": dt_util.as_local(plan.end).isoformat(),
            "hours": len(rows),
            "short_term": len(short_rows),
            "change": None
            if plan.old_end is None
            else round(new_end - plan.old_end, 4),
        }
    # Written before the next press reads them.
    await instance.async_block_till_done()
    if lookback is not None:
        result["hours_without_energy"] = lookback.hours_without_energy
    if used_smard:
        result["exchange_prices"] = ATTRIBUTION
    if summary := implausible_summary(implausible):
        result["hours_implausible"] = summary
    if not result["sensors"]:
        raise StatisticsImportError(
            "prices_missing" if result["skipped"] else "nothing_to_recalculate"
        )
    return result, from_first and not result["skipped"]
