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
FastAPI Routes for KioskNode Admin Web Shell and Stepper Wizard.

Provides endpoints for Fleet Map, Stepper Wizard Simulator, Operator Approvals,
and 1-Click Mobile Web Geolocation.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.auth.models import SecurityContext
from core_platform.app.common.timezone import to_local_ist, to_local_ist_full
from core_platform.app.entitlements.dependencies import require_action
from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info
from core_platform.app.rbac.permissions import get_web_security_context, require_app
from core_platform.app.config import settings
from core_platform.app.skills.geofencing import GeofencingSkill
from core_platform.app.telemetry.audit_engine import AuditEngine
from core_platform.app.ui.templating import build_templates
from core_platform.app.ui.ui_context import Breadcrumb, build_ui_context

router = APIRouter(
    prefix="/admin/apps/temperature-marker",
    tags=["Temperature Marker Admin"],
    dependencies=[Depends(require_app("temperature_marker"))],
)

# Set up Jinja2 templates directory
_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = build_templates([_TEMPLATES_DIR])
templates.env.filters["to_local_ist"] = to_local_ist
templates.env.filters["to_local_ist_full"] = to_local_ist_full
templates.env.globals["to_local_ist"] = to_local_ist
templates.env.globals["to_local_ist_full"] = to_local_ist_full

# Lazy shared services
_kg_service = KnowledgeGraphService()
_db_service = DatabaseService()
_geofencing_skill = GeofencingSkill()
_audit_engine = AuditEngine.get_instance()
_workflow = TemperatureMarkerWorkflow(
    db_service=_db_service,
    kg_service=_kg_service,
    audit_engine=_audit_engine,
)


class SimulationRequest(BaseModel):
    """Payload for duty check-in simulation."""

    kiosk_id: str
    phone_number: str
    temperature: float
    face_confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    latitude: float
    longitude: float
    photo_source: str = "synthetic"  # "synthetic" | "real_photo"


class LocationVerificationRequest(BaseModel):
    """Payload for 1-click mobile web geolocation verification."""

    kiosk_id: str
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    session_id: Optional[str] = None


class CreateKioskRequest(BaseModel):
    """Payload for registering a new KioskNode kiosk."""

    kiosk_id: str
    site_name: str
    city: str
    latitude: float
    longitude: float
    radius_meters: float = 100.0
    machine_model: str = "ChillerNode-Pro-X1"
    display_type: str = "7-segment-led"
    primary_operator_phones: Optional[List[str]] = None


class CreateMemberRequest(BaseModel):
    """Payload for enrolling a new operator member."""

    full_name: str
    phone_number: str
    assigned_kiosk_id: str
    emp_code: Optional[str] = None
    role: Optional[str] = "OPERATOR"
    photo_base64: Optional[str] = None
    reporting_manager_emp_code: Optional[str] = None


class UpdateMemberRequest(BaseModel):
    """Payload for updating an existing operator profile."""

    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    assigned_kiosk_id: Optional[str] = None
    role: Optional[str] = None
    reporting_manager_emp_code: Optional[str] = None
    status: Optional[str] = None


class CalibrateKioskLocationRequest(BaseModel):
    """Payload for live on-site GPS calibration of a kiosk."""

    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None


class ReassignMemberRequest(BaseModel):
    """Payload for reassigning an operator member."""

    kiosk_id: str


@router.get("/", response_class=HTMLResponse)
async def admin_root() -> RedirectResponse:
    """Redirect admin root to fleet dashboard."""
    return RedirectResponse(url="/admin/apps/temperature-marker/fleet")


@router.get("/fleet", response_class=HTMLResponse, dependencies=[Depends(require_action("temperature:fleet:view"))])
async def view_fleet(
    request: Request,
    ctx: Optional[SecurityContext] = Depends(get_web_security_context),
) -> HTMLResponse:
    """Render interactive Fleet Map and Kiosk Roster with Member assignments."""
    eff_tenant, tenant_name, tenant_obj = resolve_effective_tenant_info(request, ctx)
    kiosks = _kg_service.list_all_kiosks(tenant_id=eff_tenant)
    employees = _db_service.get_all_employees(tenant_id=eff_tenant)
    managers = [e for e in employees if e.role in ("MANAGER", "SUPERVISOR") or e.emp_code.startswith("MGR")]
    return templates.TemplateResponse(
        request=request,
        name="fleet.html",
        context={
            "active_tab": "fleet",
            "tenant_id": eff_tenant,
            "organization": tenant_name,
            "tenant_name": tenant_name,
            "active_tenant": tenant_obj,
            "kiosks": kiosks,
            "employees": employees,
            "managers": managers,
        },
    )


