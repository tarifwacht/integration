"""The blueprint as a real automation: monthly summary from the compare action."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.tarifwacht.const import CONF_METER, CONF_NAME, DOMAIN

from .conftest import (
    METER_ATTRIBUTES,
    PRICE,
    entry_data,
    price_attributes,
    subentries_data,
)

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
GERMAN = (
    "Strombezug: 312,5 kWh\n"
    "Festpreis: 100,00 €\n"
    "Börsentarif: 104,50 € (+4,50 € gegenüber dem aktuellen Tarif)\n"
    "Dynamisch: 7,25 € (Preise fehlen)\n"
    "Günstigster Tarif: Festpreis"
)
ENGLISH = (
    "Grid purchase: 312.5 kWh\n"
    "Festpreis: 100.00 €\n"
    "Börsentarif: 104.50 € (+4.50 € compared with the current tariff)\n"
    "Dynamisch: 7.25 € (prices missing)\n"
    "Cheapest tariff: Festpreis"
)
# The actions of an automation set up before the blueprint was bilingual.
OWN_ACTION = [
    {
        "action": "test.notify",
        "data": {"title": "{{ title }}", "message": "{{ message }}"},
    }
]


def load_blueprint() -> Blueprint:
    return Blueprint(
        load_yaml(BLUEPRINT),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )


def test_inputs_bilingual_and_compatible() -> None:
    """Every input named in German and English; the inputs of before keep
    their keys, nothing new is required; the actions sit in a collapsed
    section."""
    blueprint = load_blueprint()
    metadata = blueprint.data["blueprint"]
    assert " / " in metadata["name"]
    assert "\n\n" in metadata["description"]
    inputs = blueprint.inputs
    assert {"meter", "time", "notify_actions"} <= set(inputs)
    assert {"notify_device", "language"} <= set(inputs)
    for key, spec in inputs.items():
        assert " / " in spec["name"], key
        if key != "meter":
            assert "default" in spec, key
    assert inputs["notify_device"]["default"] == ""
    assert inputs["language"]["default"] == "de"
    section = metadata["input"]["more"]
    assert section["collapsed"] is True
    assert set(section["input"]) == {"notify_actions"}


async def setup_automation(
    hass: HomeAssistant, inputs: dict[str, Any]
) -> tuple[list[ServiceCall], list[ServiceCall]]:
    """The blueprint as an automation; the mocked compare and test.notify."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    compare = async_mock_service(
        hass,
        DOMAIN,
        "compare",
        response=RESPONSE,
        supports_response=SupportsResponse.ONLY,
    )
    notify = async_mock_service(hass, "test", "notify")
    config = BlueprintInputs(
        load_blueprint(),
        {"use_blueprint": {"path": BLUEPRINT.name, "input": inputs}},
    ).async_substitute()
    config.pop("use_blueprint", None)
    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    return compare, notify


async def set_up_meters(hass: HomeAssistant, *names: str) -> list[MockConfigEntry]:
    """Real Tarifwacht entries, one per meter, each with two tariffs
    (subentries with a device each). Set up before the automation, so the
    mocked compare replaces the real one."""
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    entries = []
    for number, name in enumerate(names, 1):
        meter = f"sensor.grid_import_{number}"
        hass.states.async_set(meter, "1000000", METER_ATTRIBUTES)
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=meter,
            title=name,
            data=entry_data(**{CONF_NAME: name, CONF_METER: meter}),
            version=2,
            subentries_data=[
                {**s, "subentry_id": f"{s['subentry_id'][:-1]}{number}"}
                for s in subentries_data()
            ],
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entries.append(entry)
    return entries


async def first_of_month(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    # 1 November, 08:00 CET: the summary of October.
    freezer.move_to(datetime(2026, 11, 1, 7, 0, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def turn_off(hass: HomeAssistant) -> None:
    # Detach the time trigger, or its next timer outlives the test.
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": "all"}, blocking=True
    )


@pytest.mark.freeze_time(datetime(2026, 11, 1, 6, 59, tzinfo=UTC))
async def test_monthly_summary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An automation with the inputs of before: German, own action. One
    meter: the title without the entry's name, although its two tariffs
    bring their own devices."""
    (entry,) = await set_up_meters(hass, "Haus")
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) > 1
    compare, notify = await setup_automation(
        hass, {"meter": entry.entry_id, "notify_actions": OWN_ACTION}
    )
    await first_of_month(hass, freezer)
    assert len(compare) == 1
    assert compare[0].data == {
        "config_entry": entry.entry_id,
        "start": "2026-10-01 00:00:00",
        "end": "2026-11-01 00:00:00",
    }
    assert len(notify) == 1
    assert notify[0].data["title"] == "Tarifwacht: Strom im Oktober 2026"
    assert notify[0].data["message"] == GERMAN

    # Any other day: nothing.
    freezer.move_to(datetime(2026, 11, 2, 7, 0, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert (len(compare), len(notify)) == (1, 1)
    await turn_off(hass)


@pytest.mark.freeze_time(datetime(2026, 11, 1, 6, 59, tzinfo=UTC))
async def test_monthly_summary_names_the_entry_with_two_meters(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Two meters (two entries): the title names the chosen one."""
    _, flat = await set_up_meters(hass, "Haus", "Wohnung")
    _, notify = await setup_automation(
        hass, {"meter": flat.entry_id, "notify_actions": OWN_ACTION}
    )
    await first_of_month(hass, freezer)
    assert [c.data["title"] for c in notify] == [
        "Tarifwacht · Wohnung: Strom im Oktober 2026"
    ]
    await turn_off(hass)


@pytest.mark.freeze_time(datetime(2026, 11, 1, 6, 59, tzinfo=UTC))
async def test_monthly_summary_english_to_the_phone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """English, the default notification in Home Assistant and the phone;
    without a loaded entry the title says just Tarifwacht."""
    phone_entry = MockConfigEntry(domain="mobile_app")
    phone_entry.add_to_hass(hass)
    phone = dr.async_get(hass).async_get_or_create(
        config_entry_id=phone_entry.entry_id,
        identifiers={("mobile_app", "phone-1")},
        name="Andys Handy",
    )
    _, notify = await setup_automation(
        hass, {"meter": ENTRY, "notify_device": phone.id, "language": "en"}
    )
    bell = async_mock_service(hass, "persistent_notification", "create")
    to_phone = async_mock_service(hass, "notify", "mobile_app_andys_handy")
    await first_of_month(hass, freezer)
    title = "Tarifwacht: Electricity in October 2026"
    assert [c.data for c in bell] == [{"title": title, "message": ENGLISH}]
    assert [c.data for c in to_phone] == [{"title": title, "message": ENGLISH}]
    assert not notify
    await turn_off(hass)
