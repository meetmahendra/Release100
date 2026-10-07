# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the UI translation catalog (Plan 11, T04)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict

import pytest

from core_platform.app.i18n import catalog as cat
from core_platform.app.i18n.catalog import CatalogError, I18nCatalog


def _write(directory: Path, locale: str, data: Dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{locale}.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def core_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "core"
    _write(directory, "en_US", {"common": {"save": "Save", "hello": "Hello {name}",
                                             "items_one": "{count} item", "items_other": "{count} items"}})
    _write(directory, "hi_IN", {"common": {"save": "SAVE-HI"}})
    return directory


@pytest.fixture
def catalog(core_dir: Path) -> I18nCatalog:
    c = I18nCatalog("en_US", "marker")
    c.load_core(core_dir)
    return c


def test_lookup_and_locale_override(catalog: I18nCatalog) -> None:
    assert catalog.translate("common.save", "en_US") == "Save"
    assert catalog.translate("common.save", "hi_IN") == "SAVE-HI"


def test_fallback_to_default_locale(catalog: I18nCatalog) -> None:
    assert catalog.translate("common.hello", "hi_IN", name="Asha") == "Hello Asha"


def test_interpolation_unknown_placeholder_stays_literal(catalog: I18nCatalog) -> None:
    assert catalog.translate("common.hello", "en_US") == "Hello {name}"


def test_interpolated_value_is_not_reinterpreted(catalog: I18nCatalog) -> None:
    out = catalog.translate("common.hello", "en_US", name="{count}<b>x</b>")
    assert out == "Hello {count}<b>x</b>"


def test_plural_forms(catalog: I18nCatalog) -> None:
    assert catalog.translate("common.items", "en_US", count=1) == "1 item"
    assert catalog.translate("common.items", "en_US", count=0) == "0 items"
    assert catalog.translate("common.items", "en_US", count=5) == "5 items"


def test_plural_falls_back_to_plain_key(catalog: I18nCatalog) -> None:
    assert catalog.translate("common.save", "en_US", count=3) == "Save"


def test_missing_key_marker_policy_logs_once(catalog: I18nCatalog, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="core_platform.i18n"):
        assert catalog.translate("nope.key", "en_US") == "[[nope.key]]"
        assert catalog.translate("nope.key", "en_US") == "[[nope.key]]"
    assert len([r for r in caplog.records if "nope.key" in r.getMessage()]) == 1
    assert "nope.key" in catalog.missing_keys()


def test_missing_key_key_policy(core_dir: Path) -> None:
    c = I18nCatalog("en_US", "key")
    c.load_core(core_dir)
    assert c.translate("nope.key", "en_US") == "nope.key"


def test_core_cannot_define_app_keys(tmp_path: Path) -> None:
    _write(tmp_path, "en_US", {"apps": {"demo": {"x": "y"}}})
    with pytest.raises(CatalogError):
        I18nCatalog().load_core(tmp_path)


def test_app_prefix_enforced(tmp_path: Path) -> None:
    _write(tmp_path, "en_US", {"core": {"title": "hijack"}})
    with pytest.raises(CatalogError):
        I18nCatalog().load_app("demo", tmp_path)


def test_app_keys_load_and_resolve(tmp_path: Path) -> None:
    _write(tmp_path, "en_US", {"apps": {"demo": {"home": {"title": "Demo Home"}}}})
    c = I18nCatalog()
    c.load_app("demo", tmp_path)
    assert c.translate("apps.demo.home.title", "en_US") == "Demo Home"


def test_duplicate_key_rejected(catalog: I18nCatalog, tmp_path: Path) -> None:
    _write(tmp_path, "en_US", {"common": {"save": "again"}})
    with pytest.raises(CatalogError):
        catalog.load_core(tmp_path)


def test_bad_locale_filename_and_bad_json(tmp_path: Path) -> None:
    (tmp_path / "english.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CatalogError):
        I18nCatalog().load_core(tmp_path)
    (tmp_path / "english.json").unlink()
    (tmp_path / "en_US.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError):
        I18nCatalog().load_core(tmp_path)


@pytest.mark.parametrize("data", [{"Bad-Key": "x"}, {"a": 5}, {"a": ["x"]}])
def test_bad_structure_rejected(tmp_path: Path, data: Dict[str, Any]) -> None:
    _write(tmp_path, "en_US", data)
    with pytest.raises(CatalogError):
        I18nCatalog().load_core(tmp_path)


def test_missing_directory_is_tolerated(tmp_path: Path) -> None:
    c = I18nCatalog()
    c.load_core(tmp_path / "does_not_exist")
    assert c.locales() == frozenset()


def test_register_entries_validates_locale() -> None:
    with pytest.raises(CatalogError):
        I18nCatalog().register_entries("xx", {"a.b": "c"})


def test_bundle_subset_with_default_merged_under(catalog: I18nCatalog) -> None:
    bundle = catalog.bundle(["common"], "hi_IN")
    assert bundle["common.save"] == "SAVE-HI"
    assert bundle["common.hello"] == "Hello {name}"
    assert catalog.bundle(["other"], "hi_IN") == {}


def test_keys_locales_clear_and_default(catalog: I18nCatalog) -> None:
    assert "common.save" in catalog.keys("en_US")
    assert catalog.locales() == frozenset({"en_US", "hi_IN"})
    assert catalog.default_locale == "en_US"
    catalog.clear()
    assert catalog.locales() == frozenset()


def test_thread_safety_smoke(catalog: I18nCatalog) -> None:
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            for _ in range(300):
                catalog.translate("common.save", "hi_IN")
                catalog.bundle(["common"], "en_US")
        except BaseException as err:  # noqa: BLE001 - collected for assertion
            errors.append(err)

    def writer() -> None:
        try:
            for i in range(100):
                catalog.register_entries("en_US", {f"extra.k{i}": "v"})
        except BaseException as err:  # noqa: BLE001
            errors.append(err)

    threads = [threading.Thread(target=reader), threading.Thread(target=reader), threading.Thread(target=writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_get_catalog_loads_real_core_locale() -> None:
    cat.reset_catalog()
    try:
        c = cat.get_catalog()
        assert c is cat.get_catalog()
        assert c.translate("common.save", "en_US") == "Save"
        assert c.translate("common.records_found", "en_US", count=2) == "2 records found"
    finally:
        cat.reset_catalog()


def test_real_en_us_catalog_is_ascii_only() -> None:
    path = Path(cat.__file__).resolve().parents[2] / "locales" / "en_US.json"
    path.read_text(encoding="ascii")
