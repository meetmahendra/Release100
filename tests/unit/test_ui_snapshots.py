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

"""Render-snapshot equivalence tests for every UI page (Plan 11, T02)."""

from __future__ import annotations

import pytest

from tests.ui_snapshots import snapshot_lib


@pytest.fixture(scope="module")
def captured() -> dict[str, str]:
    return snapshot_lib.capture_all()


def test_capture_is_deterministic(captured: dict[str, str]) -> None:
    """Two consecutive captures must be identical (no volatile leakage)."""
    again = snapshot_lib.capture_all()
    flaky = [name for name in captured if captured[name] != again[name]]
    assert flaky == []


def test_normalizer_scrubs_volatile_values() -> None:
    html = (
        '<div nonce="abc"><input name="csrf_token" value="zzz">'
        "<p>Updated 2026-10-07 12:30:45 by 42 users</p>"
        "<table><tbody><tr><td>row</td></tr></tbody></table></div>"
    )
    out = snapshot_lib.normalize_html(html)
    assert "<TS>" in out and "#" in out
    assert "row" not in out
    assert 'nonce="<TOKEN>"' in out
    assert 'value="<TOKEN>"' in out


@pytest.mark.parametrize("spec", snapshot_lib.PAGES, ids=lambda s: s.name)
def test_page_matches_baseline(spec: snapshot_lib.PageSpec, captured: dict[str, str]) -> None:
    target = snapshot_lib.baseline_path(spec.name)
    assert target.exists(), f"missing baseline: run scripts/capture_ui_snapshots.py --update ({spec.name})"
    assert captured[spec.name] == target.read_text(encoding="utf-8")
