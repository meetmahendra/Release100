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

"""
DevOps Super-Admin Web Routes (`ops_control_plane/super_admin/routes.py`).

Provides centralized operations dashboard and API endpoints for:
1. Tenant directory and state inspection.
2. Atomic provisioning of new tenants with root admin user.
3. Decommission & Archive with tamper-evident export.
4. Deep-Cloning with live data snapshot replication.
5. Geo-Region and DB Transfer cutover.
6. AES-256-GCM BYOK and Platform-Managed credential configuration.
7. Cryptographic SHA-256 hash chaining audit inspection.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from core_platform.app.auth.csrf import generate_csrf_token, verify_csrf_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.config import settings
from core_platform.app.identity.models import Tenant, TenantAuditLog, TenantConfig, TenantDomain
from core_platform.app.rbac.permissions import get_web_security_context, require_devops
from core_platform.app.ui.templating import build_templates
from core_platform.app.ui.ui_context import Breadcrumb, build_ui_context
from ops_control_plane.devops_vault import DevOpsKeyVault
from ops_control_plane.tenant_lifecycle import GENESIS_HASH, TenantLifecycleManager, compute_audit_hash

logger = logging.getLogger("ops_control_plane.super_admin")

router = APIRouter(
    prefix="/ops",
    tags=["DevOps Super-Admin Control Plane"],
    dependencies=[Depends(require_devops)],
)
templates = build_templates([Path(__file__).parent / "templates"])


def _verify_devops_privilege(ctx: SecurityContext, request: Optional[Request] = None) -> None:
    """Ensure principal possesses super-admin / devops privileges and is on platform host."""
    if request:
        host = request.headers.get("host", "").split(":")[0].strip().lower()
        is_customer_subdomain = False
        if "." in host and not host.replace(".", "").isdigit() and "localhost" not in host:
            parts = host.split(".")
            if len(parts) >= 3 and parts[0] not in ("www", "api", "app", "public", "ops", "ops-admin", "admin"):
                is_customer_subdomain = True

        if is_customer_subdomain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="DevOps Control Plane is not accessible on customer tenant domains.",
            )

    is_authorized = (
        ctx.principal_id in ("devops_admin", "master_admin", "system")
        or (ctx.principal_id == "admin" and ctx.tenant_id in ("default_tenant", "public", "system", None))
        or "super_admin" in ctx.user_roles
        or "devops_admin" in ctx.user_roles
    )
    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DevOps Super-Admin privileges required to access operational control plane.",
        )


@router.get("/tenants", response_class=HTMLResponse)
async def super_admin_tenants_dashboard(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> HTMLResponse:
    """Super-Admin portal dashboard listing all tenant partitions and configs."""
    _verify_devops_privilege(ctx)

    mgr = TenantLifecycleManager()
    vault = DevOpsKeyVault()
    csrf_token = request.cookies.get("csrf_token") or generate_csrf_token()

    with mgr.session_factory() as session:
        tenants = list(session.scalars(select(Tenant).order_by(Tenant.id)).all())
        domains = list(session.scalars(select(TenantDomain)).all())
        configs = list(session.scalars(select(TenantConfig)).all())
        from core_platform.app.identity.models import PlatformUser
        admins = list(session.scalars(select(PlatformUser).where(PlatformUser.role.in_(["admin", "ADMIN", "super_admin"]))).all())

        domain_map: Dict[str, List[TenantDomain]] = {}
        for d in domains:
            domain_map.setdefault(d.tenant_id, []).append(d)

        config_map: Dict[str, TenantConfig] = {c.tenant_id: c for c in configs}
        admin_map: Dict[str, PlatformUser] = {}
        for a in admins:
            if a.tenant_id not in admin_map:
                admin_map[a.tenant_id] = a
            admin_map[a.tenant_id.replace("_", "-")] = a
            admin_map[a.tenant_id.replace("-", "_")] = a

        tenant_cards: List[Dict[str, Any]] = []
        for t in tenants:
            t_domains = domain_map.get(t.id, [])
            t_cfg = config_map.get(t.id)
            t_admin = admin_map.get(t.id) or admin_map.get(t.id.replace("_", "-")) or admin_map.get(t.id.replace("-", "_"))
            tenant_cards.append({
                "tenant": t,
                "domains": t_domains,
                "config": t_cfg,
                "admin": t_admin,
                "credential_mode": t_cfg.credential_mode if t_cfg else "PLATFORM_MANAGED",
                "has_custom_gemini": bool(t_cfg and t_cfg.encrypted_gemini_api_key),
                "has_custom_waba": bool(t_cfg and t_cfg.encrypted_waba_token),
            })

    return templates.TemplateResponse(
        request=request,
        name="super_admin_tenants.html",
        context={
            "title": "DevOps Multi-Tenant Control Plane",
            "principal": ctx.principal_id,
            "tenants": tenant_cards,
            "csrf_token": csrf_token,
            "message": message,
            "error": error,
            "organization": settings.ORGANIZATION_NAME,
        },
    )


@router.post("/tenants/provision")
async def provision_tenant_action(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    slug: str = Form(...),
    name: str = Form(...),
    admin_phone: Optional[str] = Form(None),
    admin_name: Optional[str] = Form(None),
    admin_password: Optional[str] = Form(None),
    admin_email: Optional[str] = Form(None),
    cartridges: Optional[List[str]] = Form(None),
    license_tier: str = Form("ENTERPRISE"),
    max_users: int = Form(50),
    storage_region: str = Form("ap-south-1"),
    db_mode: str = Form("sqlite"),
    db_url: Optional[str] = Form(None),
    custom_domain: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """DevOps Action: Atomically provision a new tenant partition."""
    _verify_devops_privilege(ctx)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    mgr = TenantLifecycleManager()
    try:
        selected_cartridges = cartridges if cartridges else ["mail_organizer", "temperature_marker"]
        res = mgr.provision_tenant(
            slug=slug,
            name=name,
            admin_phone=admin_phone.strip() if admin_phone and admin_phone.strip() else None,
            admin_name=admin_name.strip() if admin_name and admin_name.strip() else None,
            admin_password=admin_password.strip() if admin_password and admin_password.strip() else None,
            admin_email=admin_email.strip() if admin_email and admin_email.strip() else None,
            allowed_cartridges=selected_cartridges,
            license_tier=license_tier,
            max_users=max_users,
            storage_region=storage_region,
            db_mode=db_mode,
            db_url=db_url.strip() if db_url and db_url.strip() else None,
            custom_domain=custom_domain.strip() if custom_domain and custom_domain.strip() else None,
            performed_by=ctx.principal_id,
        )
        pwd = res.get("admin_password", "")
        admin_id = res.get("admin_username") or res.get("admin_phone") or "admin"
        msg = f"Tenant '{slug}' provisioned successfully! Root Admin Username: {admin_id} | Initial Password: {pwd}"
        return RedirectResponse(
            url=f"/ops/tenants?message={quote_plus(msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ValueError as exc:
        logger.warning("[SuperAdmin] Provisioning validation error: %s", exc)
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[SuperAdmin] Provisioning failed: %s", exc, exc_info=True)
        err_msg = str(exc)
        if "UNIQUE constraint failed" in err_msg or "IntegrityError" in type(exc).__name__:
            if "platform_tenant_domains.domain_name" in err_msg:
                err_msg = "The specified custom domain/CNAME is already registered to another tenant. Please use a unique domain or leave it blank."
            elif "platform_tenants.id" in err_msg:
                err_msg = f"Tenant ID '{slug}' already exists."
            else:
                err_msg = f"Duplicate value error: {err_msg.split(':')[-1].strip()}"
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(err_msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/tenants/{slug}/update")
async def update_tenant_profile_action(
    slug: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    name: Optional[str] = Form(None),
    license_tier: Optional[str] = Form(None),
    tenant_status: Optional[str] = Form(None, alias="status"),
    max_users: Optional[int] = Form(None),
    admin_username: Optional[str] = Form(None),
    admin_name: Optional[str] = Form(None),
    admin_email: Optional[str] = Form(None),
    admin_password: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """DevOps Action: Update tenant profile, configuration, and root admin credentials."""
    _verify_devops_privilege(ctx)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    mgr = TenantLifecycleManager()
    try:
        mgr.update_tenant_profile(
            slug=slug,
            name=name.strip() if name and name.strip() else None,
            license_tier=license_tier.strip() if license_tier and license_tier.strip() else None,
            status=tenant_status.strip() if tenant_status and tenant_status.strip() else None,
            max_users=max_users,
            admin_username=admin_username.strip() if admin_username and admin_username.strip() else None,
            admin_name=admin_name.strip() if admin_name and admin_name.strip() else None,
            admin_email=admin_email.strip() if admin_email and admin_email.strip() else None,
            admin_password=admin_password.strip() if admin_password and admin_password.strip() else None,
            performed_by=ctx.principal_id,
        )
        msg = f"Tenant '{slug}' profile and credentials updated successfully!"
        return RedirectResponse(
            url=f"/ops/tenants?message={quote_plus(msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[SuperAdmin] Update failed: %s", exc, exc_info=True)
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/tenants/{slug}/delete")
async def delete_tenant_action(
    slug: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    confirm_slug: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """DevOps Action: Permanently delete a tenant partition and its users."""
    _verify_devops_privilege(ctx)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    clean_slug = slug.lower().strip()
    if confirm_slug and confirm_slug.lower().strip() != clean_slug and confirm_slug.lower().strip() != clean_slug.replace("_", "-"):
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus('Tenant confirmation slug does not match.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    mgr = TenantLifecycleManager()
    try:
        mgr.delete_tenant(slug=slug, performed_by=ctx.principal_id)
        msg = f"Tenant '{slug}' permanently deleted."
        return RedirectResponse(
            url=f"/ops/tenants?message={quote_plus(msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[SuperAdmin] Delete failed: %s", exc, exc_info=True)
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/tenants/{slug}/cartridges")
async def update_tenant_cartridges_action(
    slug: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    cartridges: Optional[List[str]] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """DevOps Action: Update enabled cartridge applications for a tenant."""
    _verify_devops_privilege(ctx)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    mgr = TenantLifecycleManager()
    try:
        selected = cartridges if cartridges else []
        mgr.update_tenant_cartridges(tenant_id=slug, cartridges=selected, performed_by=ctx.principal_id)
        msg = f"Cartridge entitlements updated for '{slug}'"
        return RedirectResponse(
            url=f"/ops/tenants?message={quote_plus(msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[SuperAdmin] Cartridge update failed: %s", exc)
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/tenants/{slug}/archive")
async def archive_tenant_action(
    slug: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """DevOps Action: Decommission and archive a tenant."""
    _verify_devops_privilege(ctx)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    mgr = TenantLifecycleManager()
    try:
        mgr.archive_tenant(slug=slug, performed_by=ctx.principal_id)
        msg = f"Tenant '{slug}' archived successfully."
        return RedirectResponse(
            url=f"/ops/tenants?message={quote_plus(msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[SuperAdmin] Archive failed: %s", exc)
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/tenants/{slug}/clone")
async def clone_tenant_action(
    slug: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    target_slug: str = Form(...),
    target_name: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """DevOps Action: Deep-Clone an entire tenant partition and data snapshot."""
    _verify_devops_privilege(ctx)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    mgr = TenantLifecycleManager()
    try:
        mgr.deep_clone_tenant(
            source_slug=slug,
            target_slug=target_slug,
            target_name=target_name.strip() if target_name and target_name.strip() else None,
            performed_by=ctx.principal_id,
        )
        msg = f"Cloned tenant '{slug}' to '{target_slug}' successfully."
        return RedirectResponse(
            url=f"/ops/tenants?message={quote_plus(msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[SuperAdmin] Deep-Clone failed: %s", exc)
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/tenants/{slug}/transfer")
async def transfer_tenant_action(
    slug: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    target_db_url: Optional[str] = Form(None),
    target_region: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """DevOps Action: Migrate tenant database and cutover geo-region."""
    _verify_devops_privilege(ctx)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    mgr = TenantLifecycleManager()
    try:
        mgr.transfer_tenant(
            slug=slug,
            target_db_url=target_db_url.strip() if target_db_url and target_db_url.strip() else None,
            target_region=target_region.strip() if target_region and target_region.strip() else None,
            performed_by=ctx.principal_id,
        )
        msg = f"Tenant '{slug}' transferred successfully."
        return RedirectResponse(
            url=f"/ops/tenants?message={quote_plus(msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[SuperAdmin] Transfer failed: %s", exc)
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/tenants/{slug}/vault")
async def configure_vault_action(
    slug: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    credential_mode: str = Form("PLATFORM_MANAGED"),
    gemini_api_key: Optional[str] = Form(None),
    openai_api_key: Optional[str] = Form(None),
    waba_access_token: Optional[str] = Form(None),
    waba_phone_number_id: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """DevOps Action: Configure tenant BYOK keys with AES-256-GCM encryption."""
    _verify_devops_privilege(ctx)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    vault = DevOpsKeyVault()
    try:
        vault.configure_tenant_credentials(
            tenant_id=slug,
            credential_mode=credential_mode,
            gemini_api_key=gemini_api_key.strip() if gemini_api_key and gemini_api_key.strip() else None,
            openai_api_key=openai_api_key.strip() if openai_api_key and openai_api_key.strip() else None,
            waba_access_token=waba_access_token.strip() if waba_access_token and waba_access_token.strip() else None,
            waba_phone_number_id=waba_phone_number_id.strip() if waba_phone_number_id and waba_phone_number_id.strip() else None,
        )
        msg = f"Vault credentials updated for '{slug}'"
        return RedirectResponse(
            url=f"/ops/tenants?message={quote_plus(msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[SuperAdmin] Vault update failed: %s", exc)
        return RedirectResponse(
            url=f"/ops/tenants?error={quote_plus(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/tenants/{slug}/audit", response_class=HTMLResponse)
async def view_tenant_audit_trail(
    slug: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
) -> HTMLResponse:
    """View cryptographic SHA-256 audit trail for a specific tenant."""
    _verify_devops_privilege(ctx)

    mgr = TenantLifecycleManager()
    with mgr.session_factory() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.id == slug))
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        stmt = (
            select(TenantAuditLog)
            .where(TenantAuditLog.tenant_id == slug)
            .order_by(TenantAuditLog.id.asc())
        )
        logs = list(session.scalars(stmt).all())

        # Verify hash integrity
        current_prev = GENESIS_HASH
        verified_logs: List[Dict[str, Any]] = []
        is_tamper_free = True

        for l in logs:
            is_valid_chain = (l.prev_hash == current_prev)
            computed_hash = compute_audit_hash(
                prev_hash=l.prev_hash,
                timestamp=l.timestamp,
                action=l.action,
                payload_str=l.payload_json or "{}",
            )
            is_valid_content = (computed_hash == l.record_hash)
            record_ok = is_valid_chain and is_valid_content

            if not record_ok:
                is_tamper_free = False

            verified_logs.append({
                "log": l,
                "payload": json.loads(l.payload_json or "{}"),
                "is_valid": record_ok,
                "computed_hash": computed_hash,
            })
            current_prev = l.record_hash

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=[],
        tenant_name=settings.ORGANIZATION_NAME or "",
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.devops_plane", path="/ops/tenants"),
            Breadcrumb(label_key="core.ops_audit.heading"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="super_admin_audit.html",
        context={
            "title": f"Audit Trail: {tenant.name} ({slug})",
            "principal": ctx.principal_id,
            "tenant": tenant,
            "logs": verified_logs,
            "is_tamper_free": is_tamper_free,
            "organization": settings.ORGANIZATION_NAME,
            "ui": ui_ctx,
        },
    )
