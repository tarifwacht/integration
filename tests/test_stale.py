"""Which statistics a change of the subentries makes stale, and from when."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from custom_components.tarifwacht.const import BERLIN
from custom_components.tarifwacht.engine import Engine
from custom_components.tarifwacht.meter import MeterTracker
from custom_components.tarifwacht.outdated import merge_stale, stale_statistics
from custom_components.tarifwacht.statistics_import import _changed, _clear_stale
from custom_components.tarifwacht.tariff_config import stale_since

FIXED: dict[str, Any] = {
    "key": "fixed",
    "kind": "fixed",
    "price": 30.0,
    "base_price": 10.0,
    "base_period": "month",
    "current": True,
}
DYNAMIC: dict[str, Any] = {
    "key": "dynamic",
    "kind": "dynamic_total",
    "price_entity": "sensor.price",
    "base_price": 0.0,
    "base_period": "month",
    "current": False,
}
SOLAR: dict[str, Any] = {"feed_in_entity": "sensor.feed_in", "pv_entity": "sensor.pv"}
# 1 February 2027 and 1 March 2027, local midnight.
FEB = datetime(2027, 1, 31, 23, tzinfo=UTC)
MAR = datetime(2027, 2, 28, 23, tzinfo=UTC)
CHANGE = {"from": "2027-03-01", "price": 32.0}


def subentries(fixed: dict[str, Any], dynamic: dict[str, Any] = DYNAMIC, **more: Any):
    return {"F": fixed, "D": dynamic, **more}


def test_stale_since() -> None:
    assert stale_since(FIXED, dict(FIXED)) == (False, None)
    # A price change from a date: from its date (added, altered or removed).
    with_change = {**FIXED, "changes": [CHANGE]}
    assert stale_since(FIXED, with_change) == (True, MAR)
    feb = {"from": "2027-02-01", "price": 31.0}
    assert stale_since(with_change, {**FIXED, "changes": [feb, CHANGE]}) == (True, FEB)
    assert stale_since(with_change, FIXED) == (True, MAR)
    # The bonus: from its date, old or new.
    bonus = {**FIXED, "bonus": 250.0, "bonus_date": "2027-03-01"}
    assert stale_since(FIXED, bonus) == (True, MAR)
    moved = {**bonus, "bonus_date": "2027-02-01"}
    assert stale_since(bonus, moved) == (True, FEB)
    # Values from the start: everything.
    assert stale_since(FIXED, {**FIXED, "base_price": 12.0}) == (True, None)
    assert stale_since(FIXED, {**FIXED, "modul3": {"active": True}}) == (True, None)
    # The current switch alone does not change the tariff's own costs.
    assert stale_since(FIXED, {**FIXED, "current": False}) == (False, None)


def test_a_price_change_of_another_tariff() -> None:
    old = subentries(FIXED)
    new = subentries(FIXED, {**DYNAMIC, "changes": [CHANGE]})
    assert stale_statistics(old, new) == {
        f"dynamic_{name}": MAR
        for name in (
            "consumption_cost",
            "cost",
            "difference",
            "saving_pv",
            "saving_battery",
        )
    }


def test_the_current_tariff_changes_all_differences() -> None:
    stale = stale_statistics(subentries(FIXED), subentries({**FIXED, "price": 31.0}))
    assert stale["fixed_cost"] is None
    assert stale["dynamic_difference"] is None
    assert "energy" not in stale and "dynamic_cost" not in stale
    # Another tariff becomes the current one: differences only.
    swapped = subentries({**FIXED, "current": False}, {**DYNAMIC, "current": True})
    assert stale_statistics(subentries(FIXED), swapped) == {
        "fixed_difference": None,
        "dynamic_difference": None,
    }


def test_new_tariff_and_solar_change() -> None:
    added = {**DYNAMIC, "key": "neu"}
    stale = stale_statistics(subentries(FIXED), {**subentries(FIXED), "N": added})
    assert set(stale) == {
        f"neu_{name}"
        for name in (
            "consumption_cost",
            "cost",
            "difference",
            "saving_pv",
            "saving_battery",
        )
    }
    old = subentries(FIXED, S=SOLAR)
    new = subentries(FIXED, S={**SOLAR, "feed_in_rate": 8.0})
    assert stale_statistics(old, new) == {
        f"{key}_{name}": None
        for key in ("fixed", "dynamic")
        for name in ("saving_pv", "saving_battery")
    }
    # Only the title changed: nothing.
    assert stale_statistics(old, subentries(FIXED, S=dict(SOLAR))) == {}


def test_merge_stale_keeps_the_earliest() -> None:
    stale: dict[str, datetime | None] = {"a": MAR, "b": None}
    merge_stale(stale, {"a": FEB, "b": FEB, "c": MAR})
    assert stale == {"a": FEB, "b": None, "c": MAR}
    merge_stale(stale, {"a": None})
    assert stale["a"] is None


def test_clear_stale_only_what_was_covered() -> None:
    engine = Engine(meter=MeterTracker(max_power_kw=100), tariffs={}, tz=BERLIN)
    engine.stale_statistics = {"a": FEB, "b": FEB, "c": None, "d": MAR}
    # a from FEB on, b only from MAR on, c from a later moment (not all), d none.
    assert not _clear_stale(engine, {"a": FEB, "b": MAR, "c": FEB}, {"d"})
    assert engine.stale_statistics == {"b": FEB, "c": None}
    assert _clear_stale(engine, {"b": None, "c": None}, ())
    assert engine.stale_statistics == {}
    # Restored after a restart.
    engine.stale_statistics = {"a": FEB, "c": None}
    restored = Engine(meter=MeterTracker(max_power_kw=100), tariffs={}, tz=BERLIN)
    restored.restore(engine.as_dict())
    assert restored.stale_statistics == {"a": FEB, "c": None}


def test_unchanged_rows_are_not_written() -> None:
    row = (FEB, 1.0, 5.0)
    assert not _changed(row, (1.0, 5.0))
    assert not _changed(row, (1.0 + 1e-9, 5.0 - 1e-9))
    assert _changed(row, (1.0, 5.01))
    assert _changed(row, (None, 5.0))
    assert _changed(row, None)
