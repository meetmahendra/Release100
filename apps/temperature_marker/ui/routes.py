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
FastAPI Routes for CaneBot Admin Web Shell and Stepper Wizard.

Provides endpoints for Fleet Map, Stepper Wizard Simulator, Operator Approvals,
and 1-Click Mobile Web Geolocation.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.skills.geofencing import GeofencingSkill
from core_platform.app.telemetry.audit_engine import AuditEngine

router = APIRouter(prefix="/admin/apps/temperature-marker", tags=["Temperature Marker Admin"])

# Set up Jinja2 templates directory
_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

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


class LocationVerificationRequest(BaseModel):
    """Payload for 1-click mobile web geolocation verification."""

    kiosk_id: str
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    session_id: Optional[str] = None


class CreateKioskRequest(BaseModel):
    """Payload for registering a new CaneBot kiosk."""

    kiosk_id: str
    site_name: str
    city: str
    latitude: float
    longitude: float
    radius_meters: float = 100.0
    machine_model: str = "CaneBot-Pro-X1"
    display_type: str = "7-segment-led"
    primary_operator_phones: Optional[List[str]] = None


class CreateMemberRequest(BaseModel):
    """Payload for enrolling a new operator member."""

    full_name: str
    phone_number: str
    assigned_kiosk_id: str
    emp_code: Optional[str] = None
    photo_base64: Optional[str] = None


class ReassignMemberRequest(BaseModel):
    """Payload for reassigning an operator member."""

    kiosk_id: str


@router.get("/", response_class=HTMLResponse)
async def admin_root() -> RedirectResponse:
    """Redirect admin root to fleet dashboard."""
    return RedirectResponse(url="/admin/apps/temperature-marker/fleet")


@router.get("/fleet", response_class=HTMLResponse)
async def view_fleet(request: Request) -> HTMLResponse:
    """Render interactive Fleet Map and Kiosk Roster with Member assignments."""
    kiosks = _kg_service.list_all_kiosks()
    employees = _db_service.get_all_employees()
    return templates.TemplateResponse(
        request=request,
        name="fleet.html",
        context={
            "active_tab": "fleet",
            "kiosks": kiosks,
            "employees": employees,
        },
    )


@router.get("/api/fleet")
async def get_fleet_api() -> List[Dict[str, Any]]:
    """Return JSON list of all registered CaneBot kiosks in fleet."""
    return _kg_service.list_all_kiosks()


@router.post("/api/kiosks")
async def create_kiosk_api(req: CreateKioskRequest) -> Dict[str, Any]:
    """Register a new CaneBot kiosk and site in the Knowledge Graph."""
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
    )
    return {"status": "SUCCESS", "kiosk_id": profile.kiosk_id}


@router.get("/api/members")
async def get_members_api() -> List[Dict[str, Any]]:
    """Return JSON list of registered operators and their assigned kiosks."""
    employees = _db_service.get_all_employees()
    return [
        {
            "emp_code": emp.emp_code,
            "full_name": emp.full_name,
            "phone_number": emp.phone_number,
            "assigned_kiosk_id": emp.assigned_kiosk_id,
            "status": emp.status,
            "has_biometrics": bool(emp.encrypted_face_embedding),
        }
        for emp in employees
    ]


@router.post("/api/members")
async def create_member_api(req: CreateMemberRequest) -> Dict[str, Any]:
    """Enroll a new operator, extract biometrics if photo provided, and update Knowledge Graph."""
    phone = req.phone_number.strip()
    kiosk_id = req.assigned_kiosk_id.strip()
    full_name = req.full_name.strip()

    from apps.temperature_marker.downstream.hr_connector import resolve_or_generate_employee_code
    emp_code = await resolve_or_generate_employee_code(
        phone_number=phone,
        full_name=full_name,
        explicit_code=req.emp_code.strip() if req.emp_code else None,
    )

    enc_emb = None
    status = "ACTIVE"
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
        except Exception:
            pass

    if not enc_emb:
        status = "PENDING_BIOMETRICS"

    emp = _db_service.register_employee(
        emp_code=emp_code,
        full_name=full_name,
        phone_number=phone,
        assigned_kiosk_id=kiosk_id,
        encrypted_face_embedding=enc_emb,
        status=status,
    )
    _kg_service.assign_operator_to_kiosk(phone, kiosk_id)

    # If registered without photo, send automated onboarding message on WhatsApp
    if status == "PENDING_BIOMETRICS":
        from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
        invite_msg = (
            f"👋 Welcome to Canectar CaneBot, {full_name}!\n\n"
            f"You have been enrolled for {kiosk_id} (Employee ID: {emp_code}).\n"
            f"📸 Please reply to this WhatsApp chat with a clear selfie photo to activate your facial recognition check-in."
        )
        asyncio.create_task(send_whatsapp_message(phone, invite_msg))

    return {"status": "SUCCESS", "emp_code": emp.emp_code, "member_status": status, "has_biometrics": bool(enc_emb)}


