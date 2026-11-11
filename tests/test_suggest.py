"""Suggestions for the setup forms (no Home Assistant instance)."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.tarifwacht.const import (
    KIND_DYNAMIC_MARKET,
    KIND_DYNAMIC_TOTAL,
    KIND_FIXED,
)
from custom_components.tarifwacht.suggest import epex_price_sensor, grid_import_stats


def entity(
    entity_id: str, unique_id: str, platform: str = "epex_spot", **extra
) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=unique_id,
        platform=platform,
        domain=entity_id.split(".")[0],
        disabled_by=extra.get("disabled_by"),
    )


# EPEX Spot's unique ids: f"{source} {key}" (ha_epex_spot 4.1.0, see suggest.py).
EPEX = [
    entity(
        "sensor.epex_spot_data_average_price", "epex_spot SMARD.de DE-LU Average Price"
    ),
    entity(
        "sensor.epex_spot_data_market_price", "epex_spot SMARD.de DE-LU MarketPrice"
    ),
    entity("sensor.epex_spot_data_total_price", "epex_spot SMARD.de DE-LU Total Price"),
    entity(
        "sensor.epex_spot_data_lowest_price", "epex_spot SMARD.de DE-LU Lowest Price"
    ),
]


def test_epex_market_and_total_price() -> None:
    assert (
        epex_price_sensor(EPEX, KIND_DYNAMIC_MARKET)
        == "sensor.epex_spot_data_market_price"
    )
    assert (
        epex_price_sensor(EPEX, KIND_DYNAMIC_TOTAL)
        == "sensor.epex_spot_data_total_price"
    )
    assert epex_price_sensor(EPEX, KIND_FIXED) is None


def test_epex_only_its_own_enabled_sensors() -> None:
    others = [
        entity("sensor.other_market", "x MarketPrice", platform="other"),
        entity("sensor.epex_disabled", "epex_spot A MarketPrice", disabled_by="user"),
    ]
    assert epex_price_sensor(others, KIND_DYNAMIC_MARKET) is None
    # Several EPEX Spot entries: the first by entity id.
    two = [
        entity("sensor.epex_b_market_price", "epex_spot B MarketPrice"),
        entity("sensor.epex_a_market_price", "epex_spot A MarketPrice"),
    ]
    assert epex_price_sensor(two, KIND_DYNAMIC_MARKET) == "sensor.epex_a_market_price"


def test_grid_import_unified_format() -> None:
    prefs = {
        "energy_sources": [
            {"type": "solar", "stat_energy_from": "sensor.pv"},
            {
                "type": "grid",
                "stat_energy_from": "sensor.import_a",
                "stat_energy_to": "sensor.export",
            },
            {
                "type": "grid",
                "stat_energy_from": None,
                "stat_energy_to": "sensor.export_b",
            },
            {"type": "grid", "stat_energy_from": "sensor.import_b"},
        ]
    }
    assert grid_import_stats(prefs) == ["sensor.import_a", "sensor.import_b"]


def test_grid_import_legacy_format() -> None:
    prefs = {
        "energy_sources": [
            {
                "type": "grid",
                "flow_from": [
                    {"stat_energy_from": "sensor.high_tariff"},
                    {"stat_energy_from": "sensor.low_tariff"},
                    {"stat_energy_from": "sensor.high_tariff"},
                ],
                "flow_to": [{"stat_energy_to": "sensor.export"}],
            }
        ]
    }
    assert grid_import_stats(prefs) == ["sensor.high_tariff", "sensor.low_tariff"]


def test_grid_import_without_preferences() -> None:
    assert grid_import_stats(None) == []
    assert grid_import_stats({}) == []
    assert (
        grid_import_stats({"energy_sources": [{"type": "grid", "flow_from": None}]})
        == []
    )
