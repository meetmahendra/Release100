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

"""Customer-admin API for groups, org units and bundle assignment (Plan 10, T16).

All routes require the legacy admin check (never entitlement-gated, so an admin
can never be locked out) and are scoped to the effective tenant.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core_platform.app.auth.csrf import verify_csrf_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.config import settings
from core_platform.app.entitlements import dependencies as deps
from core_platform.app.entitlements.admin_service import EffectiveActionDTO, EntitlementAdminService
from core_platform.app.entitlements.audit import AuditEvent, EntitlementAuditor
from core_platform.app.entitlements.catalog_view import BundleCardView, build_catalog
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import (
    BindingDTO,
    EntitlementRepository,
    GroupDTO,
    MemberDTO,
    UnitDTO,
)
from core_platform.app.rbac.permissions import require_admin

logger = logging.getLogger("core_platform.admin_shell.entitlements")

router = APIRouter(prefix="/admin/entitlements", tags=["Entitlements"])


# -- request bodies --------------------------------------------------------------------------

class UnitCreate(BaseModel):
    """Create an organizational unit."""

    name: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=60)
    parent_id: Optional[str] = None


class GroupCreate(BaseModel):
    """Create a group."""

    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=300)
    kind: str = Field(default="USER", pattern="^(USER|SERVICE)$")


class MemberAdd(BaseModel):
    """Add a member to a group."""

    principal_id: str = Field(min_length=1, max_length=64)


class BindingCreate(BaseModel):
    """Assign a bundle to a group."""

    group_id: str
    app_id: str
    bundle_id: str
    scope: Scope
    scope_unit_id: Optional[str] = None
    confirm_high_risk: bool = False


class DirectoryPerson(BaseModel):
    """A selectable person (phone number is the principal id)."""

    principal_id: str
    name: str


class DirectoryService(BaseModel):
    """A selectable API key, shown by label only."""

    principal_id: str
    label: str


class DirectoryView(BaseModel):
    """People and API keys of the tenant, for the member pickers."""

    people: List[DirectoryPerson]
    services: List[DirectoryService]


# -- helpers ----------------------------------------------------------------------------------

def _tenant_ctx(request: Request, ctx: SecurityContext) -> tuple[SecurityContext, Optional[Any]]:
    """Return the context re-scoped to the effective tenant, and the tenant record."""
    from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info

    tenant_id, _name, tenant_obj = resolve_effective_tenant_info(request, ctx)
    return ctx.model_copy(update={"tenant_id": tenant_id}), tenant_obj


def _require_csrf(request: Request) -> None:
    """Reject a mutating request whose CSRF token does not match."""
    if not verify_csrf_token(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")


def _service(repo: EntitlementRepository) -> EntitlementAdminService:
    """Build the admin service from the process-wide holders."""
    return EntitlementAdminService(repo, deps.get_registry(), EntitlementAuditor())


def _bad_request(err: ValueError) -> HTTPException:
    """Map a domain ValueError to a 400 with a stable code only."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": str(err)})


def _enabled_app_ids(tenant_obj: Optional[Any]) -> List[str]:
    """Apps the tenant may use: platform-enabled apps intersected with tenant entitlements."""
    registry = deps.get_registry()
    apps = set(registry.list_apps())
    if settings.ENABLED_APPLICATIONS is not None:
        apps &= set(settings.ENABLED_APPLICATIONS)
    allowed = getattr(tenant_obj, "allowed_cartridges", None)
    if allowed is not None:
        apps &= set(allowed)
    return sorted(apps)


# -- read routes ------------------------------------------------------------------------------

@router.get("/api/catalog")
def get_catalog(
    request: Request, ctx: SecurityContext = Depends(require_admin)
) -> List[BundleCardView]:
    """Return bundle cards for the tenant's enabled apps."""
    scoped, tenant_obj = _tenant_ctx(request, ctx)
    return build_catalog(
        scoped.tenant_id, deps.get_registry(), deps.get_repository(), _enabled_app_ids(tenant_obj)
    )


@router.get("/api/units")
def list_units(request: Request, ctx: SecurityContext = Depends(require_admin)) -> List[UnitDTO]:
    """List the tenant's organizational units."""
    scoped, _ = _tenant_ctx(request, ctx)
    return deps.get_repository().list_units(scoped.tenant_id)


@router.get("/api/groups")
def list_groups(request: Request, ctx: SecurityContext = Depends(require_admin)) -> List[Dict[str, Any]]:
    """List groups with their members and active bindings."""
    scoped, _ = _tenant_ctx(request, ctx)
    repo = deps.get_repository()
    out: List[Dict[str, Any]] = []
    for group in repo.list_groups(scoped.tenant_id):
        out.append(
            {
                "group": group.model_dump(),
                "members": [m.principal_id for m in repo.list_members(scoped.tenant_id, group.id)],
                "bindings": [
                    b.model_dump(mode="json") for b in repo.bindings_for_group(scoped.tenant_id, group.id)
                ],
            }
        )
    return out


