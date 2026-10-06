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

"""Scenario runner for the entitlement live-benchmark domain (Plan 10, T23).

Builds a throwaway SQLite database, loads the real cartridge manifests, applies the
scenario's groups / units / bindings through the real admin service, then evaluates
the request through the real gate and returns a flat result dictionary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import Engine, create_engine

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements.admin_service import EntitlementAdminService
from core_platform.app.entitlements.audit import EntitlementAuditor
from core_platform.app.entitlements.contracts import (
    Decision,
    DecisionReason,
    EntitlementDeniedError,
    ResourceRef,
)
from core_platform.app.entitlements.evaluator import EntitlementEvaluator
from core_platform.app.entitlements.gate import EntitlementGate
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository
from core_platform.app.telemetry.audit_engine import AuditEngine

APPS_ROOT = Path(__file__).resolve().parents[2] / "apps"
ADMIN_ID = "benchmark_admin"


class _ExplodingEvaluator:
    """Evaluator stand-in that always fails, to prove the gate fails closed."""

    def evaluate(
        self, ctx: SecurityContext, action_id: str, resource: Optional[ResourceRef] = None
    ) -> Decision:
        raise RuntimeError("simulated evaluator failure")


class EntitlementScenarioRunner:
    """Runs one entitlement scenario against real components on a scratch database."""

    def __init__(self, temp_dir: Path, audit_engine: AuditEngine) -> None:
        """Create the runner.

        Args:
            temp_dir: Scratch directory for the SQLite file.
            audit_engine: Audit engine writing into the scratch directory.
        """
        self._temp_dir = temp_dir
        self._audit = EntitlementAuditor(audit_engine)
        self._counter = 0
        self._engines: List[Engine] = []

    def close(self) -> None:
        """Dispose every scratch engine."""
        for engine in self._engines:
            engine.dispose()
        self._engines.clear()

    def _registry(self) -> EntitlementRegistry:
        registry = EntitlementRegistry()
        for path in sorted(APPS_ROOT.glob("*/entitlements.json")):
            registry.register_raw(path.parent.name, json.loads(path.read_text(encoding="utf-8")))
        return registry

    def run(self, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the scenario and return its flat final state."""
        self._counter += 1
        engine = create_engine(f"sqlite:///{self._temp_dir / f'ent_{self._counter}.db'}")
        self._engines.append(engine)
        repo = EntitlementRepository(engine=engine)
        registry = self._registry()
        service = EntitlementAdminService(repo, registry, self._audit)
        tenant = str(inp.get("tenant_id", "bench_tenant_a"))
        admin_ctx = SecurityContext(
            principal_id=ADMIN_ID, tenant_id=tenant, auth_strategy="local_jwt", is_authenticated=True
        )

        units: Dict[str, str] = {}
        for unit in inp.get("units", []):
            parent = units.get(unit.get("parent", "")) if unit.get("parent") else None
            units[unit["name"]] = service.create_unit(admin_ctx, unit["name"], "Unit", parent).id

        for group in inp.get("groups", []):
            group_tenant = group.get("tenant_id", tenant)
            ctx = admin_ctx.model_copy(update={"tenant_id": group_tenant})
            created = service.create_group(ctx, group["name"], None, group.get("kind", "USER"))
            for member in group.get("members", []):
                service.add_member(ctx, created.id, member)
            for binding in group.get("bindings", []):
                unit_id = units.get(binding.get("unit", "")) if binding.get("unit") else None
                service.bind_bundle(
                    ctx, created.id, binding["app_id"], binding["bundle_id"],
                    Scope(binding.get("scope", "TENANT")), unit_id, bool(binding.get("confirm", False)),
                )

        operation = str(inp.get("operation", "check"))
        if operation == "bind_unconfirmed":
            return self._bind_unconfirmed(service, admin_ctx, inp)

        principal = SecurityContext(
            principal_id=str(inp["principal"]),
            tenant_id=str(inp.get("request_tenant_id", tenant)),
            auth_strategy=str(inp.get("auth_strategy", "phone_biometric")),
            is_authenticated=True,
        )
        res = inp.get("resource") or {}
        resource = ResourceRef(
            owner_principal_id=res.get("owner"),
            unit_id=units.get(res["unit"]) if res.get("unit") else None,
        )
        evaluator: Any = _ExplodingEvaluator() if operation == "evaluator_error" else EntitlementEvaluator(repo, registry)
        gate = EntitlementGate(evaluator, repo, self._audit, registry, lambda: str(inp.get("mode", "enforce")))
        if operation == "unmapped_tool":
            return self._decision(lambda: gate.enforce_unmapped_tool(principal, str(inp["tool"])))
        return self._decision(
            lambda: gate.enforce(principal, str(inp["action_id"]), resource, bool(inp.get("legacy_allowed", True)))
        )

    @staticmethod
    def _decision(call: Any) -> Dict[str, Any]:
        try:
            decision: Decision = call()
        except EntitlementDeniedError as err:
            decision = err.decision
        return {"allowed": decision.allowed, "reason": decision.reason.value}

    @staticmethod
    def _bind_unconfirmed(
        service: EntitlementAdminService, ctx: SecurityContext, inp: Dict[str, Any]
    ) -> Dict[str, Any]:
        group = service.create_group(ctx, "bench_high_group", None, str(inp.get("kind", "USER")))
        try:
            service.bind_bundle(
                ctx, group.id, inp["app_id"], inp["bundle_id"], Scope(inp.get("scope", "TENANT")),
                None, bool(inp.get("confirm", False)),
            )
        except ValueError as err:
            return {"allowed": False, "reason": str(err)}
        return {"allowed": True, "reason": DecisionReason.ALLOWED.value}
