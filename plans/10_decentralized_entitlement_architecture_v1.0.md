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

# PLAN 10: DECENTRALIZED ENTITLEMENT ARCHITECTURE (DEA) - ORGANIZATIONAL ROLES (v1.0)

> **Status:** PROPOSED - awaiting user go-ahead for Phase 0.
> **Governing standards:** GEES v2.0 (`ENGINEERING_EXCELLENCE_STANDARD_v2.0.md`, `GEMINI.md`, `AGENTS.md`).
> **Audience:** an AI implementer (Gemini Flash class). Every task is written so it can be done without design decisions.

---

## 0. HOW TO USE THIS DOCUMENT (IMPLEMENTER RULES - READ FIRST)

1. Do **one task at a time**, in order. Do not start task N+1 until task N's *Verify* passes.
2. Before each task, `view_file` every file listed under **Read first**. Do not guess signatures.
3. Touch **only** files listed under **Files**. If you believe another file must change, STOP and report.
4. **Do not refactor, rename, reformat, or "improve"** existing code. Do not edit existing tests unless a task says so.
5. Every new `.py` file begins with this exact header (the test `test_all_source_files_have_apache_license_header` fails otherwise):
   ```
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
   ```
6. Full type annotations on every function (`mypy --strict`). No bare `Any` unless commented with a reason. No bare `except:`. Chain causes: `raise X(...) from err`.
7. **Fail closed.** Inside the evaluator/gate, an exception means DENY (in `enforce`) - never `except Exception: pass` followed by allow.
8. **No hardcoded business constants** in Python (names, thresholds, URLs, UI strings that describe a cartridge). Operational values come from `Settings`; descriptive text comes from `entitlements.json`.
9. Console output uses ASCII tags only: `[BUILD]`, `[SUCCESS]`, `[ERROR]`. No emoji or non-ASCII in `.py` or `.html` you create (Windows `cp1252` consoles crash on it).
10. Use `with` for every DB session. Tests must use a temp SQLite file (`tmp_path`), never the real DB.
11. Test keys/secrets, if any are needed, are synthetic (`mock_test_key_12345`). Never real credentials.
12. Shell is **PowerShell on Windows**: chain with `;` not `&&`. Python is `.\.venv\Scripts\python.exe`.
13. **Stop rule:** if a *Verify* command fails twice after you fix what you think is wrong, STOP and report the exact error. Do not work around it by weakening a test.
14. **Never** `git push`. Local commits only (GEMINI.md rule 11). One commit per task: `feat(dea): T07 repository` style.
15. Never write to `D:\mailOrganizer`, `D:\WhatsappClientForMailOrganized`, `D:\AI-ProjectManager`.

---

## 1. VERIFIED REPOSITORY FACTS (do not re-derive; if reality differs, STOP and report)

| Topic | Fact | File |
| :--- | :--- | :--- |
| Current authz | Role strings: `BaseApplication.required_roles`, `SecurityContext.user_roles`, `RBACFilter.assert_app_access`, route-level `Depends(require_app("<app_id>"))` | `core_platform/app/rbac/permissions.py` |
| Existing fail-open | `_get_required_roles` swallows all exceptions and returns `[]`. Leave as is. | same, L54-61 |
| SecurityContext | Pure Pydantic model: `principal_id, tenant_id, user_roles, permitted_apps, auth_strategy, is_authenticated, is_biometric_verified`; properties `is_admin`, `is_devops`. **No DB access.** | `core_platform/app/auth/models.py` |
| Principal identity | WhatsApp: `principal_id = phone_number`. Web user JWT: `principal_id = user.phone_number`. Devops: `username`. API key: key principal. | `core_platform/app/auth/strategies.py` |
| WhatsApp roles | `resolve_whatsapp` hardcodes `user_roles=["operator"]` | same |
| Users/tenants | `PlatformUser` (`platform_users`, scalar `role`, `allowed_cartridges_json`), `Tenant` (`platform_tenants`, `allowed_cartridges_json`), `TenantAuditLog` | `core_platform/app/identity/models.py` |
| Core DB base | `Base`, `TimestampMixin`, `UUIDPrimaryKeyMixin`, `TenantIsolationMixin` | `core_platform/app/db/base.py` |
| Core table creation | `UserIdentityService._ensure_tables` calls `PlatformUser.metadata.create_all`. `DatabaseManager.init_tables()` only handles **cartridge** metadata. Alembic has only `versions/001_initial_schema.py`. | `identity/service.py`, `db/manager.py`, `migrations/` |
| DB session | `DatabaseManager.get_instance().get_session()` is a context manager; `get_engine()` returns the Engine. Tests reset it via autouse fixture in `tests/conftest.py`. | `db/manager.py` |
| Audit | `AuditEngine.get_instance().record_event(action_type, payload_summary, operator_id=..., kiosk_id=None, layer_0_status=..., layer_1_model=..., layer_1_confidence=..., layer_2_gate_status=..., correlation_id=None)` -> SHA-256 chained, writes jsonl+csv+html | `telemetry/audit_engine.py` |
| Plugin loading | `PluginLoader.load_all()` instantiates cartridges (`apps/<id>/plugin.py`); `get_application(app_id)`, `get_all_applications()`. Global instance `plugin_loader` in `core_platform/main.py`. | `plugin_engine/loader.py` |
| Cartridge base | `BaseApplication` (ABC) with `app_id`, `required_roles`, etc. | `plugin_engine/base_plugin.py` |
| Settings | Pydantic settings with `DRY_RUN=True` default | `core_platform/app/config.py` |
| Admin UI | `admin_shell/routes.py` (`APIRouter(prefix="/admin")`), pages are **standalone HTML** (e.g. `users.html` is a full `<html>` doc, not `{% extends %}`), router included in `core_platform/main.py` via `app.include_router(admin_router)` | `admin_shell/` |
| Tenant resolution in pages | `resolve_effective_tenant_info(request)` from `core_platform/app/middleware/tenant_context.py`; guarded by `tests/unit/test_every_page_tenant_aware.py` | |
| Boundary tests | core never imports `apps`; every `.py` needs license header; critical files need return annotations | `tests/unit/test_architectural_boundaries.py` |
| Test layout | `tests/unit/test_*.py`, `tests/conftest.py`; live bench: `run_live_benchmark.py` + `tests/live_benchmark/live_evaluator.py` | |
| Cartridge packaging | per-app `MANIFEST.in` + `pyproject.toml` (must include any new data file) | `apps/*/` |
| mypy | `[tool.mypy] strict = true` in `pyproject.toml` | |

### 1.1 Real cartridge endpoint inventory (source of truth for manifests)

**mail_organizer** (`apps/mail_organizer/ui/routes.py`, prefix `/admin/apps/mail-organizer`):
GET `/dashboard`, `/triage`, `/drafts`, `/rules`, `/accounts`, `/pm-queue` (pages) - POST `/api/simulate` - POST `/api/pm-tasks/{id}/approve` - POST `/api/pm-tasks/{id}/reject` - GET `/accounts/reauth`, `/accounts/callback` (Google OAuth connect). MCP tools (`mcp/tools.py`): `mail_search_threads`, `mail_get_thread_context`, `mail_stage_draft_reply`, `mail_check_calendar_availability`, `mail_get_pending_pm_tasks`, `mail_approve_pm_task`.

