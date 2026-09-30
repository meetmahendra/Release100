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
Meta WhatsApp Cloud API Webhook Ingress Gateway.

Provides GET /webhook for challenge verification and POST /webhook
for real-time message parsing, kiosk resolution, and workflow execution.
"""

import hmac
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from core_platform.app.config import settings
from core_platform.app.ingress.rate_limiter import get_platform_rate_limiter
from core_platform.app.telemetry.audit_engine import AuditEngine
from core_platform.app.telemetry.logging_config import bind_log_context, clear_log_context
from core_platform.app.common.timezone import to_local_ist

logger = logging.getLogger("core_platform.ingress.whatsapp")

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

router = APIRouter(tags=["WhatsApp Webhook Ingress"])


def _get_tm_app() -> Any:
    """Return the loaded TemperatureMarker cartridge instance, or None."""
    try:
        from core_platform.main import plugin_loader  # deferred — avoids circular import
        return plugin_loader.get_application("temperature_marker")
    except Exception:
        return None


def _get_db_service() -> Any:
    """Return the TM DatabaseService from the loaded cartridge, or None."""
    tm = _get_tm_app()
    return tm.db_service if tm is not None else None


def _get_kg_service() -> Any:
    """Return the TM KnowledgeGraphService from the loaded cartridge, or None."""
    tm = _get_tm_app()
    return tm.kg_service if tm is not None else None


def _get_workflow() -> Any:
    """Return the TM workflow from the loaded cartridge, or None."""
    tm = _get_tm_app()
    return tm.workflow if tm is not None else None



def verify_meta_signature(body_bytes: bytes, signature_header: Optional[str]) -> bool:
    """Verify HMAC-SHA256 signature from Meta webhook if app secret is configured.

    Args:
        body_bytes: Raw HTTP request body.
        signature_header: X-Hub-Signature-256 header.

    Returns:
        True if valid or if verification not configured, False otherwise.
    """
    if not settings.WHATSAPP_APP_SECRET or not signature_header:
        return True

    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    actual = signature_header.replace("sha256=", "").strip()
    return hmac.compare_digest(expected, actual)


async def fetch_whatsapp_media_bytes(media_id: str) -> Optional[bytes]:
    """Retrieve binary image bytes from Meta Graph API for inbound WhatsApp photos.

    1. Resolves temporary download URL: GET https://graph.facebook.com/v19.0/{media_id}
    2. Downloads binary JPEG/PNG payload using Bearer auth token.

    Args:
        media_id: Meta media ID from inbound webhook message.

    Returns:
        Raw binary bytes of the photo, or None if download fails.
    """
    if not settings.WHATSAPP_ACCESS_TOKEN or not _HAS_HTTPX or httpx is None:
        return None

    try:
        headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            meta_resp = await client.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers)
            if meta_resp.status_code == 200:
                media_meta = meta_resp.json()
                media_url = media_meta.get("url")
                if media_url:
                    bin_resp = await client.get(media_url, headers=headers)
                    if bin_resp.status_code == 200:
                        return bin_resp.content
    except Exception:
        pass

    return None


async def extract_image_bytes_from_msg(msg: Dict[str, Any]) -> Optional[bytes]:
    """Extract raw image bytes from an inbound WhatsApp message object."""
    if "image" not in msg:
        return None
    img_obj = msg["image"]
    if "bytes" in img_obj and isinstance(img_obj["bytes"], bytes):
        return img_obj["bytes"]
    elif "base64" in img_obj and isinstance(img_obj["base64"], str):
        import base64
        try:
            return base64.b64decode(img_obj["base64"])
        except Exception:
            return None
    elif "id" in img_obj and img_obj["id"]:
        return await fetch_whatsapp_media_bytes(str(img_obj["id"]))
    return None


async def handle_operator_enrollment_photo(
    emp: Any,
    raw_image_bytes: Optional[bytes],
    correlation_id: str,
    db_service: Any,
) -> str:
    """Process an onboarding photo submitted by an operator in PENDING_PHOTO status.

    Decoupled from shift attendance:
    - Zero geofence checks
    - Zero chiller OCR
    - Computes 512-dim facial vector
    - Saves photo to logs/photos/{emp_code}_profile.jpg
    - Stores encrypted embedding (AES-256-GCM)
    - Transitions operator to PENDING_APPROVAL
    """
    if not raw_image_bytes or len(raw_image_bytes) < 100:
        return (
            f"⚠️ Image Not Received\n\n"
            f"Hello {emp.full_name}, we could not process the photo.\n"
            f"Please reply with a clear, front-facing selfie photo to complete your enrollment."
        )

    from core_platform.app.skills.registry import get_platform_skill
    face_skill: Any = get_platform_skill("face_recognizer")
    if not face_skill:
        from core_platform.app.skills.face_recognizer import FaceRecognizerSkill
        face_skill = FaceRecognizerSkill()

    ok, embedding, err = await face_skill.compute_embedding(raw_image_bytes)
    if not ok or embedding is None:
        logger.warning(
            "[Enrollment] Face detection failed for %s (%s): %s",
            emp.emp_code, emp.full_name, err,
        )
        return (
            f"⚠️ No Face Detected\n\n"
            f"Hello {emp.full_name}, we could not detect a clear face in this photo ({err or 'undetected'}).\n\n"
            f"👉 Please reply with a well-lit, front-facing selfie (no sunglasses, no extreme tilt) to complete registration."
        )

    enc_emb = face_skill.encrypt_embedding(embedding)

    # Save photo to disk for admin visual review
    photo_dir = Path("logs/photos")
    photo_dir.mkdir(parents=True, exist_ok=True)
    profile_path = photo_dir / f"{emp.emp_code}_profile.jpg"
    profile_path.write_bytes(raw_image_bytes)

    # Update employee record in DB to PENDING_APPROVAL
    db_service.register_employee(
        emp_code=emp.emp_code,
        full_name=emp.full_name,
        phone_number=emp.phone_number,
        assigned_kiosk_id=emp.assigned_kiosk_id,
        encrypted_face_embedding=enc_emb,
        status="PENDING_APPROVAL",
        role=emp.role or "OPERATOR",
        reporting_manager_emp_code=emp.reporting_manager_emp_code,
    )

    logger.info(
        "[Enrollment] Successfully registered photo & embedding for %s (%s). Status -> PENDING_APPROVAL",
        emp.emp_code, emp.full_name,
    )

    return (
        f"✅ Onboarding Photo Received!\n\n"
        f"Thank you, {emp.full_name} ({emp.emp_code})! Your facial biometric profile has been successfully generated.\n\n"
        f"⏳ Status: PENDING APPROVAL\n"
        f"Your Fleet Manager has been notified and will approve your profile shortly. You will receive a WhatsApp message once activated for duty."
    )


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
) -> Response:
    """Meta Webhook Challenge Verification.

    Args:
        hub_mode: Subscription mode ('subscribe').
        hub_verify_token: Secret verification token.
        hub_challenge: One-time echo challenge.

    Returns:
        Plain text challenge response with 200 OK.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge or "", status_code=200)

    raise HTTPException(status_code=403, detail="Verification token mismatch")


