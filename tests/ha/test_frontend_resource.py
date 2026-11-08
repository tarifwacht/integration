"""Tests for registering the Tarifwacht card as a dashboard resource."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.lovelace import LovelaceData
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.dashboard import LovelaceStorage
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifwacht.cards import CARD_RESOURCE_URL as CARD_URL
from custom_components.tarifwacht.const import DOMAIN
from custom_components.tarifwacht.frontend_resource import (
    async_register_card,
    async_unregister_card,
)

from .conftest import (
    METER,
    METER_ATTRIBUTES,
    PRICE,
    entry_data,
    price_attributes,
    subentries_data,
)

MODULE = "custom_components.tarifwacht.frontend_resource"
OLD_URL = "/tarifwacht/tarifwacht-card.js?v=0.1.4"
OTHER = {"id": "other", "type": "module", "url": "/hacsfiles/button-card.js"}


def stored(hass_storage: dict[str, Any], *items: dict[str, Any]) -> None:
    """Dashboard resources as found in .storage/lovelace_resources."""
    hass_storage["lovelace_resources"] = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {"items": list(items)},
    }


def use_resources(
    hass: HomeAssistant, resources: ResourceStorageCollection | ResourceYAMLCollection
) -> None:
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode="yaml"
        if isinstance(resources, ResourceYAMLCollection)
        else "storage",
        dashboards={},
        resources=resources,
        yaml_dashboards={},
    )


@pytest.fixture
def resources(hass: HomeAssistant) -> ResourceStorageCollection:
    """Resources in storage mode, loaded lazily like in Home Assistant."""
    collection = ResourceStorageCollection(hass, LovelaceStorage(hass, None))
    use_resources(hass, collection)
    return collection


@pytest.fixture
def extra_js(hass: HomeAssistant) -> Iterator[tuple[Mock, Mock]]:
    hass.config.components.add("frontend")
    with (
        patch(f"{MODULE}.add_extra_js_url") as add,
        patch(f"{MODULE}.remove_extra_js_url") as remove,
    ):
        yield add, remove


def urls(resources: ResourceStorageCollection) -> list[tuple[str, str]]:
    return [(item["type"], item["url"]) for item in resources.async_items()]


async def test_creates_the_resource(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    resources: ResourceStorageCollection,
    extra_js: tuple[Mock, Mock],
) -> None:
    stored(hass_storage, OTHER)
    await async_register_card(hass)
    await async_register_card(hass)  # nothing more the second time
    assert urls(resources) == [
        ("module", OTHER["url"]),
        ("module", CARD_URL),
    ]
    extra_js[0].assert_not_called()  # loaded once, not twice


async def test_updates_the_version(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    resources: ResourceStorageCollection,
) -> None:
    stored(hass_storage, {"id": "card", "type": "module", "url": OLD_URL}, OTHER)
    await async_register_card(hass)
    assert urls(resources) == [("module", CARD_URL), ("module", OTHER["url"])]
    assert resources.async_items()[0]["id"] == "card"


async def test_removes_duplicates(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    resources: ResourceStorageCollection,
) -> None:
    stored(
        hass_storage,
        OTHER,
        {"id": "a", "type": "js", "url": OLD_URL},
        {"id": "b", "type": "module", "url": CARD_URL},
        {"id": "c", "type": "module", "url": OLD_URL.split("?")[0]},
    )
    await async_register_card(hass)
    assert urls(resources) == [("module", OTHER["url"]), ("module", CARD_URL)]


async def test_yaml_resources_fall_back_to_extra_module(
    hass: HomeAssistant, extra_js: tuple[Mock, Mock]
) -> None:
    use_resources(hass, ResourceYAMLCollection([OTHER]))
    await async_register_card(hass)
    extra_js[0].assert_called_once_with(hass, CARD_URL)


async def test_without_dashboards_falls_back_to_extra_module(
    hass: HomeAssistant, extra_js: tuple[Mock, Mock]
) -> None:
    await async_register_card(hass)
    extra_js[0].assert_called_once_with(hass, CARD_URL)


async def test_failure_falls_back_to_extra_module(
    hass: HomeAssistant,
    resources: ResourceStorageCollection,
    extra_js: tuple[Mock, Mock],
) -> None:
    with patch.object(resources, "async_get_info", side_effect=OSError("disk")):
        await async_register_card(hass)
    extra_js[0].assert_called_once_with(hass, CARD_URL)


async def test_unregister_removes_only_the_card(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    resources: ResourceStorageCollection,
    extra_js: tuple[Mock, Mock],
) -> None:
    stored(
        hass_storage,
        {"id": "card", "type": "module", "url": CARD_URL},
        OTHER,
        {"id": "old", "type": "module", "url": OLD_URL},
    )
    await async_unregister_card(hass)
    assert urls(resources) == [("module", OTHER["url"])]
    extra_js[1].assert_called_once_with(hass, CARD_URL)


async def test_entry_adds_and_removes_the_card(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    resources: ResourceStorageCollection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hass, "http", Mock(async_register_static_paths=AsyncMock()), raising=False
    )
    stored(hass_storage, OTHER)
    hass.states.async_set(PRICE, "0.04577", price_attributes())
    hass.states.async_set(METER, "1000000", METER_ATTRIBUTES)
    first, second = (
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=unique_id,
            title="Haus",
            data=entry_data(),
            version=2,
            subentries_data=subentries_data(),
        )
        for unique_id in (METER, "sensor.other_meter")
    )
    for entry in (first, second):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert urls(resources) == [("module", OTHER["url"]), ("module", CARD_URL)]

    # The resource stays while another entry can still show the card.
    await hass.config_entries.async_remove(first.entry_id)
    await hass.async_block_till_done()
    assert urls(resources) == [("module", OTHER["url"]), ("module", CARD_URL)]
    await hass.config_entries.async_remove(second.entry_id)
    await hass.async_block_till_done()
    assert urls(resources) == [("module", OTHER["url"])]