**temperature_marker** (`apps/temperature_marker/ui/routes.py`, prefix `/admin/apps/temperature-marker`):
GET `/fleet`, `/api/fleet`, `/monitoring`, `/wizard`, `/approvals`, `/api/approvals`, `/api/members`, `/api/members/{emp}/photo`, `/media/{f}`, `/verify-location` - POST `/api/kiosks`, `/api/kiosks/{id}/calibrate-location`, `/api/kiosks/{id}/config` - POST `/api/members`, `/api/members/{emp}/update`, `/reassign`, `/forget-photo` - POST `/api/simulate` - POST `/api/approvals/{emp}/approve|reject` - POST `/api/verify-location` - POST `/api/records/{id}/resolve` - POST `/api/messages/{id}/resolve` - POST `/api/alerts/{id}/acknowledge`. Field check-ins arrive through the WhatsApp workflow (`graph/nodes/layer0_auth_guard.py`). MCP: `temperature_get_latest_reading`, `temperature_check_kiosk_health`, `temperature_list_fleet_status`, `temperature_list_pending_onboarding_approvals`, `temperature_approve_operator`.

---

## 2. LOCKED DECISIONS (do not re-open)

| ID | Decision |
| :-: | :--- |
| D1 | Model = **scoped bundle RBAC**: Principal -> Group -> Binding(bundle, scope) -> Actions. NOT Zanzibar/ReBAC. Evaluator sits behind `AuthorizationPort` (Protocol) so OpenFGA/Cedar can replace it later. |
| D2 | Cartridges declare entitlements in a **JSON data file** `apps/<app_id>/entitlements.json`, validated by Pydantic. Not Python dicts. |
| D3 | Action id format: `<namespace>:<resource>:<verb>`, each segment `[a-z][a-z0-9_]{1,31}`. A manifest declares one `namespace`; all its actions must start with it; **namespaces are globally unique across cartridges** (registry enforces). |
| D4 | **No wildcards** anywhere in storage or evaluation. |
| D5 | Scopes: `SELF`, `UNIT`, `TENANT`. A binding has a `scope` and (for `UNIT`) a `scope_unit_id`. UNIT grants cover that unit **and its descendants**. |
| D6 | Cartridge call sites pass `ResourceRef(owner_principal_id, unit_id)`. UNIT check with `unit_id=None` => deny. SELF check with `owner_principal_id=None` => deny. |
| D7 | Tenant always comes from `SecurityContext.tenant_id`, never from request input. Every table row and every query is tenant-scoped. |
| D8 | Enforcement modes via `Settings.ENTITLEMENT_ENFORCEMENT_MODE` in `{off, shadow, enforce}`; **default `shadow`**. See gate table in 4.4. |
| D9 | A tenant with **zero active bindings** is "not onboarded" and stays on legacy decisions even in `enforce` (clean-slate rule). |
| D10 | Risk: each action declares `effect` and `risk`; core enforces `risk >= MIN_RISK_FOR_EFFECT[effect]`. Bundle risk is **derived** = max(action risks); bundles may not declare it (`extra="forbid"`). |
| D11 | Binding stores `bundle_digest` (sha256 of sorted action ids). Drift between stored and current digest is shown in the UI and audited at startup; evaluation uses **current** bundle actions. |
| D12 | Entitlement **management** routes keep legacy `require_admin` and are never gated by DEA (lockout prevention). Tenant admin only; tenant from `resolve_effective_tenant_info`. |
| D13 | Binding a bundle whose derived risk is `HIGH` requires `confirm_high_risk=true` in the request; otherwise 400. |
| D14 | Audit via `AuditEngine.record_event` through a typed wrapper (`entitlements/audit.py`). Audit every DENY, every shadow diff, every bind/unbind, every ALLOW of a `HIGH` action. |
| D15 | **v1 gates:** cartridge admin HTTP routes, the WhatsApp workflow, **and MCP tool calls made with API keys**. API-key callers are `SERVICE` principals: they belong only to groups of `kind=SERVICE` (never share grants with human `USER` groups even if the id strings collide), and a **`SERVICE` group can never receive a HIGH-risk bundle** (AI agents do not hold high-governance authority; GEES Layer 2). Each MCP tool is mapped to exactly one action through `ActionDef.mcp_tools`; an unmapped tool is denied under `enforce` for an onboarded tenant (fail closed). |
| D16 | Out of scope for v1: IdP sync (Entra/Google/SCIM), custom (admin-composed) bundles, hard Separation-of-Duties engine, permission caching, drag-and-drop UI, per-cartridge domain-service refactor, i18n, OpenFGA. |

---

## 3. TARGET MODULE MAP (all new unless marked)

```
core_platform/app/
  config.py                                (EDIT: 3 settings, T01)
  entitlements/
    __init__.py                            (T02)
    models.py        manifest/bundle Pydantic contract           (T02)
    contracts.py     ResourceRef, Decision, Port, errors         (T03)
    registry.py      in-memory catalog of validated manifests    (T04)
    db_models.py     SQLAlchemy tables                           (T07)
    repository.py    tenant-scoped persistence                   (T08)
    audit.py         typed wrapper over AuditEngine              (T10)
    evaluator.py     pure decision logic                         (T11)
    gate.py          mode handling (off/shadow/enforce)          (T12)
    dependencies.py  require_action / authorize_action           (T12)
    admin_service.py mutations + validation + audit              (T14)
    catalog_view.py  BundleCardView builder (UI data)            (T15)
  plugin_engine/base_plugin.py             (EDIT: get_entitlement_manifest, T05)
  plugin_engine/loader.py                  (EDIT: register manifests, T05)
  admin_shell/entitlements_routes.py       (T16)
  admin_shell/templates/entitlements.html  (T17)
  migrations/versions/002_entitlements.py  (T09)
core_platform/main.py                      (EDIT: include router, T16)
apps/mail_organizer/entitlements.json      (T18)
apps/temperature_marker/entitlements.json  (T20)
tests/unit/test_dea_*.py                   (one per task)
```

---

## 4. CONTRACT LAYER (copy exactly; tasks T02-T03 reference this)

### 4.1 `entitlements/models.py` (T02)

