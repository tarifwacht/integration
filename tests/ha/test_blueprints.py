"""The blueprint as a real automation: monthly summary from the compare action."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.tarifwacht.const import DOMAIN

BLUEPRINT = (
    Path(__file__).parent.parent.parent
    / "blueprints"
    / "automation"
    / "tarifwacht"
    / "monatsuebersicht.yaml"
)
ENTRY = "01TESTENTRY0000000000000000"
# Shape of the compare response; invented values.
RESPONSE = {
    "energy_kwh": 312.5,
    "cheapest": "Festpreis",
    "tariffs": [
        {
            "tariff": "Festpreis",
            "cost": 100.0,
            "difference_to_current": 0,
            "energy_without_price_kwh": 0,
        },
        {
            "tariff": "Börsentarif",
            "cost": 104.5,
            "difference_to_current": 4.5,
            "energy_without_price_kwh": 0,
        },
        {
            "tariff": "Dynamisch",
            "cost": 7.25,
            "difference_to_current": None,
            "energy_without_price_kwh": 290.0,
        },
    ],
}


@pytest.mark.freeze_time(datetime(2026, 11, 1, 6, 59, tzinfo=UTC))
async def test_monthly_summary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    compare = async_mock_service(
        hass,
        DOMAIN,
        "compare",
        response=RESPONSE,
        supports_response=SupportsResponse.ONLY,
    )
    notify = async_mock_service(hass, "test", "notify")
    blueprint = Blueprint(
        load_yaml(BLUEPRINT),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    config = BlueprintInputs(
        blueprint,
        {
            "use_blueprint": {
                "path": BLUEPRINT.name,
                "input": {
                    "meter": ENTRY,
                    "notify_actions": [
                        {
                            "action": "test.notify",
                            "data": {
                                "title": "{{ title }}",
                                "message": "{{ message }}",
                            },
                        }
                    ],
                },
            }
        },
    ).async_substitute()
    config.pop("use_blueprint", None)
    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()

    # 1 November, 08:00 CET: the summary of October.
    freezer.move_to(datetime(2026, 11, 1, 7, 0, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(compare) == 1
    assert compare[0].data == {
        "config_entry": ENTRY,
        "start": "2026-10-01 00:00:00",
        "end": "2026-11-01 00:00:00",
    }
    assert len(notify) == 1
    assert notify[0].data["title"] == "Strom im Oktober 2026"
    assert notify[0].data["message"] == (
        "Strombezug: 312,5 kWh\n"
        "Festpreis: 100,00 €\n"
        "Börsentarif: 104,50 € (+4,50 € gegenüber dem aktuellen Tarif)\n"
        "Dynamisch: 7,25 € (Preise fehlen)\n"
        "Günstigster Tarif: Festpreis"
    )

    # Any other day: nothing.
    freezer.move_to(datetime(2026, 11, 2, 7, 0, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert (len(compare), len(notify)) == (1, 1)

    # Detach the time trigger, or its next timer outlives the test.
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": "all"}, blocking=True
    )
