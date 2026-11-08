"""Repair issue: past statistics still show a tariff's old prices.

Every tariff applies to the whole period, so a changed tariff (prices, a
price change from a date, Modul 3, the current tariff) or a changed PV and
battery subentry gives the sensors new sums at once - but the long-term
statistics of past hours keep the old values. This issue names the button
"Recalculate statistics"; a recalculation from the first row removes it.

The issue id ends with the entry id (not `<entry>_...` like the runtime's
own issues, which the runtime removes when they no longer apply).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

ISSUE = "statistics_outdated"
# Only when Home Assistant has compiled statistics since the setup.
MIN_AGE = timedelta(hours=1)


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
