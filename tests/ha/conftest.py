"""Fixtures for Home Assistant tests.

pytest-homeassistant-custom-component needs Linux (fcntl). Without it (local
Windows development) these tests are not collected; CI runs them.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from custom_components.tarifwacht.const import (
    CONF_DYNAMIC_BASE,
    CONF_DYNAMIC_PRICE,
    CONF_FIXED_BASE,
    CONF_FIXED_PRICE,
    CONF_METER,
    CONF_NAME,
)
from tests.conftest import load_fixture

METER = "sensor.grid_import"
PRICE = "sensor.epex_spot_data_total_price"

METER_ATTRIBUTES = {
    "unit_of_measurement": "Wh",
    "state_class": "total_increasing",
    "device_class": "energy",
}


def price_attributes() -> dict[str, Any]:
    """The recorded EPEX Spot forecast (€/kWh), stands in for a total price."""
    fixture = load_fixture("epex_spot_2026-10-25.json")
    return {
        **fixture["attributes"],
        "data": fixture["history_supplement"] + fixture["attributes"]["data"],
    }


def entry_data(**changes: Any) -> dict[str, Any]:
    """30 ct/kWh fixed with 31 €/month base, dynamic without base price."""
    return {
        CONF_NAME: "Haus",
        CONF_METER: METER,
        CONF_FIXED_PRICE: 30.0,
        CONF_FIXED_BASE: 31.0,
        CONF_DYNAMIC_PRICE: PRICE,
        CONF_DYNAMIC_BASE: 0.0,
        **changes,
    }


if importlib.util.find_spec("pytest_homeassistant_custom_component") is None:
    collect_ignore_glob = ["test_*.py"]
else:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
        """Allow loading custom_components/tarifwacht in every test."""