```python
from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ACTION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}:[a-z][a-z0-9_]{1,31}:[a-z][a-z0-9_]{1,31}$")
NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
BUNDLE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,47}$")


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


RISK_RANK: Dict[RiskLevel, int] = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}


class ActionEffect(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    APPROVE = "APPROVE"
    CONFIGURE = "CONFIGURE"
    EXPORT = "EXPORT"
    EXTERNAL_EFFECT = "EXTERNAL_EFFECT"


MIN_RISK_FOR_EFFECT: Dict[ActionEffect, RiskLevel] = {
    ActionEffect.READ: RiskLevel.LOW,
    ActionEffect.WRITE: RiskLevel.LOW,
    ActionEffect.APPROVE: RiskLevel.MEDIUM,
    ActionEffect.EXTERNAL_EFFECT: RiskLevel.MEDIUM,
    ActionEffect.CONFIGURE: RiskLevel.HIGH,
    ActionEffect.EXPORT: RiskLevel.HIGH,
}


class Scope(str, Enum):
    SELF = "SELF"
    UNIT = "UNIT"
    TENANT = "TENANT"


class ActionDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    plain_title: str = Field(min_length=8, max_length=80)
    plain_description: str = Field(min_length=20, max_length=300)
    effect: ActionEffect
    risk: RiskLevel
    touches: List[str] = Field(default_factory=list)
    mcp_tools: List[str] = Field(default_factory=list)  # MCP tool names this action authorizes (D15)


class BundleDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)  # declaring "risk" here is a validation error (D10)

    bundle_id: str
    title: str = Field(min_length=3, max_length=60)
    summary: str = Field(min_length=20, max_length=200)
    who_its_for: str = Field(min_length=10, max_length=160)
    cannot_do: List[str] = Field(default_factory=list)
    allowed_scopes: List[Scope] = Field(min_length=1)
    default_scope: Scope
    actions: List[str] = Field(min_length=1)
    conflicts_with: List[str] = Field(default_factory=list)


class EntitlementManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    namespace: str
    app_title: str = Field(min_length=3, max_length=80)
    actions: List[ActionDef] = Field(min_length=1)
    bundles: List[BundleDef] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_cross_references(self) -> "EntitlementManifest":
        errors: List[str] = []
        if not NAMESPACE_PATTERN.match(self.namespace):
            errors.append(f"namespace '{self.namespace}' invalid")
        action_ids = [a.action_id for a in self.actions]
        if len(set(action_ids)) != len(action_ids):
            errors.append("duplicate action_id")
        for a in self.actions:
            if not ACTION_ID_PATTERN.match(a.action_id):
                errors.append(f"action_id '{a.action_id}' malformed")
            elif not a.action_id.startswith(self.namespace + ":"):
                errors.append(f"action_id '{a.action_id}' outside namespace '{self.namespace}'")
            if RISK_RANK[a.risk] < RISK_RANK[MIN_RISK_FOR_EFFECT[a.effect]]:
                errors.append(f"action '{a.action_id}' risk {a.risk.value} below floor for effect {a.effect.value}")
        bundle_ids = [b.bundle_id for b in self.bundles]
        if len(set(bundle_ids)) != len(bundle_ids):
            errors.append("duplicate bundle_id")
        declared = set(action_ids)
        used: set[str] = set()
        by_id = {a.action_id: a for a in self.actions}
        for b in self.bundles:
            if not BUNDLE_ID_PATTERN.match(b.bundle_id):
                errors.append(f"bundle_id '{b.bundle_id}' malformed")
            if b.default_scope not in b.allowed_scopes:
                errors.append(f"bundle '{b.bundle_id}' default_scope not in allowed_scopes")
            if len(set(b.actions)) != len(b.actions):
                errors.append(f"bundle '{b.bundle_id}' has duplicate actions")
            for aid in b.actions:
                if aid not in declared:
                    errors.append(f"bundle '{b.bundle_id}' references undeclared action '{aid}'")
                else:
                    used.add(aid)
            for other in b.conflicts_with:
                if other not in bundle_ids or other == b.bundle_id:
                    errors.append(f"bundle '{b.bundle_id}' conflicts_with unknown/self '{other}'")
            risks = [RISK_RANK[by_id[x].risk] for x in b.actions if x in by_id]
            if risks and max(risks) >= RISK_RANK[RiskLevel.MEDIUM] and not b.cannot_do:
                errors.append(f"bundle '{b.bundle_id}' is MEDIUM/HIGH risk and must list cannot_do")
        for aid in sorted(declared - used):
            errors.append(f"action '{aid}' is not in any bundle")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def action_map(self) -> Dict[str, ActionDef]:
        return {a.action_id: a for a in self.actions}

    def bundle_risk(self, bundle_id: str) -> RiskLevel:
        amap = self.action_map()
        bundle = next(b for b in self.bundles if b.bundle_id == bundle_id)
        return max((amap[x].risk for x in bundle.actions), key=lambda r: RISK_RANK[r])

    def bundle_digest(self, bundle_id: str) -> str:
        bundle = next(b for b in self.bundles if b.bundle_id == bundle_id)
        return hashlib.sha256("|".join(sorted(bundle.actions)).encode("utf-8")).hexdigest()
```

### 4.2 `entitlements/contracts.py` (T03)

```python
class ResourceRef(BaseModel):  # frozen
    owner_principal_id: Optional[str] = None
    unit_id: Optional[str] = None

class DecisionReason(str, Enum):
    ALLOWED, UNAUTHENTICATED, UNKNOWN_ACTION, NO_MATCHING_BINDING, SCOPE_MISMATCH,
    EVALUATION_ERROR, TENANT_NOT_ONBOARDED, MODE_OFF          # string values equal member names

class Decision(BaseModel):  # frozen
    allowed: bool
    reason: DecisionReason
    action_id: str
    matched_binding_ids: List[str] = []
    enforced: bool = False          # True only when this decision actually decided the outcome

class AuthorizationPort(Protocol):
    def evaluate(self, ctx: SecurityContext, action_id: str,
                 resource: Optional[ResourceRef] = None) -> Decision: ...

class EntitlementDeniedError(Exception):
    def __init__(self, decision: Decision) -> None: ...   # stores .decision
```

### 4.3 Database schema (T07) - SQLAlchemy 2.0 `Mapped[]` on `core_platform.app.db.base.Base` with `TimestampMixin`