@router.post("/api/members/{emp_code}/reassign")
async def reassign_member_api(emp_code: str, req: ReassignMemberRequest) -> Dict[str, Any]:
    """Reassign an operator to a new kiosk and update knowledge graph phone mapping."""
    emp = _db_service.get_employee_by_code(emp_code)
    if not emp:
        return {"status": "ERROR", "message": "Employee not found"}

    db_ok = _db_service.assign_employee_to_kiosk(emp_code, req.kiosk_id)
    kg_ok = _kg_service.assign_operator_to_kiosk(emp.phone_number, req.kiosk_id)
    return {"status": "SUCCESS", "emp_code": emp_code, "new_kiosk_id": req.kiosk_id, "db_ok": db_ok, "kg_ok": kg_ok}


@router.get("/wizard", response_class=HTMLResponse)
async def view_wizard(request: Request, kiosk_id: Optional[str] = None) -> HTMLResponse:
    """Render Progressive Stepper Wizard for duty check-in simulation."""
    kiosks = _kg_service.list_all_kiosks()
    selected = kiosk_id or (kiosks[0]["kiosk_id"] if kiosks else "CANEBOT-PUNE-04")
    return templates.TemplateResponse(
        request=request,
        name="wizard.html",
        context={
            "active_tab": "wizard",
            "kiosks": kiosks,
            "selected_kiosk": selected,
        },
    )


@router.post("/api/simulate")
async def run_simulation(req: SimulationRequest) -> Dict[str, Any]:
    """Execute duty check-in simulation through the complete safety and workflow stack."""
    initial_state: TemperatureMarkerState = {
        "correlation_id": f"sim-{uuid.uuid4().hex[:8]}",
        "sender_phone": req.phone_number,
        "kiosk_id": req.kiosk_id,
        "user_coords": (req.latitude, req.longitude),
        "raw_image_bytes": f"DIGIT:{req.temperature}".encode("utf-8"),
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
    if result_state.get("error_code"):
        status = "REJECTED"
        err_detail = result_state.get('error_message') or result_state.get('reply_message') or 'Verification failed'
        msg = f"Rejected: {err_detail}"
    elif result_state.get("requires_admin_approval"):
        status = "NEEDS_REVIEW"
        msg = "Operator onboarding pending administrator approval."
    elif result_state.get("haccp_compliant") is False:
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
        "haccp_status": "COMPLIANT" if result_state.get("haccp_compliant") else "CRITICAL_HAZARD",
        "outbox_enqueued": result_state.get("outbox_queued", False),
        "audit_hash": result_state.get("audit_record_hash") or _audit_engine._last_hash,
    }


@router.get("/approvals", response_class=HTMLResponse)
async def view_approvals(request: Request) -> HTMLResponse:
    """Render Pending Operator Onboarding Queue."""
    pending = _db_service.get_pending_approvals()
    return templates.TemplateResponse(
        request=request,
        name="approvals.html",
        context={
            "active_tab": "approvals",
            "pending_operators": pending,
        },
    )


@router.get("/api/approvals")
async def get_approvals_api() -> List[Dict[str, Any]]:
    """Return JSON list of operators pending onboarding approval."""
    pending = _db_service.get_pending_approvals()
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


@router.post("/api/approvals/{emp_id}/approve")
async def approve_operator(emp_id: str) -> Dict[str, Any]:
    """Approve a pending operator."""
    success = _db_service.approve_employee(emp_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Operator {emp_id} not found")
    return {"status": "success", "employee_id": emp_id, "new_state": "ACTIVE"}


@router.post("/api/approvals/{emp_id}/reject")
async def reject_operator(emp_id: str) -> Dict[str, Any]:
    """Reject a pending operator."""
    success = _db_service.reject_employee(emp_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Operator {emp_id} not found")
    return {"status": "success", "employee_id": emp_id, "new_state": "REJECTED"}


@router.get("/verify-location", response_class=HTMLResponse)
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
        resolved_kiosk_id = settings.KIOSK_ID or "CANEBOT-PUNE-05"

    kiosk_info = _kg_service.get_kiosk_details(resolved_kiosk_id)
    all_kiosks = _kg_service.list_all_kiosks()

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
        },
    )


@router.post("/api/verify-location")
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


@router.get("/monitoring", response_class=HTMLResponse)
async def view_monitoring(request: Request) -> HTMLResponse:
    """Render live attendance, photo check-in, and chiller temperature monitoring console."""
    records = _db_service.get_recent_attendance(limit=50)
    employees = _db_service.get_all_employees()
    emp_map = {e.emp_code: {"full_name": e.full_name, "phone": e.phone_number} for e in employees}

    kiosks = _kg_service.list_all_kiosks()
    kiosk_map = {k["kiosk_id"]: k for k in kiosks}

    alert_count = sum(
        1 for r in records
        if (not r.haccp_compliant) or (not r.geofence_verified) or (r.face_confidence < 0.82)
    )

    return templates.TemplateResponse(
        request=request,
        name="monitoring.html",
        context={
            "active_tab": "monitoring",
            "records": records,
            "emp_map": emp_map,
            "kiosk_map": kiosk_map,
            "alert_count": alert_count,
        },
    )


@router.post("/api/records/{record_id}/resolve")
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