@router.get("/api/fleet", dependencies=[Depends(require_action("temperature:fleet:view"))])
async def get_fleet_api(request: Request) -> List[Dict[str, Any]]:
    """Return JSON list of all registered KioskNode kiosks in fleet."""
    eff_tenant, _, _ = resolve_effective_tenant_info(request)
    return _kg_service.list_all_kiosks(tenant_id=eff_tenant)


@router.post("/api/kiosks", dependencies=[Depends(require_action("temperature:kiosk:manage"))])
async def create_kiosk_api(req: CreateKioskRequest, request: Request) -> Dict[str, Any]:
    """Register a new KioskNode kiosk and site in the Knowledge Graph."""
    eff_tenant, _, _ = resolve_effective_tenant_info(request)
    profile = _kg_service.add_kiosk(
        kiosk_id=req.kiosk_id.strip(),
        site_name=req.site_name.strip(),
        city=req.city.strip(),
        latitude=req.latitude,
        longitude=req.longitude,
        radius_meters=req.radius_meters,
        machine_model=req.machine_model,
        display_type=req.display_type,
        primary_operator_phones=req.primary_operator_phones or [],
        tenant_id=eff_tenant,
    )
    return {"status": "SUCCESS", "kiosk_id": profile.kiosk_id}


@router.get("/api/members", dependencies=[Depends(require_action("temperature:member:view"))])
async def get_members_api(request: Request) -> List[Dict[str, Any]]:
    """Return JSON list of registered operators and their assigned kiosks."""
    eff_tenant, _, _ = resolve_effective_tenant_info(request)
    employees = _db_service.get_all_employees(tenant_id=eff_tenant)
    return [
        {
            "emp_code": emp.emp_code,
            "full_name": emp.full_name,
            "phone_number": emp.phone_number,
            "assigned_kiosk_id": emp.assigned_kiosk_id,
            "status": emp.status,
            "role": emp.role,
            "reporting_manager_emp_code": emp.reporting_manager_emp_code,
            "has_biometrics": bool(emp.encrypted_face_embedding),
        }
        for emp in employees
    ]