| Table | Columns |
| :--- | :--- |
| `platform_ent_org_units` | `id` str(36) PK uuid4, `tenant_id` str(64) idx, `name` str(120), `parent_id` str(36) null idx, `label` str(60) (customer's own word: "Ward", "Faculty") |
| `platform_ent_groups` | `id` str(36) PK, `tenant_id` idx, `name` str(120), `description` str(300) null, `kind` str(16) default `USER` (`USER` = people, `SERVICE` = API-key / AI agents), `external_ref` str(255) null (future IdP sync). Unique(`tenant_id`,`name`) |
| `platform_ent_group_members` | `id` int PK autoinc, `tenant_id` idx, `group_id` str(36) idx, `principal_id` str(64) idx. Unique(`tenant_id`,`group_id`,`principal_id`) |
| `platform_ent_bindings` | `id` str(36) PK, `tenant_id` idx, `group_id` idx, `app_id` str(64), `bundle_id` str(48), `scope` str(16), `scope_unit_id` str(36) null, `bundle_digest` str(64), `granted_by` str(64), `revoked_at` DateTime(tz) null, `revoked_by` str(64) null |

### 4.4 Gate behaviour (T12) - the only place mode is interpreted

| Mode | Tenant onboarded? | Evaluate? | Final outcome | Audit |
| :--- | :--- | :--- | :--- | :--- |
| `off` | n/a | no | `legacy_allowed` | none |
| `shadow` | any | yes | `legacy_allowed` | `ENTITLEMENT_SHADOW_DIFF` only if `evaluate.allowed != legacy_allowed` |
| `enforce` | no (0 active bindings) | no | `legacy_allowed`, reason `TENANT_NOT_ONBOARDED` | `ENTITLEMENT_LEGACY_FALLBACK` (once per tenant per process is fine) |
| `enforce` | yes | yes | `evaluate.allowed` | every deny: `ENTITLEMENT_DENIED`; every allow of a HIGH action: `ENTITLEMENT_ALLOWED_HIGH` |

Exception during evaluation: `enforce` -> deny with `EVALUATION_ERROR`; `shadow` -> legacy decides, error logged.

### 4.5 Evaluator algorithm (T11) - deterministic, no I/O besides repository reads

```
evaluate(ctx, action_id, resource):
  1. not ctx.is_authenticated            -> DENY UNAUTHENTICATED
  2. registry.get_action(action_id) None -> DENY UNKNOWN_ACTION
  3. kind = "SERVICE" if ctx.auth_strategy == "api_key" else "USER"
     group_ids = repo.group_ids_for_principal(ctx.tenant_id, ctx.principal_id, kind)
  4. bindings = repo.active_bindings_for_groups(ctx.tenant_id, group_ids)
  5. candidates = [b for b in bindings
                   if registry.bundle_contains(b.app_id, b.bundle_id, action_id)]   # unknown bundle => skipped
     if not candidates -> DENY NO_MATCHING_BINDING
  6. for b in candidates:
        TENANT: allow
        SELF:   allow iff resource and resource.owner_principal_id == ctx.principal_id
        UNIT:   allow iff resource and resource.unit_id and b.scope_unit_id and
                repo.unit_in_subtree(tenant, root=b.scope_unit_id, candidate=resource.unit_id)
     any allowed -> ALLOW (matched_binding_ids = those that allowed)
  7. else DENY SCOPE_MISMATCH
```
`unit_in_subtree` walks `parent_id` upward from `candidate` at most `Settings.ENTITLEMENT_MAX_UNIT_DEPTH` hops; returns True if it meets `root`.

---

## 5. TASKS

> Each task: **Read first / Files / Spec / Tests / Verify / Commit**. "Verify" commands are run from `d:\IntentRouter_Release100`.
> Task numbers T06 and T13 are intentionally unused (removed during review). Do not look for them; proceed in the order listed.

### PHASE 0 - BASELINE

**T00 Baseline** - Files: none.
- Run: `.\.venv\Scripts\python.exe -m pytest tests/unit -q -x --no-header -p no:cacheprovider` and record the exact pass count (call it `BASELINE`). `git status` must be clean apart from known untracked files. `git switch -c feature/dea-entitlements`.
- Verify: `BASELINE` recorded in your report. If any test fails before you start, STOP and report.

**T01 Settings** - Read first: `core_platform/app/config.py`. Files: `config.py`, `tests/unit/test_dea_settings.py`.
- Add three fields in the existing style, with `Field(default=..., description=...)`: `ENTITLEMENT_ENFORCEMENT_MODE: Literal["off","shadow","enforce"] = "shadow"`, `ENTITLEMENT_MAX_UNIT_DEPTH: int = 32` (ge=1, le=128), `ENTITLEMENT_MANIFEST_FILENAME: str = "entitlements.json"`.
- Tests: defaults are `shadow/32/entitlements.json`; env override `ENTITLEMENT_ENFORCEMENT_MODE=enforce` works; invalid value `"yolo"` raises `ValidationError`.
- Verify: `pytest tests/unit/test_dea_settings.py -q`. Commit `feat(dea): T01 settings`.

### PHASE 1 - PURE CONTRACTS (no DB, no HTTP)

**T02 Manifest models** - Files: `entitlements/__init__.py` (header + docstring only), `entitlements/models.py` (Section 4.1 verbatim), `tests/unit/test_dea_models.py`.
- Tests (each one a separate test function): valid minimal manifest parses; `bundle_risk` is max of action risks; `bundle_digest` is stable and order-independent; **each** validator error: duplicate action id, malformed action id, action outside namespace, effect/risk floor violation (`CONFIGURE` with `LOW`), duplicate bundle id, undeclared action in bundle, `default_scope` not in `allowed_scopes`, unknown/self `conflicts_with`, orphan action (in no bundle), MEDIUM/HIGH bundle without `cannot_do`; bundle containing key `risk` -> `ValidationError` (extra forbidden); `schema_version: 2` rejected.
- Verify: `pytest tests/unit/test_dea_models.py -q` ; `.\.venv\Scripts\python.exe -m mypy --strict core_platform/app/entitlements`. Commit.

**T03 Contracts** - Files: `entitlements/contracts.py` (Section 4.2), `tests/unit/test_dea_contracts.py`.
- Tests: `Decision`/`ResourceRef` are frozen (assignment raises); `EntitlementDeniedError.decision` round-trips; `DecisionReason("ALLOWED")` works.
- Verify: pytest + mypy strict on package. Commit.

**T04 Registry** - Files: `entitlements/registry.py`, `tests/unit/test_dea_registry.py`.
- `class EntitlementRegistry` (not a global singleton; the app holds one instance created in `main.py`, T16). Methods:
  `register(app_id: str, manifest: EntitlementManifest) -> None` (raises `ValueError` if namespace already owned by a different `app_id`; re-registering the same app replaces it),
  `rejected: Dict[str, List[str]]` (app_id -> error strings, filled by `register_raw`),
  `register_raw(app_id: str, payload: Mapping[str, Any]) -> bool` (validates; on `ValidationError` records into `rejected`, returns False, never raises),
  `get_action(action_id) -> Optional[ActionDef]`, `action_for_mcp_tool(tool_name) -> Optional[str]` (returns the single action whose `mcp_tools` contains the tool; `register` raises `ValueError` if two actions claim the same tool name), `get_manifest(app_id)`, `bundle_contains(app_id, bundle_id, action_id) -> bool` (False for unknown),
  `list_apps() -> List[str]`, `get_bundle(app_id, bundle_id) -> Optional[BundleDef]`.
- Thread-safe with a `threading.Lock`.
- Tests: namespace collision rejected; `register_raw` with bad payload records error and leaves registry unchanged; `bundle_contains` False for unknown app/bundle/action; replace-on-reregister; concurrent registers do not raise.
- Verify: pytest + mypy strict. Commit.

**T05 Plugin integration** - Read first: `plugin_engine/base_plugin.py`, `plugin_engine/loader.py`, `tests/unit/test_cartridge_db_binding.py` (to copy fake-cartridge style). Files: `base_plugin.py`, `loader.py`, `tests/unit/test_dea_plugin_integration.py`.
- In `BaseApplication` add a **concrete** (non-abstract) method:
  `def get_entitlement_manifest(self) -> Optional[Dict[str, Any]]` - reads JSON from `Path(inspect.getfile(type(self))).parent / settings.ENTITLEMENT_MANIFEST_FILENAME`; returns `None` if the file is absent; raises `ValueError(...) from err` on invalid JSON. Returns the raw dict (the registry validates).
- In `PluginLoader` add `def register_entitlements(self, registry: EntitlementRegistry) -> None`: for each loaded app, call `get_entitlement_manifest()`; wrap each app in `try/except Exception` that logs and calls `registry.rejected.setdefault(app_id, []).append(str(exc))` - **a bad manifest must never stop another cartridge loading**. Do NOT call it from `load_all()`; `main.py` calls it (T16).
- Tests: fake cartridge with temp `entitlements.json` registers; cartridge with no file registers nothing; malformed JSON goes to `rejected`; two cartridges with one bad do not interfere.
- Verify: pytest this file **and** `tests/unit/test_cartridge_db_binding.py tests/unit/test_architectural_boundaries.py`. Commit.

### PHASE 2 - PERSISTENCE

**T07 DB models** - Read first: `identity/models.py` (style), `db/base.py`. Files: `entitlements/db_models.py` (Section 4.3), `tests/unit/test_dea_db_models.py`.
- Tests: `Base.metadata.create_all(engine, tables=[...4 tables...])` on a `tmp_path` SQLite file creates exactly those tables; unique constraints enforced (`IntegrityError`) for duplicate group name per tenant and duplicate membership; same group name in two tenants is allowed.
- Verify: pytest + mypy strict. Commit.

**T08 Repository** - Files: `entitlements/repository.py`, `tests/unit/test_dea_repository.py`.
- `class EntitlementRepository.__init__(self, engine: Optional[Engine] = None)`: if None use `DatabaseManager.get_instance().get_engine()`; build `sessionmaker(bind=engine, expire_on_commit=False)`; call `Base.metadata.create_all(bind=engine, tables=[the 4 tables])` only. Every method opens `with self._session_factory() as session:` and **takes `tenant_id` as its first argument and filters by it in every query**.
- Methods (all return plain Pydantic/dataclass DTOs, never ORM objects): `create_unit(tenant_id, name, label, parent_id) -> UnitDTO` (reject parent from another tenant, reject cycles/depth > limit with `ValueError`), `list_units`, `unit_in_subtree(tenant_id, root, candidate) -> bool`, `create_group(tenant_id, name, description, kind)` (`kind` is `"USER"` or `"SERVICE"`), `list_groups`, `add_member`, `remove_member`, `list_members`, `group_ids_for_principal(tenant_id, principal_id, kind) -> List[str]` (**only returns groups whose `kind` equals the argument**, so an API-key principal never inherits a human's USER-group grants even if the id strings collide), `create_binding(...) -> BindingDTO` (reject duplicate *active* binding with `ValueError`; UNIT requires `scope_unit_id` that exists in tenant; non-UNIT requires `scope_unit_id is None`), `revoke_binding(tenant_id, binding_id, revoked_by) -> bool` (soft), `active_bindings_for_groups(tenant_id, group_ids)`, `list_active_bindings(tenant_id)`, `count_active_bindings(tenant_id) -> int`, `bindings_for_group`.
- Tests (**mandatory**): CRUD happy paths; **cross-tenant isolation for every read method** (tenant B cannot see/modify tenant A's rows, and `create_binding` with a group id from another tenant raises); subtree: root itself true, child true, grandchild true, sibling false, depth limit exceeded -> False; cycle creation rejected; duplicate active binding rejected, but allowed after revoke; revoked bindings excluded from `active_bindings_for_groups` and `count_active_bindings`; empty DB returns empty lists / 0 (clean-slate).
- Verify: pytest + mypy strict. Commit.

**T09 Alembic migration** - Read first: `migrations/env.py`, `migrations/versions/001_initial_schema.py`, `alembic.ini`. Files: `migrations/versions/002_entitlements.py`, `tests/unit/test_dea_migration.py`.
- Create the same 4 tables and indexes with `op.create_table`; `downgrade()` drops them in reverse order. `down_revision = "001"` (use the exact revision string found in 001).
- Test: programmatically run `alembic upgrade head` against a temp SQLite URL (follow how `env.py` reads the URL; if it cannot be overridden, test via `command.upgrade` with `config.set_main_option`), assert 4 tables exist; run `downgrade -1`, assert they are gone. If env.py makes this impossible without editing it, STOP and report.
- Verify: pytest this file. Commit.

### PHASE 3 - DECISION ENGINE

**T10 Audit wrapper** - Files: `entitlements/audit.py`, `tests/unit/test_dea_audit.py`.
- `class EntitlementAuditor.__init__(self, engine: Optional[AuditEngine] = None)`; `def emit(self, event: str, tenant_id: str, principal_id: str, detail: Mapping[str, Any], denied: bool) -> None` calls `record_event(action_type=event, payload_summary={"tenant_id":..., **detail}, operator_id=principal_id, layer_0_status="DENIED" if denied else "PASSED", layer_1_model="deterministic_rbac", layer_1_confidence=1.0, layer_2_gate_status="DENIED" if denied else "APPROVED")`. Failure inside `record_event` is logged and swallowed **only here** (auditing must not crash a request) but returns normally; never include secrets in `detail`.
- Constants for event names live in this module as an `Enum` (`AuditEvent`): `ENTITLEMENT_DENIED, ENTITLEMENT_SHADOW_DIFF, ENTITLEMENT_LEGACY_FALLBACK, ENTITLEMENT_ALLOWED_HIGH, ENTITLEMENT_BINDING_CREATED, ENTITLEMENT_BINDING_REVOKED, ENTITLEMENT_GROUP_CHANGED, ENTITLEMENT_BUNDLE_DRIFT, ENTITLEMENT_MANIFEST_REJECTED`.
- Tests with a mocked `AuditEngine`: correct kwargs for denied/allowed; exception inside engine does not propagate.
- Verify: pytest + mypy strict. Commit.

**T11 Evaluator** - Files: `entitlements/evaluator.py`, `tests/unit/test_dea_evaluator.py`.
- `class EntitlementEvaluator` implements `AuthorizationPort`; constructor `(repository, registry)`. Implement exactly Section 4.5. Never raises for normal denials; repository exceptions propagate (the **gate** converts them).
- Tests (**mandatory list**, each a function): API-key context (`auth_strategy="api_key"`) only sees SERVICE groups and a human (USER) context never sees SERVICE groups, even when `principal_id` strings are identical; unauthenticated deny; unknown action deny; no groups deny; group but no binding deny; TENANT allow; SELF allow when owner==principal, deny when owner differs, deny when resource None; UNIT allow at root, child, grandchild; UNIT deny sibling unit, deny when `unit_id=None`; binding for bundle that no longer exists in registry is ignored; revoked binding ignored; user in two groups gets union of grants; **cross-tenant**: principal with bindings in tenant A is denied in tenant B; matched_binding_ids populated.
- Verify: pytest + mypy strict. Commit.

**T12 Gate + dependencies** - Read first: `rbac/permissions.py` (pattern for FastAPI dependency factories). Files: `entitlements/gate.py`, `entitlements/dependencies.py`, `tests/unit/test_dea_gate.py`.
- `EntitlementGate(evaluator, repository, auditor, registry, mode_provider: Callable[[], str])` with `check(ctx, action_id, resource=None, legacy_allowed=True) -> Decision` implementing Section 4.4 exactly, and `enforce(...)` which raises `EntitlementDeniedError` when `check(...).allowed` is False.
- Module `dependencies.py` exposes `get_gate() -> EntitlementGate` / `set_gate(gate)` and `get_registry() -> EntitlementRegistry` / `set_registry(registry)` (module-level holders set by `main.py`; if unset, `get_gate()` returns a gate in `off` mode so unit tests and clean boots work). `require_action(action_id: str, resource_resolver: Optional[Callable[[Request], ResourceRef]] = None) -> Callable[..., SecurityContext]` is a FastAPI dependency factory that obtains the context exactly like `require_app` does (`get_web_security_context`), calls `get_gate().enforce(...)`, converts `EntitlementDeniedError` to `HTTPException(403, detail=<reason code only, no internals>)`, and returns ctx. `authorize_action(ctx, action_id, resource=None) -> None` for non-HTTP callers (raises `EntitlementDeniedError`).
- Tests: **one test per row of the Section 4.4 table** (7 rows incl. both enforce rows); evaluation exception under `enforce` -> deny `EVALUATION_ERROR`; under `shadow` -> legacy decides and no exception; mode `off` never calls evaluator (mock asserts 0 calls); `require_action` returns 403 body without stack/reason internals; unset gate behaves as `off`.
- Verify: pytest + mypy strict. Commit.

> **GATE A (end of Phase 3):** run `pytest tests/unit -q`; passes = `BASELINE + new tests`, zero failures; `mypy --strict core_platform/app/entitlements` clean; `pytest --cov=core_platform/app/entitlements --cov-report=term-missing tests/unit/test_dea_*.py` shows >= 90% for the package. Report numbers, then continue.

### PHASE 4 - ADMIN API + UI

**T14 Admin service** - Files: `entitlements/admin_service.py`, `tests/unit/test_dea_admin_service.py`.
- `EntitlementAdminService(repository, registry, auditor)` with methods that all take `ctx: SecurityContext` (tenant from `ctx.tenant_id`, actor from `ctx.principal_id`): `create_unit`, `create_group(ctx, name, description, kind)`, `add_member`, `remove_member`, `bind_bundle(ctx, group_id, app_id, bundle_id, scope, scope_unit_id, confirm_high_risk) -> BindingDTO`, `unbind(ctx, binding_id)`, `effective_access(ctx, principal_id) -> List[EffectiveActionDTO]`.
- `bind_bundle` validations in order: group exists in tenant; app/bundle exist in registry; **if the group `kind` is `SERVICE` and the bundle derived risk is HIGH -> `ValueError("SERVICE_GROUP_CANNOT_HOLD_HIGH_RISK")` (no confirmation can override this)**; scope in bundle `allowed_scopes`; derived risk HIGH requires `confirm_high_risk` else `ValueError("HIGH_RISK_CONFIRMATION_REQUIRED")`; stores `bundle_digest`; audits `ENTITLEMENT_BINDING_CREATED` with bundle id, scope, risk, digest. `unbind` audits `ENTITLEMENT_BINDING_REVOKED`. Group/member changes audit `ENTITLEMENT_GROUP_CHANGED`.
- `effective_access`: for the principal, expand all active bindings into `(action_id, plain_title, app_title, scope, scope_unit_name, via_bundle, via_group)` rows; skip unknown bundles.
- Tests: each validation failure (incl. SERVICE group + HIGH bundle rejected even with `confirm_high_risk=true`); audit called with the expected event; HIGH confirm flow; effective access union & scope labels; tenant isolation (ctx tenant A cannot bind group of B).
- Verify: pytest + mypy strict. Commit.

**T15 Catalog view model** - Files: `entitlements/catalog_view.py`, `tests/unit/test_dea_catalog_view.py`.
- `BundleCardView` (Pydantic): `app_id, app_title, bundle_id, title, summary, who_its_for, can_do: List[str]` (action `plain_title`s), `cannot_do, touches: List[str]` (deduplicated union of action `touches`), `risk: RiskLevel` (derived), `risk_label: str` (text: `"Low risk"`, `"Operational risk"`, `"High governance"` - these three strings come from `Settings`-free constants in this module's `Enum` mapping; they are UI vocabulary, not business data), `allowed_scopes: List[Scope]`, `scope_labels: Dict[str,str]` (`SELF -> "Only their own records"`, `UNIT -> "Their department/unit and sub-units"`, `TENANT -> "Whole organization"`), `default_scope`, `action_count`, `assigned_group_count`, `conflicts_with_titles`, `drifted_binding_count`.
- `build_catalog(tenant_id, registry, repository, enabled_app_ids) -> List[BundleCardView]`: only apps in `enabled_app_ids`; `drifted_binding_count` = active bindings whose stored digest != current digest.
- Tests: risk derived (not declared); drift counted; apps outside `enabled_app_ids` omitted; empty registry -> `[]` (clean slate).
- Verify: pytest + mypy strict. Commit.

**T16 Routes + wiring** - Read first: `admin_shell/routes.py` (auth/tenant pattern, how `users` page and POST handlers are written), `tests/unit/test_every_page_tenant_aware.py`, `tests/unit/test_auth_rbac_full.py` (how TestClient + admin cookie are built), `core_platform/main.py`. Files: `admin_shell/entitlements_routes.py`, `core_platform/main.py` (EDIT: only to create registry/repository/gate, call `plugin_loader.register_entitlements(registry)` after `load_all()`, call `set_gate`, include the router), `tests/unit/test_dea_routes.py`.
- Router prefix `/admin/entitlements`, all routes `Depends(require_admin)` (D12) and tenant from `resolve_effective_tenant_info(request)`. Routes: `GET /` (page, T17), `GET /api/catalog`, `GET/POST /api/units`, `GET/POST /api/groups`, `POST /api/groups/{id}/members`, `DELETE /api/groups/{id}/members/{principal}`, `POST /api/bindings`, `POST /api/bindings/{id}/revoke`, `GET /api/effective-access?principal_id=`. Request/response bodies are Pydantic models. Map `ValueError` to 400 with a stable `code` string; never leak stack traces.
- Startup: after `register_entitlements`, for every `registry.rejected` entry emit `ENTITLEMENT_MANIFEST_REJECTED`; for every tenant binding with digest drift emit `ENTITLEMENT_BUNDLE_DRIFT` (skip silently if the table is empty).
- Tests: 401 without auth; 403 for non-admin; tenant isolation through API; HIGH-risk bind without confirm -> 400 `HIGH_RISK_CONFIRMATION_REQUIRED`; happy path create unit/group/member/bind/revoke; `GET /api/catalog` returns cards for a fake registry.
- Verify: pytest this file **and** `tests/unit/test_every_page_tenant_aware.py tests/unit/test_auth_rbac_full.py`. Commit.

**T17 Admin page (UI)** - Read first: `admin_shell/templates/users.html` (copy its skeleton, nav, Tailwind usage). Files: `admin_shell/templates/entitlements.html`, `tests/unit/test_dea_ui.py`.
- Standalone HTML like `users.html`, ASCII only, no external JS beyond what `users.html` already uses. Sections: **1. Groups** (list/create, add member from tenant user list, remove), **2. Org units** (tree list with create child; shows the customer-chosen `label`), **3. Bundle catalog + assignment**, **4. Effective access checker**.
- **Group kinds in the UI:** the *Create group* form has a **Group type** selector: People (kind USER, members picked from the tenant user list) or AI assistants and integrations (kind SERVICE, members picked from this tenant's API keys via get_api_key_manager().list_keys() filtered by tenant, showing the key *label*, never the key or its hash). When a SERVICE group is selected in the assignment dialog, HIGH-governance bundle cards are disabled with the text Not available to AI assistants. Show a short help line under the selector explaining the difference in plain words.
- **Bundle card (the clarity requirement).** Each card shows, in this order: title; app name; **risk badge** (text + color + shape - never color alone; `Low risk` green circle, `Operational risk` amber triangle, `High governance` red diamond); **scope badge** with its plain-language label; `summary`; "Who it is for"; **"They CAN"** bullet list; **"They CANNOT"** bullet list (always rendered for MEDIUM/HIGH); "Touches" chips; "Currently assigned to N groups"; amber "Changed since granted - review" chip when `drifted_binding_count > 0`; amber "Conflicts with: <titles>" notice when the group already holds a conflicting bundle.
- **Assignment dialog:** pick group -> pick scope (only `allowed_scopes`; for UNIT pick the unit) -> **preview sentence**: *"Members of <group> will be able to <can_do list> for <scope label>. They will not be able to <cannot_do list>."* -> if HIGH: red box + checkbox "I understand this grants high-governance access" that must be ticked to enable the button (sends `confirm_high_risk=true`).
- Accessibility: badges have text, dialog is keyboard operable, `aria-label` on icon-only buttons.
- Tests: render page with a fake catalog and assert presence of each badge text, "They CAN", "They CANNOT", preview-sentence template, and the high-risk checkbox; assert no non-ASCII bytes in the template file.
- Verify: pytest this file + `tests/unit/test_every_page_tenant_aware.py`. Commit.

> **GATE B (end of Phase 4):** full `pytest tests/unit -q` green; mypy strict clean on `core_platform/app/entitlements` and `admin_shell/entitlements_routes.py`; manually start the app (`.\.venv\Scripts\python.exe -m uvicorn core_platform.main:app --port 8010`), open `/admin/entitlements` and confirm the page loads with an empty catalog and no 500 (clean-slate). Report.

### PHASE 5 - CARTRIDGE ADOPTION (shadow mode only; do not switch any default to `enforce`)

**T18 mail_organizer manifest** - Files: `apps/mail_organizer/entitlements.json`, `apps/mail_organizer/MANIFEST.in` (add `include entitlements.json`), `apps/mail_organizer/pyproject.toml` (package-data include if the file lists package data - read it first), `tests/unit/test_dea_manifest_mail.py`. Build the JSON from the action and bundle tables in Section 6.1 (one JSON object: `schema_version: 1`, `namespace`, `app_title`, `actions[]`, `bundles[]`). Write `plain_description` (20-300 chars) and `summary` (20-200 chars) yourself in plain, non-technical English for a customer administrator.
- Tests: file validates with `EntitlementManifest`; registers in a fresh registry via `register_raw`; every `require_action` literal used in mail routes (T19) exists in it (written in T19 and re-run).

**T19 mail routes gating** - Read first: `apps/mail_organizer/ui/routes.py`. Files: that file only + `tests/unit/test_dea_mail_gating.py`.
- Add `dependencies=[Depends(require_action("<action_id>"))]` per route: `/dashboard,/triage,/drafts,/accounts` -> `mail:inbox:view`; `/rules` -> `mail:rules:view`; `POST /api/simulate` -> `mail:inbox:triage`; `/pm-queue` -> `mail:pm_task:view`; approve -> `mail:pm_task:approve`; reject -> `mail:pm_task:reject`; `/accounts/reauth` and `/accounts/callback` -> `mail:account:connect`. Router-level `require_app` stays. Do not alter handler bodies.
- Tests (mode via monkeypatching the gate's `mode_provider`): `off` and `shadow`: existing behaviour unchanged (run the existing `tests/unit/test_mail_organizer_ui.py` too); `enforce` + onboarded tenant + user without binding -> 403 on approve; with `project_lead` binding at TENANT scope -> 200/expected; `enforce` + non-onboarded tenant -> legacy behaviour.
- Verify: pytest new file + `tests/unit/test_mail_organizer_ui.py tests/unit/test_mail_organizer_deep_coverage.py tests/unit/test_mail_organizer_extended.py`. Commit.

**T20 temperature_marker manifest** - same pattern; JSON from Section 6.2. Files: `apps/temperature_marker/entitlements.json`, its `MANIFEST.in`/`pyproject.toml` data include, `tests/unit/test_dea_manifest_temperature.py`.

**T21 temperature routes + WhatsApp gating** - Read first: `apps/temperature_marker/ui/routes.py`, `apps/temperature_marker/graph/nodes/layer0_auth_guard.py`, `apps/temperature_marker/services/whatsapp_handler.py`. Files: those that need decorators + `tests/unit/test_dea_temperature_gating.py`.
- Route mapping: `/fleet`,`/api/fleet` -> `temperature:fleet:view`; `/monitoring` -> `temperature:monitoring:view`; `/wizard`,`POST /api/simulate` -> `temperature:checkin:simulate`; `/approvals`,`/api/approvals` -> `temperature:operator:view`; approve/reject -> `temperature:operator:approve`; `/api/members` GET -> `temperature:member:view`; members POST/update/reassign/forget-photo -> `temperature:member:manage`; member photo + `/media` -> `temperature:photo:view`; kiosks POST/calibrate/config -> `temperature:kiosk:manage`; `/verify-location`,`POST /api/verify-location` -> `temperature:location:verify`; `/api/records/{id}/resolve` -> `temperature:attendance:resolve`; `/api/messages/{id}/resolve` -> `temperature:message:resolve`; `/api/alerts/{id}/acknowledge` -> `temperature:alert:acknowledge`.
- WhatsApp: in `layer0_auth_guard.py` call `authorize_action(ctx, "temperature:telemetry:record", ResourceRef(owner_principal_id=<sender principal>, unit_id=<kiosk unit if known else None>))`. **Behaviour under `off`/`shadow` must be byte-identical to today.** If the node has no `SecurityContext`, build one with `AuthResolver.resolve_whatsapp(phone, tenant_id)`. Read the node fully first; if its structure makes this unsafe, STOP and report instead of improvising.
- Tests: same matrix as T19 plus a WhatsApp-path test in `shadow` mode showing identical results and a `ENTITLEMENT_SHADOW_DIFF` audit when the principal has no binding.
- Verify: pytest new file + `tests/unit/test_temperature_*` / existing temperature and layer0 tests (`Get-ChildItem tests/unit -Filter "test_*temperature*"`, `test_layer0*`, `test_whatsapp*`). Commit.

**T21b MCP gating (API-key callers)** - Read first: `core_platform/app/mcp_server/server.py` (`_handle_tools_call`), `core_platform/app/mcp_server/tool_aggregator.py`, `core_platform/app/auth/models.py`, `core_platform/app/auth/api_keys.py`, `tests/unit/test_mcp_server_full.py`. Files: `mcp_server/server.py`, `tests/unit/test_dea_mcp_gating.py`.
- In `_handle_tools_call`, **before** dispatching the tool handler, call `registry.action_for_mcp_tool(tool_name)` (registry is reachable the same way the gate is, via `dependencies.get_registry()` added in T12). Then:
  - action found -> `authorize_action(ctx, action_id)` (no resource; tenant-wide check). On `EntitlementDeniedError` return the existing JSON-RPC error helper `_error_response(...)` with message `"Forbidden"` and no internals.
  - **no action mapped** to this tool -> gate decides with a synthetic `Decision`: in `enforce` for an onboarded tenant, DENY (fail closed); in `off`/`shadow`, allow and in `shadow` audit `ENTITLEMENT_SHADOW_DIFF` with `detail={"unmapped_mcp_tool": tool_name}`.
- Principal kind: `SecurityContext.auth_strategy == "api_key"` => principal kind `SERVICE`; everything else => `USER` (see T08/T11).
- MCP tools in the manifests are mapped through the `mcp_tools` field of `ActionDef` (Section 6). `tools/list` must NOT hide tools in `shadow`; in `enforce` it may filter to permitted tools (optional; skip if it complicates `test_mcp_server_full.py`).
- Tests: shadow = identical responses to today (run `tests/unit/test_mcp_server_full.py` unchanged); enforce + onboarded tenant + key principal in no group -> JSON-RPC forbidden for `mail_approve_pm_task`; with the principal in a SERVICE group holding a bundle that has that action -> tool executes; unmapped tool denied in enforce; API-key principal whose id equals a human's phone number does NOT inherit that human's USER-group grants.
- Verify: pytest new file + `tests/unit/test_mcp_server_full.py tests/unit/test_mail_organizer_*.py`. Commit.

> **GATE C (end of Phase 5):** full `pytest tests/unit -q` green (>= BASELINE + all new); no existing test modified.

### PHASE 6 - QUALITY GATES & DOCS

**T22 Consistency tests** - Files: `tests/unit/test_dea_consistency.py`.
- (a) every `apps/*/entitlements.json` validates; (b) AST-scan `apps/**/*.py` for `require_action("...")` / `authorize_action(..., "...")` string literals and assert each is a declared action of some manifest; (c) every declared action is referenced by at least one call site **or** is listed in a `"reserved_for": [...]` allowlist inside the manifest-test file with a comment (prevents dead actions); (d) no `.py` under `core_platform/app/entitlements` imports `apps`; (e) no wildcard characters (`*`) in any manifest action id; (f) every MCP tool name registered by a cartridge (`get_mcp_tools()` of `mail_organizer` and `temperature_marker`, imported inside the test) appears in exactly one action `mcp_tools`, or in a `reserved_for` allowlist with a comment.

**T23 Live benchmark** - Read first: `run_live_benchmark.py`, `tests/live_benchmark/live_evaluator.py`; locate the catalog with `Get-ChildItem -Recurse -Filter benchmark_catalog.json`. Add safety cases: cross-tenant denial; SELF scope denial; UNIT sibling denial; HIGH-risk bind without confirmation rejected; evaluator exception in enforce -> deny; non-onboarded tenant falls back to legacy. All are **hard-safety** cases. Run `python run_live_benchmark.py --quality-gate`; required: 100% safety, >= 80% functional, reports written.

**T24 Docs** - Files: `ARCHITECTURE.md` (new section "Decentralized Entitlements"), `USER_MANUAL.md` (customer-admin section: groups, units, bundles, risk badges, shadow vs enforce), `OPERATIONS_MANUAL.md` (how to read `ENTITLEMENT_SHADOW_DIFF`, how to promote to `enforce`, rollback = set `off`), `issues/ISSUE-009_fail_open_required_roles.md` (record the pre-existing fail-open in `_get_required_roles`; no code change). Append only; preserve existing text.

**T25 Final gate (Definition of Done)** - all must be true and reported with numbers:
1. `pytest tests/unit -q`: all pass; count = BASELINE + new; **zero modified existing tests**.
2. `mypy --strict core_platform/app/entitlements core_platform/app/admin_shell/entitlements_routes.py`: 0 errors.
3. Coverage of `core_platform/app/entitlements` >= 90% lines.
4. `test_architectural_boundaries.py` and `test_zero_secret_leak_guard.py` pass.
5. `python run_live_benchmark.py --quality-gate`: 100% safety, >= 80% functional.
6. `git log` shows one commit per task, **nothing pushed**. Present the commit list to the user and wait for an explicit "go" before any push.

---

## 6. MANIFEST CONTENT (cartridge-owned data; copy then adjust only if a route listed in Section 1.1 differs)

### 6.1 `apps/mail_organizer/entitlements.json`

Fields per action: `action_id, plain_title, plain_description, effect, risk, touches`. Fields per bundle: `bundle_id, title, summary, who_its_for, cannot_do, allowed_scopes, default_scope, actions, conflicts_with`.

Actions (namespace `mail`, app_title `AI Email and Calendar Organizer`):

| action_id | effect | risk | plain_title | touches |
| :--- | :--- | :--- | :--- | :--- |
| `mail:inbox:view` | READ | LOW | View the email dashboard, triage and drafts | mailbox data |
| `mail:inbox:triage` | WRITE | LOW | Run AI triage on an email | AI model |
| `mail:draft:stage` | WRITE | LOW | Prepare a draft reply for review | drafts |
| `mail:rules:view` | READ | LOW | See VIP and whitelist rules | rules |
| `mail:pm_task:view` | READ | LOW | See tasks waiting for approval | task queue |
| `mail:pm_task:approve` | APPROVE | MEDIUM | Approve a task and send it to the project tool | Jira, Linear |
| `mail:pm_task:reject` | APPROVE | MEDIUM | Reject a proposed task | task queue |
| `mail:account:connect` | CONFIGURE | HIGH | Connect or re-authorize a mailbox | Google account |

Bundles:

| bundle_id | actions | allowed_scopes (default first) | cannot_do (required if MEDIUM+) |
| :--- | :--- | :--- | :--- |
| `inbox_user` | inbox:view, inbox:triage, draft:stage, rules:view | SELF, UNIT, TENANT (SELF) | (none required - LOW) |
| `project_lead` | inbox:view, inbox:triage, draft:stage, rules:view, pm_task:view, pm_task:approve, pm_task:reject | UNIT, TENANT (UNIT) | "Connect or change mailboxes", "Change VIP or whitelist rules" |
| `mailbox_admin` | account:connect, inbox:view | TENANT (TENANT) | "Approve or reject project tasks" |

> Note: `mail:draft:stage` is exercised via the MCP tool `mail_stage_draft_reply` (mapped in Section 6.3), so it needs no allowlist entry.

### 6.2 `apps/temperature_marker/entitlements.json`

Namespace `temperature`, app_title `Industrial Temperature and Attendance Marker`.

| action_id | effect | risk | plain_title | touches |
| :--- | :--- | :--- | :--- | :--- |
| `temperature:telemetry:record` | WRITE | LOW | Submit a duty check-in and chiller temperature reading | kiosk, WhatsApp |
| `temperature:location:verify` | WRITE | LOW | Confirm their location at a kiosk | GPS |
| `temperature:checkin:simulate` | WRITE | LOW | Try the check-in simulator | none |
| `temperature:fleet:view` | READ | LOW | View the kiosk fleet and its status | kiosks |
| `temperature:monitoring:view` | READ | LOW | View live monitoring and records | records |
| `temperature:operator:view` | READ | LOW | See operators waiting for onboarding approval | roster |
| `temperature:member:view` | READ | LOW | View the team member list | roster |
| `temperature:photo:view` | READ | MEDIUM | View a team member's stored photo | biometric data |
| `temperature:operator:approve` | APPROVE | MEDIUM | Approve or reject a new operator | roster |
| `temperature:attendance:resolve` | APPROVE | MEDIUM | Resolve a flagged attendance or temperature record | records |
| `temperature:message:resolve` | APPROVE | MEDIUM | Resolve an operator's escalated message | WhatsApp |
| `temperature:alert:acknowledge` | APPROVE | MEDIUM | Acknowledge a temperature alert | alerts |
| `temperature:kiosk:manage` | CONFIGURE | HIGH | Add kiosks, move locations, change kiosk settings | kiosks, GPS |
| `temperature:member:manage` | CONFIGURE | HIGH | Add, edit, reassign or erase a team member | roster, biometric data |

> `temperature:operator:approve` also covers reject (single action for both). Add `temperature:operator:view`'s route list accordingly.

Bundles: `field_operator` = telemetry:record, location:verify (SELF, default SELF; allowed SELF only); `shift_supervisor` = field_operator actions + fleet:view, monitoring:view, operator:view, member:view, photo:view, operator:approve, attendance:resolve, message:resolve, alert:acknowledge, checkin:simulate (UNIT, TENANT; default UNIT; cannot_do: "Add or change kiosks", "Add, edit or erase team members"); `fleet_engineer` = fleet:view, monitoring:view, member:view, kiosk:manage, member:manage (TENANT; default TENANT; cannot_do: "Approve operators", "Resolve attendance or temperature records"). Add `conflicts_with: ["fleet_engineer"]` on `shift_supervisor` and vice versa (UI shows the separation-of-duties warning).
> **Deferred:** `haccp_auditor` - no audit-export route exists. Add later together with that route.

### 6.3 MCP tool mapping (add as mcp_tools on the matching action in each manifest)

| MCP tool | action_id |
| :--- | :--- |
| mail_search_threads, mail_get_thread_context, mail_check_calendar_availability | mail:inbox:view |
| mail_stage_draft_reply | mail:draft:stage |
| mail_get_pending_pm_tasks | mail:pm_task:view |
| mail_approve_pm_task | mail:pm_task:approve |
| 	emperature_get_latest_reading, 	emperature_check_kiosk_health, 	emperature_list_fleet_status | 	emperature:fleet:view |
| 	emperature_list_pending_onboarding_approvals | 	emperature:operator:view |
| 	emperature_approve_operator | 	emperature:operator:approve |

SERVICE-kind groups may only receive bundles whose derived risk is LOW or MEDIUM. Because the existing manifests keep project_lead (MEDIUM) and shift_supervisor (MEDIUM), an AI assistant key can be bound to those. HIGH bundles (mailbox_admin, leet_engineer) cannot be bound to SERVICE groups by design.

---

## 7. TEST MATRIX - SECURITY-CRITICAL (must all exist before Gate C)

| Risk | Where covered |
| :--- | :--- |
| Cross-tenant read/write leakage | T08, T11, T14, T16 |
| Fail-open on evaluator error | T12 |
| Silent privilege widening on cartridge upgrade | T15 (drift), T16 (startup audit) |
| Cartridge understating risk | T02 |
| Cartridge squatting another namespace | T04 |
| Dead/undeclared actions | T22 |
| Admin lockout | T16 (routes use legacy `require_admin`) |
| Existing tenants broken by rollout | T12 (`shadow`, non-onboarded), T19, T21 |
| HIGH-risk grant without conscious confirmation | T14, T16, T17 |
| Bad manifest breaking other cartridges | T05 |
| API-key principal inheriting a human's grants (same `principal_id` string) | T08, T11 (group `kind` separation) |
| AI/service principal holding a HIGH-risk bundle | T14, T16 |
| MCP tool with no declared action slipping through | T21b, T22 (fail closed in `enforce`) |

---

## 8. FAILURE PLAYBOOK

| Symptom | Likely cause | Action |
| :--- | :--- | :--- |
| License-header test fails | new file lacks exact header | paste header from Section 0.5 |
| `test_every_page_tenant_aware` fails | page/route ignores tenant | use `resolve_effective_tenant_info(request)` as in other admin routes |
| `mypy --strict` error on SQLAlchemy | missing `Mapped[...]` | use `Mapped[Optional[str]]` + `mapped_column(...)` as in `identity/models.py` |
| Tables not found in tests | forgot `create_all(tables=[...])` in repository init | see T08 |
| Existing mail/temperature test now fails | gate not in `off`/`shadow` or handler body edited | revert handler edits; only add `dependencies=[...]` |
| `UnicodeEncodeError` on Windows | non-ASCII in print/template | ASCII only |
| Anything not covered here | - | STOP and report the exact command and output |

## 9. LATER PHASES (not part of this plan)

Phase 7: IdP sync (Entra ID, Google Workspace, SCIM) filling `external_ref`. Phase 8: custom bundles composed by the admin + hard SoD rules. Phase 9: `haccp_auditor` with audit-export route. Phase 10: optional swap of the evaluator behind `AuthorizationPort` for OpenFGA/Cedar if relationship queries ("list everything this user can see") become necessary.
