"""Consistency checks for manifest.json, hacs.json, pyproject.toml and translations."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from custom_components.tarifwacht.config_flow import _tariff_schema
from custom_components.tarifwacht.const import DOMAIN, KINDS, VERSION
from custom_components.tarifwacht.sensor import DIFFERENCE, ENERGY, TARIFF_SENSORS
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
    keys = {d.key for d in (*TARIFF_SENSORS, DIFFERENCE, ENERGY)} | {"cheapest"}
    assert set(strings["entity"]["sensor"]) == keys


def test_tariff_kinds_translated() -> None:
    tariff = load(INTEGRATION / "strings.json")["config_subentries"]["tariff"]
    assert set(tariff["step"]["user"]["menu_options"]) == set(KINDS)
    for kind in KINDS:
        fields = {str(key) for key in _tariff_schema(kind).schema}
        assert set(tariff["step"][kind]["data"]) == fields, kind


def test_base_periods_translated() -> None:
    strings = load(INTEGRATION / "strings.json")
    options = strings["selector"]["base_period"]["options"]
    assert set(options) == {p.value for p in BasePeriod}


def test_reconfigure_step_matches_user_step() -> None:
    steps = load(INTEGRATION / "strings.json")["config"]["step"]
    assert steps["reconfigure"] == steps["user"]