async def dispatch_whatsapp_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch inbound WhatsApp payload to the appropriate domain cartridge."""
    # 0. Handle Cloud Relay wrapper if present
    if data.get("event") == "connected":
        logger.info("[WhatsApp Ingress] Cloud Relay connected: %s", data.get("message", ""))
        return {"status": "RELAY_CONNECTED"}

    # Unwrap envelope: could be data['body']['payload'] or data['payload'] or data['body']
    unwrapped = data
    if "body" in unwrapped and isinstance(unwrapped["body"], dict):
        body = unwrapped["body"]
        if "payload" in body and isinstance(body["payload"], dict):
            unwrapped = body["payload"]
        elif "entry" in body:
            unwrapped = body
    elif "payload" in unwrapped and isinstance(unwrapped["payload"], dict):
        unwrapped = unwrapped["payload"]

    entries = unwrapped.get("entry", [])
    if not entries:
        logger.warning("[WhatsApp Ingress] Dropping payload: no 'entry' found. Top keys: %s", list(data.keys()))
        return {"status": "NO_ENTRY"}

    changes = entries[0].get("changes", [])
    if not changes:
        logger.warning("[WhatsApp Ingress] Dropping payload: no 'changes' found in entry[0].")
        return {"status": "NO_CHANGE"}

    value = changes[0].get("value", {})
    messages = value.get("messages", [])
    if not messages:
        statuses = value.get("statuses", [])
        if statuses:
            status_item = statuses[0]
            logger.info(
                "[WhatsApp Ingress] Delivery receipt update: id=%s recipient=%s status=%s",
                status_item.get("id"),
                status_item.get("recipient_id"),
                status_item.get("status"),
            )
            return {"status": "STATUS_UPDATE", "statuses": statuses}
        logger.info("[WhatsApp Ingress] No messages or statuses in webhook payload.")
        return {"status": "NO_MESSAGES"}

    msg = messages[0]
    sender_raw = str(msg.get("from", ""))
    sender_phone = f"+{sender_raw}" if not sender_raw.startswith("+") else sender_raw
    logger.info(
        "[WhatsApp Ingress] Inbound message received from %s (raw: %s, type: %s)",
        sender_phone,
        sender_raw,
        msg.get("type", "unknown"),
    )

    # --- Layer 0: Per-sender rate limiting (token bucket, 10 burst / 1 per sec) ---
    _rate_limiter = get_platform_rate_limiter()
    allowed, remaining = _rate_limiter.check_and_consume(sender_phone)
    if not allowed:
        logger.warning(
            "[RateLimit] Sender %s exceeded ingress rate limit. Remaining tokens: %d",
            sender_phone,
            remaining,
        )
        # Must return HTTP 200 to Meta — returning 4xx causes Meta to aggressively retry.
        return {
            "status": "RATE_LIMITED",
            "sender": sender_phone,
            "message": "Too many requests. Please wait before sending another message.",
        }

    # Refresh fleet roster to catch any dynamic assignments
    _kg_service = _get_kg_service()
    _db_service = _get_db_service()
    _workflow = _get_workflow()

    if _kg_service is not None:
        _kg_service.roster = _kg_service._load_roster()

    # Extract location if shared directly or retrieve recently verified location for this operator
    user_coords = None
    if "location" in msg:
        loc = msg["location"]
        user_coords = (float(loc.get("latitude", 0.0)), float(loc.get("longitude", 0.0)))
        from core_platform.app.ingress.location_session import set_session_coordinates
        set_session_coordinates(sender_phone, user_coords, ttl_seconds=1800)
        logger.info("[WhatsApp Ingress] Cached verified location for sender %s: %s (TTL: 30m)", sender_phone, user_coords)
    else:
        from core_platform.app.ingress.location_session import get_session_coordinates
        user_coords = get_session_coordinates(sender_phone)
        if user_coords:
            logger.info("[WhatsApp Ingress] Reusing cached verified location for %s: %s", sender_phone, user_coords)

    # Extract text or caption
    text_content = ""
    is_image = "image" in msg
    if "text" in msg:
        text_content = str(msg["text"].get("body", "")).strip()
    elif is_image:
        text_content = str(msg["image"].get("caption", "")).strip()

    cmd_lower = text_content.lower()

    # Dynamic Kiosk Detection from Message (e.g., "checkin CANEBOT-PUNE-05" or "switch 5")
    explicit_kiosk: Optional[str] = None
    if any(cmd_lower.startswith(p) for p in ["checkin ", "check-in ", "duty "]):
        tokens = text_content.split()
        for t in tokens[1:]:
            found = _kg_service.find_kiosk(t)
            if found:
                explicit_kiosk = found
                break

    # Multi-Tier Kiosk Resolution Hierarchy:
    # 1. Explicit in command / check-in
    # 2. Knowledge Graph roster by operator phone
    # 3. SQLite Employee Database assigned_kiosk_id
    # 4. Proximity check if GPS coordinates are cached/available (within 1500m)
    # 5. Default settings.KIOSK_ID
    kiosk_id: Optional[str] = explicit_kiosk
    if not kiosk_id and _kg_service:
        kiosk_id = _kg_service.resolve_kiosk_by_phone(sender_phone)

    emp = _db_service.get_employee_by_phone(sender_phone) if _db_service else None
    if not kiosk_id and emp and emp.assigned_kiosk_id:
        kiosk_id = emp.assigned_kiosk_id
        if _kg_service:
            _kg_service.assign_operator_to_kiosk(sender_phone, kiosk_id)

    # If coordinates are missing, check if operator already marked attendance today
    if not user_coords and emp:
        att = _db_service.has_attendance_today(emp.emp_code)
        if att is not None:
            assigned_kiosk = att.kiosk_id or kiosk_id or emp.assigned_kiosk_id
            kiosk_geo = _kg_service.get_kiosk_coordinates(assigned_kiosk)
            if kiosk_geo:
                user_coords = (kiosk_geo[0], kiosk_geo[1])
                logger.info(
                    "[WhatsApp Ingress] Operator %s already on duty today at %s — reusing station coordinates: %s",
                    emp.emp_code, assigned_kiosk, user_coords
                )

    if not kiosk_id and user_coords:
        nearest_res = _kg_service.find_nearest_kiosk(user_coords)
        if nearest_res and nearest_res[1] <= 1500.0:
            kiosk_id = nearest_res[0]

    if not kiosk_id:
        kiosk_id = settings.KIOSK_ID

    correlation_id = f"wa-{uuid.uuid4().hex[:8]}"
    bind_log_context(correlation_id=correlation_id, kiosk_id=kiosk_id)
    reply_text = ""

    base_url = (
        settings.ORCHESTRATOR_BASE_URL.rstrip("/")
        if settings.ORCHESTRATOR_BASE_URL
        else f"http://localhost:{settings.ORCHESTRATOR_PORT}"
    )

    # Ingress Intent Inference
    from core_platform.app.ingress.intent_router import IngressIntent, classify_ingress_intent
    from core_platform.app.messaging.internal_dispatch import ManagerTriageSessionManager
    sender_role = emp.role if emp and emp.role else "OPERATOR"
    has_quoted_reply = "context" in msg or "reply_to" in msg
    has_active_triage = ManagerTriageSessionManager.get_instance().get_active_message_id(sender_phone) is not None
    intent_result = classify_ingress_intent(
        text=text_content,
        is_image=is_image,
        sender_role=sender_role,
        has_quoted_reply=has_quoted_reply,
        has_active_triage=has_active_triage,
    )

    is_native_location = msg.get("type") == "location" or "location" in msg

    # ── Flaw 4: Operator Self-Registration / Supervisor Enrollment Command ──
    if cmd_lower.startswith("register") or cmd_lower.startswith("onboard"):
        if sender_role.upper() not in ["SUPERVISOR", "MANAGER", "ADMIN"]:
            reply_text = (
                "❌ Self-Registration Disabled\n"
                "Operator self-registration via WhatsApp is not permitted.\n"
                "Please contact your Fleet Supervisor or HR administrator to provision your CaneBot account."
            )
        else:
            remainder = text_content.split(maxsplit=1)[1].strip() if " " in text_content.strip() else ""
            if not remainder:
                reply_text = (
                    "📝 Supervisor Enrollment Format:\n"
                    "register <EMP-CODE> <Full Name> <Phone>\n"
                    "Example: register EMP-1050 Amit Patil +919800112233"
                )
            else:
                tokens = remainder.split()
                explicit_code = None
                phone_arg = None
                name_tokens = []
                for t in tokens:
                    if (t.startswith("EMP-") or (t.isdigit() and len(t) <= 6)) and explicit_code is None:
                        explicit_code = t
                    elif (t.startswith("+") or (t.isdigit() and len(t) >= 10)) and phone_arg is None:
                        phone_arg = t
                    else:
                        name_tokens.append(t)
                full_name = " ".join(name_tokens) if name_tokens else "New Operator"
                target_phone = phone_arg or sender_phone

                tm = _get_tm_app()
                if tm is not None and hasattr(tm, "resolve_or_generate_employee_code"):
                    emp_code = await tm.resolve_or_generate_employee_code(
                        phone_number=target_phone,
                        full_name=full_name,
                        explicit_code=explicit_code,
                    )
                else:
                    emp_code = explicit_code or f"EMP-{uuid.uuid4().hex[:4].upper()}"

                _db_service.register_employee(
                    emp_code=emp_code,
                    full_name=full_name,
                    phone_number=target_phone,
                    assigned_kiosk_id=kiosk_id,
                    status="PENDING_PHOTO",
                )
                _kg_service.assign_operator_to_kiosk(target_phone, kiosk_id)
                reply_text = (
                    f"📝 Operator Enrolled by Supervisor:\n"
                    f"Operator: {full_name} ({emp_code})\n"
                    f"Assigned Station: {kiosk_id}\n"
                    f"Phone: {target_phone}\n\n"
                    "Status: PENDING_PHOTO. Operator has been enrolled and can now submit their selfie photo."
                )

    # ── Option A Decoupling: Operator Onboarding & Ingress Lifecycle Gate ──
    elif emp is not None and emp.status in ("PENDING_PHOTO", "PENDING_BIOMETRICS"):
        if is_image:
            raw_bytes = await extract_image_bytes_from_msg(msg)
            reply_text = await handle_operator_enrollment_photo(emp, raw_bytes, correlation_id, _db_service)
        else:
            kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
            station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else (emp.assigned_kiosk_id or "your station")
            reply_text = (
                f"👋 Welcome to CaneBot, {emp.full_name}!\n\n"
                f"Your account setup is pending. Please reply to this chat with a clear front-facing selfie photo to complete your enrollment for {station_name} ({emp.emp_code})."
            )
    elif emp is not None and emp.status == "PENDING_APPROVAL":
        reply_text = (
            f"⏳ Enrollment Under Review\n\n"
            f"Hello {emp.full_name}, your onboarding portrait has been received and is currently awaiting Admin Approval.\n\n"
            f"You will receive a WhatsApp confirmation once your account has been activated for shift duty."
        )
    elif emp is not None and emp.status in ("REJECTED", "SUSPENDED"):
        reply_text = (
            f"⛔ Account Inactive\n\n"
            f"Hello {emp.full_name}, your CaneBot account is currently inactive or suspended.\n"
            f"Please contact your Fleet Supervisor for assistance."
        )

    # ── Flaw 3: Native WhatsApp Location Handling ──
    elif is_native_location and user_coords:
        if emp is None:
            # Unregistered sender guard (ISSUE-006 & ISSUE-007)
            reply_text = (
                f"👋 Welcome to CaneBot.\n\n"
                f"Your phone number ({sender_phone}) is not registered with any CaneBot kiosk.\n"
                f"Please reach out to your facility manager or administrator to be enrolled."
            )
        else:
            kiosks_list = _kg_service.list_all_kiosks() if _kg_service else []
            if not kiosks_list:
                # Clean slate 0-kiosks guard (ISSUE-006)
                reply_text = (
                    "❌ No active kiosks are configured in the system fleet roster.\n"
                    "Please contact your system administrator to register station locations."
                )
            else:
                kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
                if not kiosk_details:
                    reply_text = (
                        f"❌ Assigned kiosk '{kiosk_id}' not found in fleet roster.\n"
                        "Please contact your administrator."
                    )
                else:
                    station_name = kiosk_details.get("name", kiosk_id)
                    target_lat = float(kiosk_details.get("latitude", 0.0))
                    target_lon = float(kiosk_details.get("longitude", 0.0))
                    radius = float(kiosk_details.get("radius_meters") or kiosk_details.get("geofence_radius_meters") or 100.0)

                    from core_platform.app.skills.geofencing import GeofencingSkill
                    geo_skill = GeofencingSkill()
                    within, dist = await geo_skill.verify_geofence(
                        user_coords=user_coords,
                        kiosk_coords=(target_lat, target_lon),
                        allowed_radius_meters=radius,
                    )

                    from core_platform.app.ingress.location_session import set_session_coordinates
                    set_session_coordinates(sender_phone, user_coords, ttl_seconds=1800)
                    set_session_coordinates(kiosk_id, user_coords, ttl_seconds=1800)

                    if within:
                        _db_service.assign_employee_to_kiosk(emp.emp_code, kiosk_id)
                        _kg_service.assign_operator_to_kiosk(sender_phone, kiosk_id)

                        reply_text = (
                            f"📍 Location Verified!\n"
                            f"You are within {round(dist, 1)}m of {station_name} ({kiosk_id}). Geofence check PASSED ✅\n\n"
                            f"📸 Please now send your check-in selfie photo showing the chiller temperature display."
                        )
                    else:
                        reply_text = (
                            f"⚠️ Location Warning: Out of Geofence Boundary\n"
                            f"You are {round(dist, 1)}m away from {station_name} ({kiosk_id}) (permitted radius: {radius:.0f}m).\n\n"
                            f"Please move closer to your assigned CaneBot kiosk and resend your location pin."
                        )

    # ── Issue 14 / OP-4: Duplicate Attendance Action Guard (Idempotent Check-in Acknowledgment) ──
    elif (
        not is_image
        and not is_native_location
        and (emp is not None and _db_service.has_attendance_today(emp.emp_code) is not None)
        and any(cmd_lower.startswith(k) or cmd_lower == k for k in ["attendance", "checkin", "check-in", "duty", "punch", "login", "mark attendance"])
    ):
        att_rec = _db_service.has_attendance_today(emp.emp_code)
        chk_time = to_local_ist(att_rec.checkin_time_utc) if att_rec and att_rec.checkin_time_utc else "Today"
        kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
        station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id
        op_name = emp.full_name if emp else "Operator"

        if (
            att_rec is None
            or att_rec.haccp_status in ("PENDING_CHILLER_PHOTO", "READING_UNAVAILABLE")
            or att_rec.chiller_temp_c is None
            or att_rec.chiller_temp_c == 0.0
        ):
            c_status = "❄️ Chiller Temperature: Pending photo. (Please take a photo of the chiller gauge)"
            next_step = "📸 Next Action: Please submit a photo of the chiller gauge to complete daily compliance."
        else:
            temp_status = att_rec.haccp_status or "COMPLIANT"
            c_status = f"❄️ Chiller Temperature: {att_rec.chiller_temp_c:.1f}°C ({temp_status})"
            next_step = "✨ All kiosk duties compliant! Have a safe and productive shift."

        reply_text = (
            f"✅ Shift Attendance Already Recorded!\n"
            f"Hello {op_name}, your daily shift attendance has already been recorded for today.\n\n"
            f"📍 Station: {station_name} ({kiosk_id})\n"
            f"⏰ Check-in Time: {chk_time}\n"
            f"{c_status}\n\n"
            f"{next_step}\n"
            f"(No further check-in action needed for today)"
        )

    # ── Flaw 2: Operator First-Touch Daily Check-in & Location Gate ──
    elif (
        sender_role.upper() == "OPERATOR"
        and not is_image
        and not is_native_location
        and (emp is not None and _db_service.has_attendance_today(emp.emp_code) is None)
        and intent_result.intent not in [IngressIntent.SYSTEM_COMMAND, IngressIntent.OPERATOR_QUERY, IngressIntent.OPERATOR_GREETING]
        and not any(k in cmd_lower for k in ["fire", "smoke", "accident", "injury", "emergency", "help", "/help", "#help", "status", "/status"])
        and not any(cmd_lower.startswith(p) for p in ["mail", "#email", "/mail", "email", "approve", "reject", "register", "kiosk"])
    ):
        from core_platform.app.ingress.location_session import bind_session_metadata, record_location_prompt
        bind_session_metadata(correlation_id, {"phone": sender_phone, "kiosk_id": kiosk_id})
        record_location_prompt(sender_phone)
        kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
        station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id
        op_name = emp.full_name if emp else "Operator"
        reply_text = (
            f"⚠️ Shift Attendance Pending!\n"
            f"Good day, {op_name}! Your daily shift attendance has not been recorded yet.\n\n"
            f"📍 Step 1: Verify your location (1-click):\n"
            f"{base_url}/loc?session={correlation_id}&kiosk_id={kiosk_id}\n\n"
            f"📸 Step 2: Send your selfie photo showing the chiller temperature display to punch in."
        )

    # ── Issue 9: Operator Conversational Greeting (Self-Service Interactive Status) ──
    elif intent_result.intent == IngressIntent.OPERATOR_GREETING:
        if not emp:
            reply_text = (
                f"👋 Hello! Your phone number ({sender_phone}) is not registered in the CaneBot Kiosk system.\n\n"
                f"If you are an operator, please contact your Fleet Manager or Supervisor to set up your profile."
            )
        elif emp.status in ("PENDING_PHOTO", "PENDING_BIOMETRICS"):
            kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
            station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else (emp.assigned_kiosk_id or "your station")
            reply_text = (
                f"👋 Welcome to CaneBot, {emp.full_name}!\n\n"
                f"Your account setup is pending. Please reply to this chat with a clear front-facing selfie photo to complete your enrollment for {station_name} ({emp.emp_code})."
            )
        elif emp.status == "PENDING_APPROVAL":
            reply_text = (
                f"⏳ Enrollment Under Review\n\n"
                f"Hello {emp.full_name}, your onboarding portrait has been received and is currently awaiting Admin Approval.\n\n"
                f"You will receive a WhatsApp confirmation once your account has been activated for shift duty."
            )
        elif emp.status in ("REJECTED", "SUSPENDED"):
            reply_text = (
                f"⛔ Account Inactive\n\n"
                f"Hello {emp.full_name}, your CaneBot account is currently inactive or suspended.\n"
                f"Please contact your Fleet Supervisor for assistance."
            )
        else:
            from core_platform.app.ingress.location_session import bind_session_metadata, record_location_prompt
            op_name = emp.full_name
            kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
            station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id

            # 1. Attendance & Chiller Status
            att_rec = _db_service.has_attendance_today(emp.emp_code)
            if att_rec:
                chk_time = to_local_ist(att_rec.checkin_time_utc) if att_rec.checkin_time_utc else "Today"
                att_line = f"✅ Shift Attendance: RECORDED at {chk_time} ({station_name})"
                if (
                    att_rec.haccp_status in ("PENDING_CHILLER_PHOTO", "READING_UNAVAILABLE")
                    or att_rec.chiller_temp_c is None
                    or att_rec.chiller_temp_c == 0.0
                ):
                    chiller_line = "❄️ Chiller Temperature: Pending photo. (Please take a photo of the chiller gauge)"
                    next_action = "👉 Please take and submit a photo of the chiller gauge to complete daily compliance."
                else:
                    temp_status = att_rec.haccp_status or "COMPLIANT"
                    chiller_line = f"❄️ Chiller Temperature: {att_rec.chiller_temp_c:.1f}°C ({temp_status})"
                    next_action = "✨ All kiosk duties compliant! Have a safe and productive shift."
            else:
                bind_session_metadata(correlation_id, {"phone": sender_phone, "kiosk_id": kiosk_id})
                record_location_prompt(sender_phone)
                loc_url = f"{base_url}/loc?session={correlation_id}&kiosk_id={kiosk_id}"
                att_line = (
                    f"⚠️ Shift Attendance: PENDING for today\n\n"
                    f"📍 Step 1: Verify Location (1-click):\n{loc_url}\n\n"
                    f"📸 Step 2: Send selfie photo with chiller display to punch in."
                )
                chiller_line = "❄️ Chiller Temperature: Pending check-in photo."
                next_action = "👉 Please click the location link above or share your WhatsApp location pin, then submit your check-in selfie."

            # 2. Filtered Messages Status (Only instructions TO operator or manager replies)
            recent_msgs = _db_service.get_recent_messages_for_operator(sender_phone, limit=5)
            incoming_instructions = [
                m for m in recent_msgs
                if m.recipient_phone in (sender_phone, f"+{sender_phone}")
                and m.status in ("QUEUED", "DELIVERED")
            ]
            resolved_replies = [
                m for m in recent_msgs
                if m.reply_context
                and m.status == "RESOLVED"
                and m.sender_phone in (sender_phone, f"+{sender_phone}")
            ]

            if incoming_instructions:
                msg_line = f"📬 Supervisor Instruction: \"{incoming_instructions[0].message_text[:60]}\""
            elif resolved_replies:
                latest = resolved_replies[0]
                snippet = latest.reply_context[:60] if latest.reply_context else "Reviewed"
                msg_line = f"💬 Latest Manager Reply: \"{snippet}\""
            else:
                msg_line = "📬 Messages: No new instructions from supervisor."

            reply_text = (
                f"👋 Hello {op_name}!\n"
                f"Station: {station_name} ({kiosk_id})\n"
                f"----------------------------------------\n"
                f"{att_line}\n\n"
                f"{chiller_line}\n\n"
                f"{msg_line}\n"
                f"----------------------------------------\n"
                f"{next_action}"
            )

    # Multi-Application Dispatch Logic:
    # 1. Operator Operational Queries / Supply Requests / Machine Notes
    # Automatically route directly to assigned Reporting Manager (NO @tagging required)
    elif intent_result.intent == IngressIntent.OPERATOR_QUERY:
        if not emp:
            # Unregistered sender guard (ISSUE-007)
            reply_text = (
                f"👋 Welcome to CaneBot.\n\n"
                f"Your phone number ({sender_phone}) is not registered in the system.\n"
                f"Please reach out to your facility manager or administrator to be enrolled."
            )
        else:
            mgr = None
            if emp.reporting_manager_emp_code:
                mgr = _db_service.get_employee_by_code(emp.reporting_manager_emp_code)

            if mgr and mgr.phone_number:
                mgr_phone = mgr.phone_number
                mgr_emp = mgr.emp_code
                mgr_name = mgr.full_name
            else:
                mgr_phone = getattr(settings, "SUPERVISOR_PHONE", "+919800000000")
                mgr_emp = "SUPERVISOR"
                mgr_name = "Fleet Supervisor"

            sender_code = emp.emp_code
            sender_name = emp.full_name

            # Enqueue into InternalMessageQueue
            msg_record = _db_service.enqueue_internal_message(
                correlation_id=correlation_id,
                sender_phone=sender_phone,
                sender_emp_code=sender_code,
                sender_name=sender_name,
                kiosk_id=kiosk_id,
                recipient_emp_code=mgr_emp,
                recipient_phone=mgr_phone,
                message_text=text_content,
                priority=intent_result.priority,
            )

            # Urgent emergency bypass via Meta Template Message if critical, otherwise direct WhatsApp push (ISSUE-008)
            from core_platform.app.messaging.internal_dispatch import (
                send_urgent_meta_template_alert,
                send_whatsapp_raw_message,
            )
            if intent_result.priority >= 100:
                await send_urgent_meta_template_alert(
                    recipient_phone=mgr_phone,
                    operator_name=sender_name,
                    kiosk_id=kiosk_id,
                    alert_summary=text_content[:60],
                )
            else:
                push_text = (
                    f"📬 New Operator Message\n"
                    f"From: {sender_name} ({sender_code})\n"
                    f"Machine: {kiosk_id}\n"
                    f"Priority: {intent_result.priority} | Ref: MSG-{msg_record.id}\n"
                    f"----------------------------------------\n"
                    f'"{text_content}"\n'
                    f"----------------------------------------\n"
                    f"Reply to this message directly or send 'NEXT' to triage."
                )
                await send_whatsapp_raw_message(to_phone=mgr_phone, text=push_text)

            # Check if this is a general knowledge / procedural inquiry vs physical machine supply/dispatch note
            is_question = (
                cmd_lower.endswith("?")
                or any(cmd_lower.startswith(w) for w in ["what", "how", "why", "where", "is ", "can ", "when", "tell ", "kya ", "kaise "])
                or any(k in cmd_lower for k in ["temperature range", "haccp limit", "how to clean", "how to mark", "who is my manager"])
            )

            if is_question and intent_result.priority < 75:
                # Natural language conversational answering (ISSUE-002 & ISSUE-004)
                from core_platform.app.ingress.conversational_agent import generate_conversational_response
                reply_text = await generate_conversational_response(
                    sender_phone=sender_phone,
                    user_text=text_content,
                    emp=emp,
                    kiosk_id=kiosk_id,
                    kg_service=_kg_service,
                    db_service=_db_service,
                    operation_id=correlation_id,
                )
            else:
                # Operational note / supply alert -> Dispatch to manager
                p_icon = "🚨" if intent_result.priority >= 100 else ("⚠️" if intent_result.priority >= 75 else "📦")
                reply_text = (
                    f"{p_icon} Message Dispatched to {mgr_name} ({mgr_emp})\n"
                    f"Machine: {kiosk_id}\n"
                    "----------------------------------------\n"
                    f'"{text_content}"\n'
                    "----------------------------------------\n"
                    f"Priority: {intent_result.priority} | Ref: MSG-{msg_record.id}\n"
                    "Your manager has been notified and will reply directly."
                )

    # 2. Manager Greeting / Triage Trigger
    elif intent_result.intent == IngressIntent.MANAGER_GREETING:
        from core_platform.app.messaging.internal_dispatch import build_top10_digest
        mgr_name = emp.full_name if emp else "Supervisor"
        reply_text = build_top10_digest(
            manager_phone=sender_phone,
            manager_name=mgr_name,
            db_service=_db_service,
        )

    # 3. Manager Triage Actions & Two-Way Quoted Reply Relay
    elif intent_result.intent == IngressIntent.MANAGER_REPLY:
        from core_platform.app.messaging.internal_dispatch import (
            handle_manager_navigation,
            handle_manager_reply,
            send_whatsapp_raw_message,
        )
        mgr_name = emp.full_name if emp else "Supervisor"

        if cmd_lower in ["next", "skip", "all", "list", "more"]:
            reply_text = handle_manager_navigation(
                manager_phone=sender_phone,
                manager_name=mgr_name,
                command=cmd_lower,
                db_service=_db_service,
            )
        else:
            quoted_wamid = None
            if "context" in msg and "id" in msg["context"]:
                quoted_wamid = str(msg["context"]["id"])
            elif "reply_to" in msg and "id" in msg["reply_to"]:
                quoted_wamid = str(msg["reply_to"]["id"])

            mgr_confirm, op_phone, op_msg = handle_manager_reply(
                manager_phone=sender_phone,
                manager_name=mgr_name,
                reply_text=text_content,
                quoted_wamid=quoted_wamid,
                db_service=_db_service,
            )
            reply_text = mgr_confirm
            if op_phone and op_msg:
                # Deliver two-way quoted reply directly to the operator
                await send_whatsapp_raw_message(op_phone, op_msg)

    # 4. System Help & Status Inquiries
    elif cmd_lower in ["help", "/help", "#help", "menu"]:
        if not emp:
            reply_text = (
                "🤖 CaneBot Assistant\n"
                "------------------------------------\n"
                f"Your phone number ({sender_phone}) is not registered in the CaneBot system.\n\n"
                "Please contact your Fleet Supervisor or HR administrator to provision your account."
            )
        else:
            kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
            station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id
            if sender_role.upper() == "OPERATOR":
                reply_text = (
                    f"🤖 CaneBot Fleet Assistant\n"
                    f"📍 Assigned Station: {station_name} ({kiosk_id})\n"
                    "------------------------------------\n"
                    "1️⃣ Check-in & Chiller: Send selfie photo with chiller display.\n"
                    f"2️⃣ 1-Click GPS Location: Open {base_url}/loc?session={correlation_id}&kiosk_id={kiosk_id}\n"
                    "3️⃣ Native Location Pin: Share current location pin directly in WhatsApp.\n"
                    "4️⃣ Operational Notes: Send message with machine notes or supply requests.\n"
                    "------------------------------------\n"
                    "ℹ️ Station assignments and account enrollment are managed exclusively by your Fleet Supervisor."
                )
            else:
                reply_text = (
                    f"🤖 Release100 Fleet Management Console\n"
                    f"📍 Monitored Station: {station_name} ({kiosk_id})\n"
                    "------------------------------------\n"
                    "1️⃣ Fleet Dashboard: Send 'fleet' or 'status' for live multi-kiosk matrix.\n"
                    "2️⃣ Review Messages: Reply 'hi' or 'messages' for operator triage queue.\n"
                    "3️⃣ Assign Operator: Send 'assign <EMP-CODE> <station_id>'\n"
                    "4️⃣ Switch Station: Send 'kiosk <station_id>'\n"
                    f"5️⃣ Admin Console: Visit {base_url}/admin/apps/temperature-marker/monitoring\n"
                )

    # 4b. Manager Fleet Executive Digest Command ('fleet', 'status', 'dashboard', 'alerts')
    elif cmd_lower in ["fleet", "status", "/status", "dashboard", "alerts"] and sender_role.upper() in ["SUPERVISOR", "MANAGER", "ADMIN"]:
        from core_platform.app.messaging.internal_dispatch import build_fleet_executive_digest
        mgr_name = emp.full_name if emp else "Supervisor"
        reply_text = build_fleet_executive_digest(
            manager_name=mgr_name,
            db_service=_db_service,
        )

    # 5. Dynamic Kiosk Switch & Fleet Query Commands (Flaw 1 RBAC)
    elif cmd_lower in ["kiosk", "kiosks", "kiosk list", "kiosks list"]:
        all_k = _kg_service.list_all_kiosks()
        lines = [f"📍 CaneBot Fleet Stations (Your Active: {kiosk_id}):\n"]
        for k in all_k:
            mark = " ✅ (Active)" if k["kiosk_id"] == kiosk_id else ""
            lines.append(f"• {k['kiosk_id']}: {k['name']} ({k['city']}){mark}")
        if sender_role.upper() in ["SUPERVISOR", "MANAGER", "ADMIN"]:
            lines.append(f"\n👉 To switch your monitored station: kiosk <station_id>")
            lines.append(f"👉 To assign an operator: assign <EMP-CODE> <station_id>")
        else:
            lines.append(f"\nℹ️ Station assignments are managed exclusively by your Fleet Supervisor.")
        reply_text = "\n".join(lines)

    elif cmd_lower.startswith("kiosk ") or cmd_lower.startswith("switch ") or cmd_lower.startswith("assign "):
        if sender_role.upper() not in ["SUPERVISOR", "MANAGER", "ADMIN"]:
            details = _kg_service.get_kiosk_details(kiosk_id)
            s_name = details.get("name", kiosk_id) if details else kiosk_id
            reply_text = (
                f"⛔ Station Assignment Restricted\n"
                f"Kiosk assignment can only be updated by your Fleet Manager or Supervisor.\n"
                f"Your assigned station is: {s_name} ({kiosk_id})."
            )
        else:
            remainder = text_content.split(maxsplit=1)[1].strip()
            tokens = remainder.split()
            target_emp: Optional[str] = None
            target_station: Optional[str] = None

            if len(tokens) >= 2:
                target_emp = tokens[0].strip()
                target_station = tokens[1].strip()
            else:
                target_station = remainder

            matched_kiosk = _kg_service.find_kiosk(target_station)
            if not matched_kiosk:
                all_k = _kg_service.list_all_kiosks()
                avail = ", ".join(f"{k['kiosk_id']} ({k['name']})" for k in all_k)
                reply_text = (
                    f"❌ Station '{target_station}' not recognized.\n"
                    f"Available kiosks:\n{avail}\n\n"
                    "Example: kiosk CANEBOT-PUNE-05 (or 'assign EMP-1042 CANEBOT-PUNE-05')"
                )
            elif target_emp:
                target_employee = _db_service.get_employee_by_code(target_emp) or _db_service.get_employee_by_phone(target_emp)
                if target_employee:
                    _db_service.assign_employee_to_kiosk(target_employee.emp_code, matched_kiosk)
                    _kg_service.assign_operator_to_kiosk(target_employee.phone_number, matched_kiosk)
                    details = _kg_service.get_kiosk_details(matched_kiosk)
                    s_name = details.get("name", matched_kiosk) if details else matched_kiosk
                    reply_text = (
                        f"✅ Operator Assigned Successfully!\n"
                        f"Operator: {target_employee.full_name} ({target_employee.emp_code})\n"
                        f"Assigned Station: {s_name} ({matched_kiosk})"
                    )
                else:
                    reply_text = f"❌ Operator '{target_emp}' not found in employee roster."
            else:
                _kg_service.assign_operator_to_kiosk(sender_phone, matched_kiosk)
                if emp:
                    _db_service.assign_employee_to_kiosk(emp.emp_code, matched_kiosk)
                details = _kg_service.get_kiosk_details(matched_kiosk)
                s_name = details.get("name", matched_kiosk) if details else matched_kiosk
                kiosk_id = matched_kiosk
                reply_text = (
                    f"✅ Monitored Station Updated!\n"
                    f"You are now monitoring: {s_name} ({matched_kiosk}).\n\n"
                    f"📍 Verify GPS Location (1-click):\n{base_url}/loc?kiosk_id={matched_kiosk}"
                )



    # 2. Mail & Calendar Domain Commands
    elif any(cmd_lower.startswith(prefix) for prefix in ["mail", "#email", "/mail", "email", "approve", "reject"]):
        try:
            from core_platform.main import plugin_loader  # deferred
            mo_app = plugin_loader.get_application("mail_organizer")
            mail_db = getattr(mo_app, "db_service", None)
            if mail_db is None:
                raise ImportError("mail_organizer db_service not found")
        except (ImportError, Exception):
            reply_text = "⚠️ Mail Organizer cartridge is not enabled on this device."
            return {"status": "success", "reply": reply_text, "source": "whatsapp_router"}

        if cmd_lower.startswith("approve "):
            task_id = text_content[8:].strip()
            ok = mail_db.approve_pm_task(task_id)
            reply_text = f"✅ Task '{task_id}' approved & marked READY for execution." if ok else f"❌ Task '{task_id}' not found or already processed."
        elif cmd_lower.startswith("reject "):
            task_id = text_content[7:].strip()
            ok = mail_db.reject_pm_task(task_id)
            reply_text = f"🚫 Task '{task_id}' rejected & cancelled." if ok else f"❌ Task '{task_id}' not found or already processed."
        else:
            metrics = mail_db.get_dashboard_metrics()
            processed_count = metrics.get('total_emails_processed', metrics.get('total_emails', 0))
            reply_text = (
                "📬 AI Mail & Calendar Summary:\n"
                f"• Total Processed: {processed_count}\n"
                f"• Pending PM Tasks: {metrics.get('pending_pm_tasks', 0)}\n"
                f"• Needs Review: {metrics.get('needs_review', 0)}\n"
                "Visit http://localhost:8002/mail/ for full interactive triage."
            )

    # 3. Explicit Geolocation Link Command
    elif cmd_lower in ["location", "loc", "gps", "link", "/location", "/loc"]:
        from core_platform.app.ingress.location_session import bind_session_metadata, record_location_prompt
        bind_session_metadata(correlation_id, {"phone": sender_phone, "kiosk_id": kiosk_id})
        record_location_prompt(sender_phone)
        kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
        station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id
        reply_text = (
            f"📍 Verify CaneBot location for {station_name} (1-click):\n"
            f"{base_url}/loc?session={correlation_id}&kiosk_id={kiosk_id}"
        )

    # 4. CaneBot Attendance & Chiller Verification (Default for photos / kiosk ops)
    else:
        raw_image_bytes = await extract_image_bytes_from_msg(msg) if is_image else None

        is_explicit_loc = any(w in cmd_lower for w in ["location", "link", "loc", "gps", "where"])
        initial_state: Dict[str, Any] = {
            "correlation_id": correlation_id,
            "sender_phone": sender_phone,
            "kiosk_id": kiosk_id,
            "text_content": text_content,
            "user_coords": user_coords,
            "raw_image_bytes": raw_image_bytes,
            "explicit_location_request": is_explicit_loc,
        }
        if _workflow is not None:
            final_state = await _workflow.execute(initial_state)
            reply_text = str(final_state.get("reply_message") or "Reading processed.")
        else:
            reply_text = "⚠️ Attendance & temperature service is currently unavailable. Please try again later."

    logger.info(
        "[WhatsApp Ingress] Generated reply for %s: '%s'",
        sender_phone,
        reply_text.replace("\n", " ")[:120],
    )

    # Send outbound WhatsApp message if Cloud API is configured
    from core_platform.app.common.phone_validator import normalize_phone_number
    normalized_to = normalize_phone_number(sender_raw)
    clean_to = normalized_to.lstrip("+")
    if settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID and _HAS_HTTPX and httpx is not None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"https://graph.facebook.com/v21.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
                headers = {
                    "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                }
                outbound_body = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": clean_to,
                    "type": "text",
                    "text": {"body": reply_text},
                }
                logger.info("[WhatsApp Ingress] Sending outbound reply to +%s via Meta Graph API...", clean_to)
                resp = await client.post(url, headers=headers, json=outbound_body)
                if resp.is_success:
                    resp_data = resp.json()
                    outbound_id = resp_data.get("messages", [{}])[0].get("id", "SENT")
                    logger.info(
                        "[WhatsApp Ingress] Outbound message successfully delivered to +%s (Message ID: %s)",
                        clean_to,
                        outbound_id,
                    )
                else:
                    logger.error(
                        "[WhatsApp Ingress] Meta Graph API returned error %d: %s",
                        resp.status_code,
                        resp.text,
                    )
        except Exception as e:
            logger.error("[WhatsApp Ingress] Outbound dispatch failed with exception: %s", e)
    elif not (settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID):
        logger.warning("[WhatsApp Ingress] WHATSAPP_ACCESS_TOKEN or PHONE_NUMBER_ID not configured; skipping outbound reply.")

    return {
        "status": "EVENT_RECEIVED",
        "correlation_id": correlation_id,
        "kiosk_id": kiosk_id,
        "reply_message": reply_text,
    }


@router.post("/webhook")
async def handle_incoming_message(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Process inbound WhatsApp message or media event from Meta Cloud API."""
    body_bytes = await request.body()
    if not verify_meta_signature(body_bytes, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid HMAC-SHA256 signature")

    try:
        data = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed JSON payload")

    return await dispatch_whatsapp_payload(data)
