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
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from core_platform.app.config import settings
from core_platform.app.ingress.rate_limiter import get_platform_rate_limiter
from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.telemetry.audit_engine import AuditEngine
from core_platform.app.telemetry.logging_config import bind_log_context, clear_log_context

logger = logging.getLogger("core_platform.ingress.whatsapp")

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

router = APIRouter(tags=["WhatsApp Webhook Ingress"])

_kg_service = KnowledgeGraphService()
_db_service = DatabaseService()
_audit_engine = AuditEngine.get_instance()
_workflow = TemperatureMarkerWorkflow(
    db_service=_db_service,
    kg_service=_kg_service,
    audit_engine=_audit_engine,
)


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
    if not kiosk_id:
        kiosk_id = _kg_service.resolve_kiosk_by_phone(sender_phone)

    if not kiosk_id:
        from apps.temperature_marker.database.db_service import DatabaseService
        emp = DatabaseService.get_instance().get_employee_by_phone(sender_phone)
        if emp and emp.assigned_kiosk_id:
            kiosk_id = emp.assigned_kiosk_id
            _kg_service.assign_operator_to_kiosk(sender_phone, kiosk_id)

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

    # Multi-Application Dispatch Logic:
    # 1. System Help & Status Inquiries
    if cmd_lower in ["help", "/help", "#help", "menu", "status", "/status"]:
        kiosk_details = _kg_service.get_kiosk_details(kiosk_id)
        station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id
        reply_text = (
            f"🤖 Release100 Multi-App Fleet Assistant\n"
            f"📍 Active Kiosk: {station_name} ({kiosk_id})\n"
            "------------------------------------\n"
            "1️⃣ Check-in & Chiller: Send selfie photo with chiller display.\n"
            f"2️⃣ 1-Click GPS Location: Open {base_url}/loc?kiosk_id={kiosk_id}\n"
            "3️⃣ Switch Active Kiosk: Send 'kiosk <kiosk_id>' (e.g. 'kiosk CANEBOT-PUNE-05' or 'kiosk 5')\n"
            "4️⃣ Self-Registration: Send 'register <EMP-CODE> <Full Name>'\n"
            "5️⃣ Email & Calendar: Send 'mail digest' or 'approve TASK-xxx'\n"
            f"6️⃣ Kiosk Fleet Admin: Visit {base_url}/admin/apps/temperature-marker/fleet"
        )

    # 2. Dynamic Kiosk Switch & Fleet Query Commands
    elif cmd_lower in ["kiosk", "kiosks", "kiosk list", "kiosks list"]:
        all_k = _kg_service.list_all_kiosks()
        lines = [f"📍 CaneBot Fleet Stations (Your Active: {kiosk_id}):\n"]
        for k in all_k:
            mark = " ✅ (Active)" if k["kiosk_id"] == kiosk_id else ""
            lines.append(f"• {k['kiosk_id']}: {k['name']} ({k['city']}){mark}")
        lines.append(f"\n👉 To switch your station, reply with: kiosk <station_id>")
        lines.append("Example: kiosk CANEBOT-PUNE-05 (or 'kiosk 5')")
        reply_text = "\n".join(lines)

    elif cmd_lower.startswith("kiosk ") or cmd_lower.startswith("switch "):
        target_raw = text_content.split(maxsplit=1)[1].strip()
        matched = _kg_service.find_kiosk(target_raw)
        if matched:
            _kg_service.assign_operator_to_kiosk(sender_phone, matched)
            from apps.temperature_marker.database.db_service import DatabaseService
            temp_db = DatabaseService.get_instance()
            emp = temp_db.get_employee_by_phone(sender_phone)
            if emp:
                temp_db.assign_employee_to_kiosk(emp.emp_code, matched)

            details = _kg_service.get_kiosk_details(matched)
            s_name = details.get("name", matched) if details else matched
            kiosk_id = matched
            reply_text = (
                f"✅ Kiosk Assignment Updated!\n"
                f"You are now assigned to: {s_name} ({matched}).\n\n"
                f"📍 Verify GPS Location (1-click):\n{base_url}/loc?kiosk_id={matched}"
            )
        else:
            all_k = _kg_service.list_all_kiosks()
            avail = ", ".join(f"{k['kiosk_id']} ({k['name']})" for k in all_k)
            reply_text = (
                f"❌ Station '{target_raw}' not recognized.\n"
                f"Available kiosks:\n{avail}\n\n"
                "Example: kiosk CANEBOT-PUNE-05 (or 'kiosk 5')"
            )

    # 3. Operator Self-Registration Command
    elif cmd_lower.startswith("register") or cmd_lower.startswith("onboard"):
        remainder = text_content.split(maxsplit=1)[1].strip() if " " in text_content.strip() else ""
        if not remainder:
            reply_text = (
                "📝 Please provide your name to register:\n"
                "Example: register Rajesh Sharma\n"
                "(Or: register EMP-1042 Rajesh Sharma if your ID is known)"
            )
        else:
            tokens = remainder.split(maxsplit=1)
            explicit_code = None
            if len(tokens) == 2 and (tokens[0].startswith("EMP-") or tokens[0].isdigit()):
                explicit_code = tokens[0].strip()
                full_name = tokens[1].strip()
            else:
                full_name = remainder.strip()

            from apps.temperature_marker.downstream.hr_connector import resolve_or_generate_employee_code
            emp_code = await resolve_or_generate_employee_code(
                phone_number=sender_phone,
                full_name=full_name,
                explicit_code=explicit_code,
            )

            raw_image_bytes = None
            if is_image:
                img_obj = msg["image"]
                if "bytes" in img_obj and isinstance(img_obj["bytes"], bytes):
                    raw_image_bytes = img_obj["bytes"]
                elif "base64" in img_obj and isinstance(img_obj["base64"], str):
                    import base64
                    try:
                        raw_image_bytes = base64.b64decode(img_obj["base64"])
                    except Exception:
                        pass
                elif "id" in img_obj and img_obj["id"]:
                    raw_image_bytes = await fetch_whatsapp_media_bytes(str(img_obj["id"]))

            enc_emb = None
            if raw_image_bytes:
                try:
                    from core_platform.app.skills.registry import get_platform_skill
                    face_skill: Any = get_platform_skill("face_recognizer")
                    if face_skill:
                        ok, vec, _ = await face_skill.compute_embedding(raw_image_bytes)
                        if ok and vec is not None:
                            enc_emb = face_skill.encrypt_embedding(vec)
                except Exception:
                    pass

            from apps.temperature_marker.database.db_service import DatabaseService
            temp_db = DatabaseService.get_instance()
            temp_db.register_employee(
                emp_code=emp_code,
                full_name=full_name,
                phone_number=sender_phone,
                assigned_kiosk_id=kiosk_id,
                encrypted_face_embedding=enc_emb,
                status="PENDING_APPROVAL",
            )
            photo_note = " Biometric template captured." if enc_emb else " Please send a selfie photo to enroll your face."
            reply_text = (
                f"📝 Registration Submitted for {full_name} ({emp_code}) at {kiosk_id}."
                f"{photo_note}\nStatus: PENDING_APPROVAL. Awaiting Admin/Supervisor approval."
            )

    # 2. Mail & Calendar Domain Commands
    elif any(cmd_lower.startswith(prefix) for prefix in ["mail", "#email", "/mail", "email", "approve", "reject"]):
        from apps.mail_organizer.database.db_service import MailDatabaseService
        mail_db = MailDatabaseService()

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

    # 3. CaneBot Attendance & Chiller Verification (Default for photos / kiosk ops)
    else:
        raw_image_bytes = None
        if is_image:
            img_obj = msg["image"]
            if "bytes" in img_obj and isinstance(img_obj["bytes"], bytes):
                raw_image_bytes = img_obj["bytes"]
            elif "base64" in img_obj and isinstance(img_obj["base64"], str):
                import base64
                try:
                    raw_image_bytes = base64.b64decode(img_obj["base64"])
                except Exception:
                    pass
            elif "id" in img_obj and img_obj["id"]:
                raw_image_bytes = await fetch_whatsapp_media_bytes(str(img_obj["id"]))

        initial_state: TemperatureMarkerState = {
            "correlation_id": correlation_id,
            "sender_phone": sender_phone,
            "kiosk_id": kiosk_id,
            "text_content": text_content,
            "user_coords": user_coords,
            "raw_image_bytes": raw_image_bytes,
        }
        final_state = await _workflow.execute(initial_state)
        reply_text = str(final_state.get("reply_message") or "Reading processed.")

    logger.info(
        "[WhatsApp Ingress] Generated reply for %s: '%s'",
        sender_phone,
        reply_text.replace("\n", " ")[:120],
    )

    # Send outbound WhatsApp message if Cloud API is configured
    clean_to = sender_raw.replace("+", "").replace(" ", "").replace("-", "").strip()
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
