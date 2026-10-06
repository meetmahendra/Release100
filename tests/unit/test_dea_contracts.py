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

"""Unit tests for entitlement contracts (Plan 10, T03)."""

import pytest
from pydantic import ValidationError

from core_platform.app.entitlements.contracts import (
    Decision,
    DecisionReason,
    EntitlementDeniedError,
    ResourceRef,
)


def test_resource_ref_is_frozen() -> None:
    ref = ResourceRef(owner_principal_id="p1", unit_id="u1")
    with pytest.raises(ValidationError):
        ref.unit_id = "u2"  # type: ignore[misc]


def test_decision_is_frozen_and_defaults() -> None:
    d = Decision(allowed=False, reason=DecisionReason.NO_MATCHING_BINDING, action_id="demo:item:view")
    assert d.matched_binding_ids == []
    assert d.enforced is False
    with pytest.raises(ValidationError):
        d.allowed = True  # type: ignore[misc]


def test_denied_error_round_trips_decision() -> None:
    d = Decision(allowed=False, reason=DecisionReason.SCOPE_MISMATCH, action_id="demo:item:approve")
    err = EntitlementDeniedError(d)
    assert err.decision is d
    assert "SCOPE_MISMATCH" in str(err)


def test_reason_values_equal_names() -> None:
    assert DecisionReason("ALLOWED") is DecisionReason.ALLOWED
    for member in DecisionReason:
        assert member.value == member.name