@router.post("/api/members", dependencies=[Depends(require_action("temperature:member:manage"))])
async def create_member_api(req: CreateMemberRequest, request: Request) -> Dict[str, Any]:
    """Enroll a new operator, extract biometrics if photo provided, and update Knowledge Graph."""
    from core_platform.app.common.phone_validator import normalize_phone_number

    eff_tenant, _, _ = resolve_effective_tenant_info(request)
    try:
        phone = normalize_phone_number(req.phone_number.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid mobile number: {exc}")

    kiosk_id = req.assigned_kiosk_id.strip()
    full_name = req.full_name.strip()
    mgr_code = req.reporting_manager_emp_code.strip() if req.reporting_manager_emp_code else None

    from apps.temperature_marker.downstream.hr_connector import resolve_or_generate_employee_code
    emp_code = await resolve_or_generate_employee_code(
        phone_number=phone,
        full_name=full_name,
        explicit_code=req.emp_code.strip() if req.emp_code else None,
    )

    enc_emb = None
    status = "PENDING_PHOTO"
    if req.photo_base64:
        import base64
        try:
            clean_b64 = req.photo_base64.split(",")[-1]
            raw_bytes = base64.b64decode(clean_b64)
            from core_platform.app.skills.registry import get_platform_skill
            face_skill: Any = get_platform_skill("face_recognizer")
            if face_skill:
                ok, vec, _ = await face_skill.compute_embedding(raw_bytes)
                if ok and vec is not None:
                    enc_emb = face_skill.encrypt_embedding(vec)
                    # Persist profile photo to disk for visual admin audit
                    photo_dir = Path("logs/photos")
                    photo_dir.mkdir(parents=True, exist_ok=True)
                    photo_path = photo_dir / f"{emp_code}_profile.jpg"
                    photo_path.write_bytes(raw_bytes)
                    status = "PENDING_APPROVAL"
        except Exception:
            pass

    if not enc_emb:
        status = "PENDING_PHOTO"

    emp = _db_service.register_employee(
        emp_code=emp_code,
        full_name=full_name,
        phone_number=phone,
        assigned_kiosk_id=kiosk_id,
        encrypted_face_embedding=enc_emb,
        status=status,
        role=req.role or "OPERATOR",
        reporting_manager_emp_code=mgr_code,
        tenant_id=eff_tenant,
    )
    _kg_service.assign_operator_to_kiosk(phone, kiosk_id, tenant_id=eff_tenant)

    # If registered without photo, send automated onboarding message on WhatsApp
    if status == "PENDING_PHOTO":
        from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
        invite_msg = (
            f"👋 Welcome to Apex KioskNode, {full_name}!\n\n"
            f"You have been enrolled for {kiosk_id} (Employee ID: {emp_code}).\n"
            f"📸 Please reply to this WhatsApp chat with a clear selfie photo to activate your facial recognition check-in."
        )
        asyncio.create_task(send_whatsapp_message(phone, invite_msg))

    return {
        "status": "SUCCESS",
        "emp_code": emp.emp_code,
        "member_status": status,
        "role": emp.role,
        "reporting_manager_emp_code": emp.reporting_manager_emp_code,
        "has_biometrics": bool(enc_emb),
    }


@router.post("/api/members/{emp_code}/update", dependencies=[Depends(require_action("temperature:member:manage"))])
async def update_member_api(emp_code: str, req: UpdateMemberRequest) -> Dict[str, Any]:
    """Update operator profile details (name, phone, kiosk, manager, status, role)."""
    from core_platform.app.common.phone_validator import normalize_phone_number

    norm_phone = None
    if req.phone_number:
        try:
            norm_phone = normalize_phone_number(req.phone_number.strip())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid mobile number: {exc}")

    emp = _db_service.update_employee(
        emp_code=emp_code,
        full_name=req.full_name,
        phone_number=norm_phone,
        assigned_kiosk_id=req.assigned_kiosk_id,
        reporting_manager_emp_code=req.reporting_manager_emp_code,
        status=req.status,
        role=req.role,
    )
    if not emp:
        raise HTTPException(status_code=404, detail=f"Operator '{emp_code}' not found")

    if norm_phone and req.assigned_kiosk_id:
        _kg_service.assign_operator_to_kiosk(norm_phone, req.assigned_kiosk_id)

    return {
        "status": "SUCCESS",
        "emp_code": emp.emp_code,
        "full_name": emp.full_name,
        "phone_number": emp.phone_number,
        "assigned_kiosk_id": emp.assigned_kiosk_id,
        "reporting_manager_emp_code": emp.reporting_manager_emp_code,
        "member_status": emp.status,
    }


@router.post("/api/kiosks/{kiosk_id}/calibrate-location", dependencies=[Depends(require_action("temperature:kiosk:manage"))])
async def calibrate_kiosk_location_api(kiosk_id: str, req: CalibrateKioskLocationRequest) -> Dict[str, Any]:
    """Live ground-truth calibration of physical kiosk GPS coordinates."""
    kiosk = _kg_service.get_kiosk_details(kiosk_id)
    if not kiosk:
        raise HTTPException(status_code=404, detail=f"Kiosk '{kiosk_id}' not found in fleet roster")

    ok = _kg_service.update_kiosk_coordinates(
        kiosk_id=kiosk_id,
        latitude=req.latitude,
        longitude=req.longitude,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"Failed to update coordinates for kiosk '{kiosk_id}'")

    return {
        "status": "SUCCESS",
        "kiosk_id": kiosk_id,
        "latitude": req.latitude,
        "longitude": req.longitude,
        "message": f"Kiosk '{kiosk_id}' coordinates calibrated to ({req.latitude:.6f}, {req.longitude:.6f})",
    }


@router.post("/api/members/{emp_code}/reassign", dependencies=[Depends(require_action("temperature:member:manage"))])
async def reassign_member_api(emp_code: str, req: ReassignMemberRequest) -> Dict[str, Any]:
    """Reassign an operator to a new kiosk and update knowledge graph phone mapping."""
    emp = _db_service.get_employee_by_code(emp_code)
    if not emp:
        return {"status": "ERROR", "message": "Employee not found"}

    db_ok = _db_service.assign_employee_to_kiosk(emp_code, req.kiosk_id)
    kg_ok = _kg_service.assign_operator_to_kiosk(emp.phone_number, req.kiosk_id)
    return {"status": "SUCCESS", "emp_code": emp_code, "new_kiosk_id": req.kiosk_id, "db_ok": db_ok, "kg_ok": kg_ok}


@router.post("/api/members/{emp_code}/forget-photo", dependencies=[Depends(require_action("temperature:member:manage"))])
async def forget_member_photo_api(emp_code: str) -> Dict[str, Any]:
    """Clear an operator's stored biometric face photo/embedding and prompt re-enrollment."""
    emp = _db_service.get_employee_by_code(emp_code)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Operator '{emp_code}' not found")

    ok = _db_service.clear_employee_face_embedding(emp_code)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to clear face embedding")

    # Remove stored photo file if exists
    photo_file = Path(f"logs/photos/{emp_code}_profile.jpg")
    if photo_file.exists():
        try:
            photo_file.unlink()
        except Exception:
            pass

    # Send automated WhatsApp invitation for fresh selfie
    from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
    site_label = emp.assigned_kiosk_id
    kiosk_info = _kg_service.get_kiosk_details(emp.assigned_kiosk_id)
    if kiosk_info:
        site_label = f"{kiosk_info.get('name', site_label)} ({emp.assigned_kiosk_id})"

    msg = (
        f"📸 Biometric Profile Reset\n"
        f"Hello {emp.full_name}, your registered face photo for {site_label} has been cleared by the Administrator.\n\n"
        f"👉 Please reply to this WhatsApp chat with a clear, front-facing selfie photo to submit your new profile photo for approval."
    )
    asyncio.create_task(send_whatsapp_message(emp.phone_number, msg))

    return {
        "status": "SUCCESS",
        "emp_code": emp_code,
        "message": f"Biometric photo cleared for {emp.full_name}. Operator invited via WhatsApp.",
    }


@router.get("/api/members/{emp_code}/photo", dependencies=[Depends(require_action("temperature:photo:view"))])
async def get_member_photo_api(emp_code: str) -> Any:
    """Serve the stored profile enrollment photo for an operator if available."""
    from fastapi.responses import FileResponse
    photo_file = Path(f"logs/photos/{emp_code}_profile.jpg")
    if photo_file.exists() and photo_file.stat().st_size > 50:
        return FileResponse(str(photo_file), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail=f"Photo for operator {emp_code} not found")


@router.get("/media/{filename}", dependencies=[Depends(require_action("temperature:photo:view"))])
@router.get("/logs/media/{filename}", dependencies=[Depends(require_action("temperature:photo:view"))])
async def get_checkin_photo_api(filename: str) -> Any:
    """Serve check-in captured media photo from the local media vault."""
    from fastapi.responses import FileResponse
    safe_name = Path(filename).name
    photo_file = Path("logs/media") / safe_name
    if photo_file.exists() and photo_file.is_file():
        return FileResponse(str(photo_file), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail=f"Photo '{safe_name}' not found")



@router.get("/wizard", response_class=HTMLResponse, dependencies=[Depends(require_action("temperature:checkin:simulate"))])
async def view_wizard(
    request: Request,
    kiosk_id: Optional[str] = None,
    ctx: Optional[SecurityContext] = Depends(get_web_security_context),
) -> HTMLResponse:
    """Render Progressive Stepper Wizard for duty check-in simulation."""
    eff_tenant, tenant_name, tenant_obj = resolve_effective_tenant_info(request, ctx)
    kiosks = _kg_service.list_all_kiosks(tenant_id=eff_tenant)
    selected = kiosk_id or (kiosks[0]["kiosk_id"] if kiosks else "NODE-PUNE-04")

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name=str(tenant_name or ""),
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.platform_dashboard", path="/admin/"),
            Breadcrumb(label_key="apps.temperature_marker.name", path="/admin/apps/temperature-marker/fleet"),
            Breadcrumb(label_key="apps.temperature_marker.nav.wizard"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="wizard.html",
        context={
            "active_tab": "wizard",
            "tenant_id": eff_tenant,
            "organization": tenant_name,
            "tenant_name": tenant_name,
            "active_tenant": tenant_obj,
            "kiosks": kiosks,
            "selected_kiosk": selected,
            "ui": ui_ctx,
        },
    )


@router.post("/api/simulate", dependencies=[Depends(require_action("temperature:checkin:simulate"))])
async def run_simulation(req: SimulationRequest) -> Dict[str, Any]:
    """Execute duty check-in simulation through the complete safety and workflow stack."""
    if req.photo_source == "real_photo":
        from apps.temperature_marker.common.fixture_generator import get_real_kiosk_fixture
        raw_img = get_real_kiosk_fixture()
    else:
        from apps.temperature_marker.common.fixture_generator import generate_synthetic_gauge_jpeg
        raw_img = generate_synthetic_gauge_jpeg(req.temperature, kiosk_id=req.kiosk_id)

    initial_state: TemperatureMarkerState = {
        "correlation_id": f"sim-{uuid.uuid4().hex[:8]}",
        "sender_phone": req.phone_number,
        "kiosk_id": req.kiosk_id,
        "user_coords": (req.latitude, req.longitude),
        "raw_image_bytes": raw_img,
        "face_confidence": req.face_confidence,
    }

    result_state = await _workflow.execute(initial_state)

    # Compute distance for display
    kiosk = _kg_service.get_kiosk_by_id(req.kiosk_id)
    distance = None
    if kiosk:
        distance = round(
            _geofencing_skill.calculate_distance_meters(
                (req.latitude, req.longitude), (kiosk["latitude"], kiosk["longitude"])
            ),
            1,
        )

    # Determine status
    # Evaluate simulation status
    haccp_compliant = (2.0 <= req.temperature <= 4.0)
    haccp_status = "COMPLIANT" if haccp_compliant else ("ELEVATED" if (4.0 < req.temperature <= 7.0) else "CRITICAL_HAZARD")

    if result_state.get("error_code"):
        status = "REJECTED"
        err_detail = result_state.get('error_message') or result_state.get('reply_message') or 'Verification failed'
        msg = f"Rejected: {err_detail}"
    elif result_state.get("requires_admin_approval"):
        status = "NEEDS_REVIEW"
        msg = "Operator onboarding pending administrator approval."
    elif req.temperature > 7.0 or req.temperature < 2.0:
        status = "CRITICAL"
        msg = f"Critical Chiller Temperature Violation: {req.temperature}°C (Safe: 2-4°C)"
    elif req.temperature > 4.0:
        status = "ELEVATED"
        msg = f"Chiller Temperature Borderline/Elevated: {req.temperature}°C"
    else:
        status = "COMPLIANT"
        msg = f"Duty Check-in Approved. Chiller verified at {req.temperature}°C."

    return {
        "correlation_id": initial_state["correlation_id"],
        "status": status,
        "summary_message": msg,
        "temperature": req.temperature,
        "face_confidence": result_state.get("face_confidence", req.face_confidence),
        "geofence_status": "VERIFIED" if result_state.get("geofence_verified") else "BREACH",
        "distance_meters": distance,
        "haccp_status": haccp_status,
        "outbox_enqueued": result_state.get("outbox_queued", False),
        "audit_hash": result_state.get("audit_record_hash") or _audit_engine._last_hash,
    }


@router.get("/approvals", response_class=HTMLResponse, dependencies=[Depends(require_action("temperature:operator:view"))])
async def view_approvals(
    request: Request,
    ctx: Optional[SecurityContext] = Depends(get_web_security_context),
) -> HTMLResponse:
    """Render Pending Operator Onboarding Queue."""
    eff_tenant, tenant_name, tenant_obj = resolve_effective_tenant_info(request, ctx)
    pending = _db_service.get_pending_approvals(tenant_id=eff_tenant)

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name=str(tenant_name or ""),
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.platform_dashboard", path="/admin/"),
            Breadcrumb(label_key="apps.temperature_marker.name", path="/admin/apps/temperature-marker/fleet"),
            Breadcrumb(label_key="apps.temperature_marker.nav.approvals"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="approvals.html",
        context={
            "active_tab": "approvals",
            "tenant_id": eff_tenant,
            "organization": tenant_name,
            "tenant_name": tenant_name,
            "active_tenant": tenant_obj,
            "pending_operators": pending,
            "ui": ui_ctx,
        },
    )


@router.get("/api/approvals", dependencies=[Depends(require_action("temperature:operator:view"))])
async def get_approvals_api(request: Request) -> List[Dict[str, Any]]:
    """Return JSON list of operators pending onboarding approval."""
    eff_tenant, _, _ = resolve_effective_tenant_info(request)
    pending = _db_service.get_pending_approvals(tenant_id=eff_tenant)
    return [
        {
            "emp_code": op.emp_code,
            "full_name": op.full_name,
            "phone_number": op.phone_number,
            "assigned_kiosk_id": op.assigned_kiosk_id,
            "status": op.status,
            "created_at": op.created_at_utc.isoformat() if op.created_at_utc else None,
        }
        for op in pending
    ]


@router.post("/api/approvals/{emp_id}/approve", dependencies=[Depends(require_action("temperature:operator:approve"))])
async def approve_operator(emp_id: str) -> Dict[str, Any]:
    """Approve a pending operator and notify them via WhatsApp."""
    success = _db_service.approve_employee(emp_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Operator {emp_id} not found")

    emp = _db_service.get_employee_by_code(emp_id)
    if emp and emp.phone_number:
        from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
        kiosk_info = _kg_service.get_kiosk_details(emp.assigned_kiosk_id)
        station_name = kiosk_info.get("name", emp.assigned_kiosk_id) if kiosk_info else emp.assigned_kiosk_id
        approval_msg = (
            f"✅ Profile Approved!\n"
            f"Hello {emp.full_name}, your KioskNode operator profile for {station_name} ({emp.assigned_kiosk_id}) "
            f"has been approved by the Administrator.\n\n"
            f"You are now authorized for daily duty check-ins! 🚀\n"
            f"📍 Remember to verify your location and submit your selfie with the chiller display when your shift begins."
        )
        asyncio.create_task(send_whatsapp_message(emp.phone_number, approval_msg))

    return {"status": "success", "employee_id": emp_id, "new_state": "ACTIVE"}


@router.post("/api/approvals/{emp_id}/reject", dependencies=[Depends(require_action("temperature:operator:approve"))])
async def reject_operator(emp_id: str) -> Dict[str, Any]:
    """Reject a pending operator and notify them via WhatsApp."""
    emp = _db_service.get_employee_by_code(emp_id)
    success = _db_service.reject_employee(emp_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Operator {emp_id} not found")

    if emp and emp.phone_number:
        from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
        rejection_msg = (
            f"❌ Profile Review Notice\n"
            f"Hello {emp.full_name}, your KioskNode operator profile request could not be approved at this time.\n"
            f"Please contact your Fleet Supervisor or HR administrator for assistance."
        )
        asyncio.create_task(send_whatsapp_message(emp.phone_number, rejection_msg))

    return {"status": "success", "employee_id": emp_id, "new_state": "REJECTED"}


@router.get("/verify-location", response_class=HTMLResponse, dependencies=[Depends(require_action("temperature:location:verify"))])
async def view_verify_location(
    request: Request,
    kiosk_id: Optional[str] = None,
    session: Optional[str] = None,
) -> HTMLResponse:
    """1-Click Mobile Web Geolocation page."""
    _kg_service.roster = _kg_service._load_roster()
    resolved_kiosk_id = kiosk_id or request.query_params.get("kiosk_id")
    session_id = session or request.query_params.get("session") or ""

    if not resolved_kiosk_id and session_id:
        from core_platform.app.ingress.location_session import get_session_metadata
        meta = get_session_metadata(session_id)
        if meta:
            resolved_kiosk_id = meta.get("kiosk_id")
            if not resolved_kiosk_id and meta.get("phone"):
                resolved_kiosk_id = _kg_service.resolve_kiosk_by_phone(str(meta["phone"]))

    if not resolved_kiosk_id:
        from core_platform.app.config import settings
        resolved_kiosk_id = settings.KIOSK_ID or "NODE-PUNE-05"

    kiosk_info = _kg_service.get_kiosk_details(resolved_kiosk_id)
    all_kiosks = _kg_service.list_all_kiosks()

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=None,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name="",
        breadcrumbs=[],
    )

    return templates.TemplateResponse(
        request=request,
        name="loc.html",
        context={
            "kiosk_id": resolved_kiosk_id,
            "kiosk_name": kiosk_info.get("name", resolved_kiosk_id) if kiosk_info else resolved_kiosk_id,
            "site_name": kiosk_info.get("name", "") if kiosk_info else "",
            "city": kiosk_info.get("city", "") if kiosk_info else "",
            "radius_meters": kiosk_info.get("radius_meters", 150.0) if kiosk_info else 150.0,
            "session_id": session_id,
            "all_kiosks": all_kiosks,
            "ui": ui_ctx,
        },
    )


@router.post("/api/verify-location", dependencies=[Depends(require_action("temperature:location:verify"))])
async def verify_location_api(req: LocationVerificationRequest) -> Dict[str, Any]:
    """Verify geolocation coordinates against kiosk geofence using GeofencingSkill."""
    _kg_service.roster = _kg_service._load_roster()
    kiosk = _kg_service.get_kiosk_by_id(req.kiosk_id)
    if not kiosk:
        raise HTTPException(status_code=404, detail=f"Kiosk {req.kiosk_id} not found in fleet roster")

    target_lat = float(kiosk["latitude"])
    target_lon = float(kiosk["longitude"])
    radius = float(kiosk.get("radius_meters") or kiosk.get("geofence_radius_meters") or 100.0)

    accuracy_val = float(req.accuracy) if req.accuracy is not None else 0.0
    within, distance = await _geofencing_skill.verify_geofence(
        user_coords=(req.latitude, req.longitude),
        kiosk_coords=(target_lat, target_lon),
        allowed_radius_meters=radius,
        accuracy_meters=accuracy_val,
    )

    # Cache verified location for correlation session if session_id was provided
    if req.session_id:
        from core_platform.app.ingress.location_session import (
            get_session_phone,
            set_session_coordinates,
        )
        set_session_coordinates(req.session_id, (req.latitude, req.longitude))
        set_session_coordinates(req.kiosk_id, (req.latitude, req.longitude))

        sender_phone = get_session_phone(req.session_id)
        if sender_phone:
            set_session_coordinates(sender_phone, (req.latitude, req.longitude), ttl_seconds=1800)
            if within:
                try:
                    _kg_service.assign_operator_to_kiosk(sender_phone, req.kiosk_id)
                    emp = _db_service.get_employee_by_phone(sender_phone)
                    if emp:
                        _db_service.assign_employee_to_kiosk(emp.emp_code, req.kiosk_id)
                except Exception:
                    pass

            from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
            site_label = kiosk.get("site_name", req.kiosk_id)
            if within:
                notify_text = (
                    f"✅ Location Verified! You are within {round(distance, 1)}m of {site_label} ({req.kiosk_id}).\n\n"
                    f"📸 Please now take and send a selfie photo showing the chiller temperature display to complete check-in."
                )
            else:
                notify_text = (
                    f"⚠️ Location Warning: You appear to be {round(distance, 1)}m away from {site_label} ({req.kiosk_id}) "
                    f"(permissible radius: {radius:.0f}m). Please move closer to the kiosk and re-verify."
                )
            # Async background dispatch
            asyncio.create_task(send_whatsapp_message(sender_phone, notify_text))

    return {
        "kiosk_id": req.kiosk_id,
        "kiosk_name": kiosk.get("site_name", req.kiosk_id),
        "distance_meters": round(distance, 1),
        "radius_meters": radius,
        "within_geofence": within,
        "status": "VERIFIED" if within else "BREACH",
    }


class ResolveAttendanceRequest(BaseModel):
    """Payload for manual admin override or resolution of attendance records."""

    resolution_status: str
    notes: str


class KioskConfigRequest(BaseModel):
    """Payload for configuring kiosk multi-check monitoring requirements."""

    required_daily_temp_checks: int = Field(default=3, ge=1, le=12)
    check_interval_hours: float = Field(default=4.0, ge=0.5, le=24.0)
    min_safe_temp: float = Field(default=2.0)
    max_safe_temp: float = Field(default=4.0)
    critical_alert_temp: float = Field(default=7.0)
    alert_manager_on_hazard: bool = Field(default=True)


class ResolveMessageRequest(BaseModel):
    """Payload for web-based manager message reply & resolution."""

    reply_text: str = Field(min_length=1)
    resolver_phone: str = Field(default="+919800000000")


class AcknowledgeAlertRequest(BaseModel):
    """Payload for acknowledging an active safety alert."""

    ack_notes: str = Field(default="Acknowledged by manager via Web Console")


@router.get("/monitoring", response_class=HTMLResponse, dependencies=[Depends(require_action("temperature:monitoring:view"))])
async def view_monitoring(
    request: Request,
    ctx: Optional[SecurityContext] = Depends(get_web_security_context),
) -> HTMLResponse:
    """Render live attendance, photo check-in, and chiller temperature monitoring console."""
    eff_tenant, tenant_name, tenant_obj = resolve_effective_tenant_info(request, ctx)
    records = _db_service.get_recent_attendance(limit=50, tenant_id=eff_tenant)
    employees = _db_service.get_all_employees(tenant_id=eff_tenant)
    emp_map = {e.emp_code: {"full_name": e.full_name, "phone": e.phone_number} for e in employees}

    kiosks = _kg_service.list_all_kiosks(tenant_id=eff_tenant)
    kiosk_map = {k["kiosk_id"]: k for k in kiosks}

    # Enhanced fleet monitoring telemetry
    kiosks_summary = _db_service.get_kiosk_daily_attendance_summary(tenant_id=eff_tenant)
    active_alerts = _db_service.get_active_high_alerts(tenant_id=eff_tenant)
    recent_messages = _db_service.get_recent_internal_messages(limit=50, tenant_id=eff_tenant)
    kiosk_configs = _db_service.get_all_kiosk_configs()

    alert_count = len(active_alerts)

    return templates.TemplateResponse(
        request=request,
        name="monitoring.html",
        context={
            "active_tab": "monitoring",
            "tenant_id": eff_tenant,
            "organization": tenant_name,
            "tenant_name": tenant_name,
            "active_tenant": tenant_obj,
            "records": records,
            "emp_map": emp_map,
            "kiosk_map": kiosk_map,
            "kiosks_summary": kiosks_summary,
            "active_alerts": active_alerts,
            "messages": recent_messages,
            "kiosk_configs": kiosk_configs,
            "alert_count": alert_count,
        },
    )


@router.post("/api/records/{record_id}/resolve", dependencies=[Depends(require_action("temperature:attendance:resolve"))])
async def resolve_record_api(record_id: int, req: ResolveAttendanceRequest) -> Dict[str, Any]:
    """Manually resolve or override a flagged attendance/temperature record."""
    status_val = req.resolution_status.strip()
    notes_val = req.notes.strip()

    success = _db_service.resolve_attendance_record(
        record_id=record_id,
        resolution_status=status_val,
        notes=notes_val,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Attendance record #{record_id} not found")

    _audit_engine.record_event(
        action_type="ADMIN_MANUAL_RESOLUTION",
        operator_id="ADMIN_USER",
        payload_summary={
            "record_id": record_id,
            "resolution_status": status_val,
            "notes": notes_val,
        },
        layer_2_gate_status="RESOLVED_OVERRIDE",
    )

    return {"status": "SUCCESS", "record_id": record_id, "resolution_status": status_val}


@router.post("/api/kiosks/{kiosk_id}/config", dependencies=[Depends(require_action("temperature:kiosk:manage"))])
async def update_kiosk_config_api(kiosk_id: str, req: KioskConfigRequest) -> Dict[str, Any]:
    """Upsert HACCP multi-check schedule configuration for a kiosk or GLOBAL_DEFAULT."""
    updated = _db_service.upsert_kiosk_config(
        kiosk_id=kiosk_id,
        required_daily_temp_checks=req.required_daily_temp_checks,
        check_interval_hours=req.check_interval_hours,
        min_safe_temp=req.min_safe_temp,
        max_safe_temp=req.max_safe_temp,
        critical_alert_temp=req.critical_alert_temp,
        alert_manager_on_hazard=req.alert_manager_on_hazard,
    )
    _audit_engine.record_event(
        action_type="KIOSK_CONFIG_UPDATED",
        operator_id="ADMIN_USER",
        payload_summary={
            "kiosk_id": kiosk_id,
            "required_daily_temp_checks": req.required_daily_temp_checks,
            "check_interval_hours": req.check_interval_hours,
        },
        layer_2_gate_status="CONFIG_SAVED",
    )
    return {"status": "SUCCESS", "kiosk_id": updated.kiosk_id, "required_checks": updated.required_daily_temp_checks}


@router.post("/api/messages/{message_id}/resolve", dependencies=[Depends(require_action("temperature:message:resolve"))])
async def resolve_internal_message_api(message_id: int, req: ResolveMessageRequest) -> Dict[str, Any]:
    """Resolve an internal message from web UI and push reply to operator's WhatsApp."""
    success, op_phone, outbound_reply = _db_service.resolve_internal_message_web(
        message_id=message_id,
        reply_text=req.reply_text.strip(),
        resolver_phone=req.resolver_phone.strip(),
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Message #{message_id} not found")

    if op_phone and outbound_reply:
        from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
        asyncio.create_task(send_whatsapp_message(op_phone, outbound_reply))

    _audit_engine.record_event(
        action_type="INTERNAL_MESSAGE_WEB_RESOLVED",
        operator_id=req.resolver_phone,
        payload_summary={"message_id": message_id, "reply_text": req.reply_text},
        layer_2_gate_status="MESSAGE_RESOLVED",
    )
    return {"status": "SUCCESS", "message_id": message_id, "recipient": op_phone}


@router.post("/api/alerts/{record_id}/acknowledge", dependencies=[Depends(require_action("temperature:alert:acknowledge"))])
async def acknowledge_alert_api(record_id: int, req: AcknowledgeAlertRequest) -> Dict[str, Any]:
    """Acknowledge an active emergency compliance alert."""
    success = _db_service.acknowledge_alert(record_id=record_id, ack_notes=req.ack_notes.strip())
    if not success:
        raise HTTPException(status_code=404, detail=f"Alert record #{record_id} not found")

    _audit_engine.record_event(
        action_type="EMERGENCY_ALERT_ACKNOWLEDGED",
        operator_id="ADMIN_USER",
        payload_summary={"record_id": record_id, "notes": req.ack_notes},
        layer_2_gate_status="ALERT_ACKNOWLEDGED",
    )
    return {"status": "SUCCESS", "record_id": record_id}