@router.get("/api/directory")
def get_directory(request: Request, ctx: SecurityContext = Depends(require_admin)) -> DirectoryView:
    """List the tenant's people and API-key labels for the member pickers."""
    scoped, _ = _tenant_ctx(request, ctx)
    people: List[DirectoryPerson] = []
    services: List[DirectoryService] = []
    try:
        from core_platform.app.identity.service import get_user_identity_service

        for user in get_user_identity_service().list_users(tenant_id=scoped.tenant_id):
            people.append(DirectoryPerson(principal_id=user.phone_number, name=user.full_name))
    except Exception as err:  # noqa: BLE001 - directory is a convenience; never 500
        logger.warning("[Entitlements] user directory unavailable: %s", err)
    try:
        from core_platform.app.auth.api_keys import get_api_key_manager

        for key in get_api_key_manager().list_keys():
            if key.get("tenant_id") == scoped.tenant_id and not key.get("revoked"):
                services.append(
                    DirectoryService(
                        principal_id=str(key.get("principal_id", "")), label=str(key.get("label", ""))
                    )
                )
    except Exception as err:  # noqa: BLE001
        logger.warning("[Entitlements] API key directory unavailable: %s", err)
    return DirectoryView(people=people, services=services)


@router.get("/api/effective-access")
def effective_access(
    request: Request, principal_id: str, ctx: SecurityContext = Depends(require_admin)
) -> List[EffectiveActionDTO]:
    """Explain what a principal can do, expanded from group bindings."""
    scoped, _ = _tenant_ctx(request, ctx)
    return _service(deps.get_repository()).effective_access(scoped, principal_id)


# -- write routes -----------------------------------------------------------------------------

@router.post("/api/units")
def create_unit(
    request: Request, body: UnitCreate, ctx: SecurityContext = Depends(require_admin)
) -> UnitDTO:
    """Create an organizational unit."""
    _require_csrf(request)
    scoped, _ = _tenant_ctx(request, ctx)
    try:
        return _service(deps.get_repository()).create_unit(scoped, body.name, body.label, body.parent_id)
    except ValueError as err:
        raise _bad_request(err) from err


@router.post("/api/groups")
def create_group(
    request: Request, body: GroupCreate, ctx: SecurityContext = Depends(require_admin)
) -> GroupDTO:
    """Create a group."""
    _require_csrf(request)
    scoped, _ = _tenant_ctx(request, ctx)
    try:
        return _service(deps.get_repository()).create_group(
            scoped, body.name, body.description, body.kind
        )
    except ValueError as err:
        raise _bad_request(err) from err


@router.post("/api/groups/{group_id}/members")
def add_member(
    request: Request, group_id: str, body: MemberAdd, ctx: SecurityContext = Depends(require_admin)
) -> MemberDTO:
    """Add a member to a group."""
    _require_csrf(request)
    scoped, _ = _tenant_ctx(request, ctx)
    try:
        return _service(deps.get_repository()).add_member(scoped, group_id, body.principal_id)
    except ValueError as err:
        raise _bad_request(err) from err


@router.delete("/api/groups/{group_id}/members/{principal_id}")
def remove_member(
    request: Request, group_id: str, principal_id: str, ctx: SecurityContext = Depends(require_admin)
) -> Dict[str, bool]:
    """Remove a member from a group."""
    _require_csrf(request)
    scoped, _ = _tenant_ctx(request, ctx)
    removed = _service(deps.get_repository()).remove_member(scoped, group_id, principal_id)
    return {"removed": removed}


@router.post("/api/bindings")
def create_binding(
    request: Request, body: BindingCreate, ctx: SecurityContext = Depends(require_admin)
) -> BindingDTO:
    """Assign a bundle to a group."""
    _require_csrf(request)
    scoped, _ = _tenant_ctx(request, ctx)
    try:
        return _service(deps.get_repository()).bind_bundle(
            scoped,
            body.group_id,
            body.app_id,
            body.bundle_id,
            body.scope,
            body.scope_unit_id,
            body.confirm_high_risk,
        )
    except ValueError as err:
        raise _bad_request(err) from err


@router.post("/api/bindings/{binding_id}/revoke")
def revoke_binding(
    request: Request, binding_id: str, ctx: SecurityContext = Depends(require_admin)
) -> JSONResponse:
    """Revoke a binding."""
    _require_csrf(request)
    scoped, _ = _tenant_ctx(request, ctx)
    revoked = _service(deps.get_repository()).unbind(scoped, binding_id)
    return JSONResponse(content={"revoked": revoked})


# -- startup audits ---------------------------------------------------------------------------

def emit_startup_audits(
    registry: EntitlementRegistry,
    repository: EntitlementRepository,
    auditor: Optional[EntitlementAuditor] = None,
) -> None:
    """Audit rejected manifests and bundle drift once at startup; never raises."""
    sink = auditor or EntitlementAuditor()
    try:
        for app_id, errors in registry.rejected.items():
            sink.emit(
                AuditEvent.ENTITLEMENT_MANIFEST_REJECTED.value,
                "platform",
                "system",
                {"app_id": app_id, "errors": errors[:5]},
                True,
            )
        for binding in repository.all_active_bindings():
            manifest = registry.get_manifest(binding.app_id)
            if manifest is None or binding.bundle_id not in {b.bundle_id for b in manifest.bundles}:
                continue
            if manifest.bundle_digest(binding.bundle_id) != binding.bundle_digest:
                sink.emit(
                    AuditEvent.ENTITLEMENT_BUNDLE_DRIFT.value,
                    binding.tenant_id,
                    "system",
                    {"binding_id": binding.id, "app_id": binding.app_id, "bundle_id": binding.bundle_id},
                    False,
                )
    except Exception as err:  # noqa: BLE001 - startup audit must never block boot
        logger.error("[Entitlements] startup audit failed: %s", err)
