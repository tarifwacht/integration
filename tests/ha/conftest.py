"""Fixtures for Home Assistant tests.

pytest-homeassistant-custom-component needs Linux (fcntl). Without it (local
Windows development) these tests are not collected; CI runs them.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from custom_components.tarifwacht.const import (
    CONF_BASE_PERIOD,
    CONF_BASE_PRICE,
    CONF_CURRENT,
    CONF_DYNAMIC_BASE,
    CONF_DYNAMIC_PRICE,
    CONF_FIXED_BASE,
    CONF_FIXED_PRICE,
    CONF_KEY,
    CONF_KIND,
    CONF_METER,
    CONF_NAME,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    KIND_DYNAMIC_TOTAL,
    KIND_FIXED,
    SUBENTRY_TARIFF,
)
from tests.conftest import load_fixture

METER = "sensor.grid_import"
PRICE = "sensor.epex_spot_data_total_price"
FIXED_SUBENTRY = "01FIXEDSUBENTRY000000000000"
DYNAMIC_SUBENTRY = "01DYNAMICSUBENTRY0000000000"

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
    return {CONF_NAME: "Haus", CONF_METER: METER, **changes}


def fixed_tariff(**changes: Any) -> dict[str, Any]:
    """30 ct/kWh with 31 €/month base: the current tariff."""
    return {
        CONF_KEY: "fixed",
        CONF_KIND: KIND_FIXED,
        CONF_PRICE: 30.0,
        CONF_BASE_PRICE: 31.0,
        CONF_BASE_PERIOD: "month",
        CONF_CURRENT: True,
        **changes,
    }


def dynamic_tariff(**changes: Any) -> dict[str, Any]:
    """The total-price sensor without base price."""
    return {
        CONF_KEY: "dynamic",
        CONF_KIND: KIND_DYNAMIC_TOTAL,
        CONF_PRICE_ENTITY: PRICE,
        CONF_BASE_PRICE: 0.0,
        CONF_BASE_PERIOD: "month",
        CONF_CURRENT: False,
        **changes,
    }


def subentries_data() -> list[dict[str, Any]]:
    return [
        {
            "data": fixed_tariff(),
            "subentry_id": FIXED_SUBENTRY,
            "subentry_type": SUBENTRY_TARIFF,
            "title": "Fixed price",
            "unique_id": None,
        },
        {
            "data": dynamic_tariff(),
            "subentry_id": DYNAMIC_SUBENTRY,
            "subentry_type": SUBENTRY_TARIFF,
            "title": "Dynamic",
            "unique_id": None,
        },
    ]


def legacy_entry_data() -> dict[str, Any]:
    """Entry data of 0.1.0b1 (version 1): both tariffs in the entry."""
    return {
        CONF_NAME: "Haus",
        CONF_METER: METER,
        CONF_FIXED_PRICE: 30.0,
        CONF_FIXED_BASE: 31.0,
        CONF_DYNAMIC_PRICE: PRICE,
        CONF_DYNAMIC_BASE: 0.0,
    }


if importlib.util.find_spec("pytest_homeassistant_custom_component") is None:
    collect_ignore_glob = ["test_*.py"]
else:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.tarifwacht.const import DOMAIN

    def mock_entry() -> MockConfigEntry:
        """A version-2 entry with the fixed and the dynamic tariff."""
        return MockConfigEntry(
            domain=DOMAIN,
            unique_id=METER,
            title="Haus",
            data=entry_data(),
            version=2,
            subentries_data=subentries_data(),
        )

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
        """Allow loading custom_components/tarifwacht in every test."""


def nest_sections(result: dict[str, Any], user_input: dict[str, Any]) -> dict[str, Any]:
    """The input as the form takes it: flat fields that belong to a section
    of the shown form moved into it (the tests write them flat). A section
    given explicitly stays as it is."""
    from homeassistant.data_entry_flow import section

    nested = dict(user_input)
    schema = result.get("data_schema")
    if schema is None:
        return nested
    for key, value in schema.schema.items():
        name = str(key)
        if not isinstance(value, section) or name in user_input:
            continue
        inner = {str(k) for k in value.schema.schema}
        moved = {k: nested.pop(k) for k in list(nested) if k in inner}
        if moved:
            nested[name] = moved
    return nested


def shown_values(result: dict[str, Any]) -> dict[str, Any]:
    """The suggested values of a form, those inside sections included."""
    from homeassistant.data_entry_flow import section

    values: dict[str, Any] = {}
    for key, value in result["data_schema"].schema.items():
        if isinstance(value, section):
            for inner in value.schema.schema:
                values[str(inner)] = (inner.description or {}).get("suggested_value")
        else:
            values[str(key)] = (getattr(key, "description", None) or {}).get(
                "suggested_value"
            )
    return values
