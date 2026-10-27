"""Action tarifwacht.import_statistics: the sensors' history before their statistics.

The sensors only have long-term statistics since they exist. This fills the
hours before each sensor's first statistic: before the setup from the lookback
(hourly meter statistics, prices as in the compare action), after it from the
stored quarter hours (a tariff added later). The later sums are shifted by the
imported total so the series stays continuous - the same adjustment Home
Assistant's own "fix statistics" uses (pattern of Einspeisewacht).

A tariff without the price of a quarter hour in the period is skipped as a
whole: no gaps in the permanent statistics. A second call finds nothing left.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from itertools import chain
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .lookback import HOUR, HourlyCosts, hour_start, hourly_costs
from .smard import ATTRIBUTION

if TYPE_CHECKING:
    from . import TarifwachtConfigEntry


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


async def async_import_history(
    hass: HomeAssistant, entry: TarifwachtConfigEntry, first_day: date
) -> dict[str, Any]:
    """Import hourly statistics from `first_day` until each sensor's first one.

    Raises StatisticsImportError, or SmardError if exchange prices are needed
    and cannot be loaded.
    """
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
    registry = er.async_get(hass)
    targets: dict[str, tuple[Series, str | None]] = {}
    for unique_id, target in _series(entry).items():
        if entity_id := registry.async_get_entity_id("sensor", DOMAIN, unique_id):
            targets[entity_id] = target

    instance = get_instance(hass)
    existing = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        None,
        set(targets),
        "hour",
        None,
        {"sum"},
    )
    firsts = {
        entity_id: dt_util.utc_from_timestamp(rows[0]["start"])
        for entity_id in targets
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
        if entity_id not in metadata:
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
        rows: list[StatisticData] = []
        total = 0.0
        for hour in sorted(values):
            total += values[hour]
            rows.append(StatisticData(start=hour, state=total, sum=total))
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
    if lookback.uses_smard:
        result["exchange_prices"] = ATTRIBUTION
    if not result["sensors"]:
        raise StatisticsImportError(
            "prices_missing"
            if result["skipped"] and not done_before
            else "nothing_to_import"
        )
    return result
