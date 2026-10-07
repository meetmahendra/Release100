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

"""Unit tests for the UI / NLS settings (Plan 11, T03)."""

import pytest
from pydantic import ValidationError

from core_platform.app.config import PlatformSettings


def _fresh(**env: str) -> PlatformSettings:
    """Build settings ignoring any local .env file."""
    return PlatformSettings(_env_file=None, **env)  # type: ignore[call-arg]


def test_ui_defaults() -> None:
    s = _fresh()
    assert s.UI_DEFAULT_LOCALE == "en_US"
    assert s.UI_SUPPORTED_LOCALES == ["en_US"]
    assert s.UI_LOCALE_COOKIE_NAME == "ui_locale"
    assert s.UI_MISSING_KEY_POLICY == "marker"


def test_ui_supported_locales_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_SUPPORTED_LOCALES", '["en_US","hi_IN"]')
    assert _fresh().UI_SUPPORTED_LOCALES == ["en_US", "hi_IN"]


def test_ui_missing_key_policy_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_MISSING_KEY_POLICY", "explode")
    with pytest.raises(ValidationError):
        _fresh()


@pytest.mark.parametrize("bad", ["english", "EN_us", "en-US", ""])
def test_ui_default_locale_format(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("UI_DEFAULT_LOCALE", bad)
    with pytest.raises(ValidationError):
        _fresh()


def test_ui_supported_locales_rejects_empty_and_bad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_SUPPORTED_LOCALES", "[]")
    with pytest.raises(ValidationError):
        _fresh()
    monkeypatch.setenv("UI_SUPPORTED_LOCALES", '["en_US","bogus"]')
    with pytest.raises(ValidationError):
        _fresh()


def test_ui_default_must_be_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_DEFAULT_LOCALE", "hi_IN")
    with pytest.raises(ValidationError):
        _fresh()
