"""Consistency checks for manifest.json, hacs.json, pyproject.toml and translations."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from homeassistant.data_entry_flow import section

from custom_components.tarifwacht.config_flow import (
    _modul3_fields,
    _tariff_data,
    _tariff_schema,
)
from custom_components.tarifwacht.const import DOMAIN, KINDS, VERSION
from custom_components.tarifwacht.sensor import (
    DIFFERENCE,
    ENERGY,
    PRICE_NOW,
    SAVING_BATTERY,
    SAVING_PV,
    TARIFF_SENSORS,
)
from custom_components.tarifwacht.tariff_config import change_fields
from custom_components.tarifwacht.tariffs import BasePeriod

ROOT = Path(__file__).parent.parent
INTEGRATION = ROOT / "custom_components" / DOMAIN


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest() -> dict:
    return load(INTEGRATION / "manifest.json")


def test_versions_match() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest()["version"] == VERSION == pyproject["project"]["version"]


def test_domain_matches_folder() -> None:
    assert manifest()["domain"] == DOMAIN == INTEGRATION.name


def test_manifest_key_order() -> None:
    # hassfest requires domain, name first, then the remaining keys sorted.
    keys = list(manifest())
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_hacs_json() -> None:
    hacs = load(ROOT / "hacs.json")
    assert hacs["name"] == manifest()["name"]
    assert hacs["filename"] == f"{DOMAIN}.zip"


def _keys(data: object, prefix: str = "") -> set[str]:
    if isinstance(data, dict):
        return {
            k for key, value in data.items() for k in _keys(value, f"{prefix}{key}.")
        }
    return {prefix.rstrip(".")}


def test_translations_complete() -> None:
    strings = load(INTEGRATION / "strings.json")
    assert load(INTEGRATION / "translations" / "en.json") == strings
    assert _keys(load(INTEGRATION / "translations" / "de.json")) == _keys(strings)


def test_every_sensor_translated() -> None:
    strings = load(INTEGRATION / "strings.json")
    keys = {
        d.key
        for d in (
            *TARIFF_SENSORS,
            DIFFERENCE,
            ENERGY,
            SAVING_PV,
            SAVING_BATTERY,
            PRICE_NOW,
        )
    } | {"cheapest"}
    assert set(strings["entity"]["sensor"]) == keys


def test_tariff_kinds_translated() -> None:
    tariff = load(INTEGRATION / "strings.json")["config_subentries"]["tariff"]
    assert set(tariff["step"]["user"]["menu_options"]) == set(KINDS)
    for kind in KINDS:
        schema = _tariff_schema(kind).schema
        sections = {str(k): v for k, v in schema.items() if isinstance(v, section)}
        fields = {str(key) for key in schema} - set(sections)
        step = tariff["step"][kind]
        assert set(step["data"]) == fields, kind
        assert set(step.get("sections", {})) == set(sections), kind
        for name, part in sections.items():
            keys = {str(key) for key in part.schema.schema}
            assert set(step["sections"][name]["data"]) == keys, (kind, name)
            assert set(step["sections"][name]["data_description"]) <= keys


def test_base_periods_translated() -> None:
    strings = load(INTEGRATION / "strings.json")
    options = strings["selector"]["base_period"]["options"]
    assert set(options) == {p.value for p in BasePeriod}


def test_reconfigure_step_matches_user_step() -> None:
    steps = load(INTEGRATION / "strings.json")["config"]["step"]
    assert steps["reconfigure"] == steps["user"]


def test_solar_steps_match() -> None:
    """The steps with and without suggestions differ only in their hint."""
    for name in ("strings.json", "translations/de.json"):
        steps = load(INTEGRATION / name)["config_subentries"]["solar"]["step"]
        base = steps["reconfigure"]
        variants = {
            "user": ("{einspeisewacht_url}", "{speicherwacht_url}"),
            "suggested_einspeisewacht": ("{einspeisewacht}",),
            "suggested_speicherwacht": ("{speicherwacht}",),
            "suggested_both": ("{einspeisewacht}", "{speicherwacht}"),
        }
        for step, placeholders in variants.items():
            text = steps[step]
            assert {k: v for k, v in text.items() if k != "description"} == {
                k: v for k, v in base.items() if k != "description"
            }, (name, step)
            assert text["description"].startswith(base["description"] + "\n\n")
            for placeholder in placeholders:
                assert placeholder in text["description"], (name, step)


def test_price_change_fields_translated() -> None:
    step = load(INTEGRATION / "strings.json")["config_subentries"]["tariff"]["step"]
    fields = {"from"} | {key for kind in KINDS for key in change_fields(kind)}
    # Modul 3 is stored as one value but entered in six fields (a fixed
    # price: eight, with the grid fee it contains and the VAT).
    fields = (fields - {"modul3"}) | set(step["modul3_fixed"]["data"])
    # VAT and base price period under "More", Modul 3 in its own section.
    add_change = step["add_change"]
    sections = add_change["sections"]
    assert set(sections) == {"details_section", "modul3_section"}
    assert set(sections["details_section"]["data"]) == {"vat", "base_period"}
    assert set(sections["modul3_section"]["data"]) == set(step["modul3_fixed"]["data"])
    shown = set(add_change["data"])
    assert not shown & {"vat", "base_period", "modul3_active", "nt", "ht"}
    assert shown | {k for s in sections.values() for k in s["data"]} == fields
    assert set(step["reconfigure"]["menu_options"]) == {
        "edit",
        "modul3",
        "add_change",
        "remove_change",
    }


def test_modul3_fields_translated() -> None:
    strings = load(INTEGRATION / "strings.json")
    steps = strings["config_subentries"]["tariff"]["step"]
    for step, kind in (("modul3", "dynamic_market"), ("modul3_fixed", "fixed")):
        fields = {str(key) for key in _modul3_fields(kind)}
        assert set(steps[step]["data"]) == fields, step
    assert set(steps["modul3_fixed"]["data"]) - set(steps["modul3"]["data"]) == {
        "standard_fee",
        "vat",
    }
    assert set(strings["selector"]["quarters"]["options"]) == {"1", "2", "3", "4"}


def test_every_entity_and_action_has_an_icon() -> None:
    icons = load(INTEGRATION / "icons.json")
    strings = load(INTEGRATION / "strings.json")
    assert set(icons["entity"]["sensor"]) == set(strings["entity"]["sensor"])
    assert set(icons["entity"]["button"]) == set(strings["entity"]["button"])
    assert set(strings["entity"]["button"]) == {
        "issue_report",
        "recalculate_statistics",
    }
    assert set(icons["services"]) == set(strings["services"])


def test_smard_consent_only_for_exchange_price_tariffs() -> None:
    """The SMARD.de checkbox exists and is stored only for exchange prices;
    without it in the input (setup form, old tariffs) nothing is stored."""
    base = {"base_period": "month", "current": False, "price_entity": "sensor.p"}
    market = {**base, "vat": 19.0}
    assert "smard_fill" in {str(k) for k in _tariff_schema("dynamic_market").schema}
    for kind in ("fixed", "dynamic_total"):
        assert "smard_fill" not in {str(k) for k in _tariff_schema(kind).schema}
    assert _tariff_data("dynamic_market", {**market, "smard_fill": True})["smard_fill"]
    assert not _tariff_data("dynamic_market", {**market, "smard_fill": False})[
        "smard_fill"
    ]
    assert "smard_fill" not in _tariff_data("dynamic_market", market)
    total = _tariff_data("dynamic_total", {**base, "smard_fill": True})
    assert "smard_fill" not in total
