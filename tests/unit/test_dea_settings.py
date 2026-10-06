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

"""Unit tests for Decentralized Entitlement Architecture settings (Plan 10, T01)."""

import pytest
from pydantic import ValidationError

from core_platform.app.config import PlatformSettings


def _fresh(**env: str) -> PlatformSettings:
    """Build settings ignoring any local .env file."""
    return PlatformSettings(_env_file=None, **env)  # type: ignore[call-arg]


def test_entitlement_defaults_are_fail_safe() -> None:
    """Default mode is shadow, depth is 32, manifest file is entitlements.json."""
    s = _fresh()
    assert s.ENTITLEMENT_ENFORCEMENT_MODE == "shadow"
    assert s.ENTITLEMENT_MAX_UNIT_DEPTH == 32
    assert s.ENTITLEMENT_MANIFEST_FILENAME == "entitlements.json"


def test_entitlement_mode_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variable overrides the enforcement mode."""
    monkeypatch.setenv("ENTITLEMENT_ENFORCEMENT_MODE", "enforce")
    assert _fresh().ENTITLEMENT_ENFORCEMENT_MODE == "enforce"


def test_entitlement_mode_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown modes are rejected at configuration time."""
    monkeypatch.setenv("ENTITLEMENT_ENFORCEMENT_MODE", "yolo")
    with pytest.raises(ValidationError):
        _fresh()


@pytest.mark.parametrize("bad_depth", ["0", "129"])
def test_entitlement_depth_bounds(monkeypatch: pytest.MonkeyPatch, bad_depth: str) -> None:
    """Depth outside 1..128 is rejected."""
    monkeypatch.setenv("ENTITLEMENT_MAX_UNIT_DEPTH", bad_depth)
    with pytest.raises(ValidationError):
        _fresh()
