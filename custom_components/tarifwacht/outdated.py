"""Repair issue: past statistics still show a tariff's old prices.

Every tariff applies to the whole period, so a changed tariff (prices, a
price change from a date, Modul 3, the current tariff) or a changed PV and
battery subentry gives the sensors new sums at once - but the long-term
statistics of past hours keep the old values. This issue names the button
"Recalculate statistics"; a recalculation from the first row removes it.

The issue id ends with the entry id (not `<entry>_...` like the runtime's
own issues, which the runtime removes when they no longer apply).

What a change makes stale is remembered per sensor (`stale_statistics`,
kept in the runtime's store): the button then rewrites only those sensors,
from the earliest moment that changed (statistics_import.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import CONF_CURRENT, CONF_KIND, DOMAIN
from .tariff_config import stale_since, tariff_key

ISSUE = "statistics_outdated"
# Only when Home Assistant has compiled statistics since the setup.
MIN_AGE = timedelta(hours=1)


# Sensors of a tariff with a sum (unique id `<entry>_<tariff key>_<name>`).
TARIFF_SERIES = (
    "consumption_cost",
    "cost",
    "difference",
    "saving_pv",
    "saving_battery",
)
SAVINGS = ("saving_pv", "saving_battery")

# Unique id suffix -> first moment whose statistics are stale (None: all).
Stale = dict[str, datetime | None]


def merge_stale(into: Stale, new: Mapping[str, datetime | None]) -> None:
    """Add `new` to `into`: the earlier moment wins, None (all) over both."""
    for suffix, since in new.items():
        if suffix not in into:
            into[suffix] = since
        elif into[suffix] is not None:
            into[suffix] = None if since is None else min(into[suffix], since)


def stale_statistics(
    old: Mapping[str, Mapping[str, Any]], new: Mapping[str, Mapping[str, Any]]
) -> Stale:
    """The sensors (unique id suffixes) whose past statistics a change of the
    subentries alters, each from its earliest moment.

    A tariff's own sensors when its costs change (a price change or the
    bonus from their date, anything else from the start); the differences
    of every tariff when the current tariff's costs change or another
    tariff becomes the current one; the savings of every tariff when PV and
    battery change. "Grid purchase" never: it does not depend on tariffs.
    """
    stale: Stale = {}

    def tariffs(subentries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        return {sid: data for sid, data in subentries.items() if CONF_KIND in data}

    old_tariffs, new_tariffs = tariffs(old), tariffs(new)
    keys = {
        sid: tariff_key(sid, data)
        for sid, data in {**old_tariffs, **new_tariffs}.items()
    }

    def current(found: Mapping[str, Mapping[str, Any]]) -> str | None:
        return next((keys[s] for s, d in found.items() if d.get(CONF_CURRENT)), None)

    current_key = current(new_tariffs)
    names = {keys[sid] for sid in new_tariffs}

    def mark(names_of: Any, since: datetime | None) -> None:
        merge_stale(stale, dict.fromkeys(names_of, since))

    if current(old_tariffs) != current_key:
        mark((f"{key}_difference" for key in names), None)
    for sid, data in new_tariffs.items():
        if sid in old_tariffs:
            changed, since = stale_since(old_tariffs[sid], data)
        else:
            changed, since = True, None  # a new tariff: no statistics yet
        if not changed:
            continue
        key = keys[sid]
        mark((f"{key}_{name}" for name in TARIFF_SERIES), since)
        if key == current_key:
            mark((f"{other}_difference" for other in names), since)
    solar_old = {s: dict(d) for s, d in old.items() if s not in old_tariffs}
    solar_new = {s: dict(d) for s, d in new.items() if s not in new_tariffs}
    if solar_old != solar_new:
        mark((f"{key}_{name}" for key in names for name in SAVINGS), None)
    return stale


def issue_id(entry_id: str) -> str:
    return f"{ISSUE}_{entry_id}"


def past_changed(
    old: Mapping[str, Mapping[str, Any]], new: Mapping[str, Mapping[str, Any]]
) -> bool:
    """Whether a subentry that stays changed its data (not only its title).

    A new subentry has no statistics yet; a removed one takes its sensors
    with it.
    """
    return any(key in new and dict(new[key]) != dict(data) for key, data in old.items())


@callback
def async_mark_outdated(
    hass: HomeAssistant,
    entry: ConfigEntry,
    old: Mapping[str, Mapping[str, Any]],
    started: datetime | None,
    now: datetime,
) -> None:
    """Show the issue if a change of the subentries alters past hours."""
    new = {key: subentry.data for key, subentry in entry.subentries.items()}
    if started is None or now - started < MIN_AGE or not past_changed(old, new):
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(entry.entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE,
        translation_placeholders={"name": entry.title},
    )


@callback
def async_clear_outdated(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, issue_id(entry_id))
