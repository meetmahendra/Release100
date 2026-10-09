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

Adheres strictly to GEES v2.0 Microkernel Architecture (Rule 3).
Operates as a pure transport multiplexer with zero domain business logic.
Dispatches incoming messages to loaded application cartridges via BaseApplication.
"""

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from core_platform.app.common.phone_validator import normalize_phone_number
from core_platform.app.config import settings
from core_platform.app.ingress.rate_limiter import get_platform_rate_limiter
from core_platform.app.telemetry.logging_config import bind_log_context, clear_log_context

logger = logging.getLogger("core_platform.ingress.whatsapp")

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

router = APIRouter(tags=["WhatsApp Webhook Ingress"])


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

    1. Resolves temporary download URL: GET https://graph.facebook.com/v21.0/{media_id}
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
            meta_resp = await client.get(f"https://graph.facebook.com/v21.0/{media_id}", headers=headers)
            if meta_resp.status_code == 200:
                media_meta = meta_resp.json()
                media_url = media_meta.get("url")
                if media_url:
                    bin_resp = await client.get(media_url, headers=headers)
                    if bin_resp.status_code == 200:
                        return bin_resp.content
    except Exception as exc:
        logger.warning("[WhatsApp Ingress] Media download error for media_id=%s: %s", media_id, exc)

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


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta WhatsApp Cloud API Webhook Verification Handshake."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("[WhatsApp Ingress] Webhook handshake verified successfully.")
        return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning("[WhatsApp Ingress] Webhook verification failed. Invalid verify_token.")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


async def dispatch_whatsapp_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Pure transport multiplexer for inbound WhatsApp payloads.

    1. Parses message envelope and validates sender.
    2. Enforces per-sender token bucket rate limiting.
    3. Resolves destination domain cartridge dynamically via PluginLoader & SemanticRouter.
    4. Dispatches message to cartridge-owned WhatsApp handler.
    5. Sends outbound WhatsApp response via Meta Graph API.
    """
    if data.get("event") == "connected":
        return {"status": "RELAY_CONNECTED", "message": data.get("message", "Worker ready")}

    # Cloud Relay wrapper unwrap: {"event": "whatsapp_message", "body": {...}}
    if "body" in data:
        inner_body = data["body"]
        if isinstance(inner_body, str):
            try:
                inner_body = json.loads(inner_body)
            except Exception:
                pass
        if isinstance(inner_body, dict):
            data = inner_body

    if "entry" not in data or not data["entry"]:
        return {"status": "NO_ENTRY"}

    entry = data["entry"][0]
    changes = entry.get("changes", [])
    if not changes:
        return {"status": "NO_ENTRY"}

    value = changes[0].get("value", {})
    messages = value.get("messages", [])

    if not messages:
        statuses = value.get("statuses", [])
        if statuses:
            return {"status": "STATUS_UPDATE", "count": len(statuses)}
        return {"status": "NO_ENTRY"}

    msg = messages[0]
    sender_raw = msg.get("from", "")
    sender_phone = normalize_phone_number(sender_raw)

    correlation_id = f"wa-{uuid.uuid4().hex[:8]}"
    node_id = getattr(settings, "NODE_ID", getattr(settings, "KIOSK_ID", "NODE-01"))
    bind_log_context(correlation_id=correlation_id, kiosk_id=node_id)

    # --- Layer 0: Per-sender rate limiting ---
    rate_limiter = get_platform_rate_limiter()
    allowed, remaining = rate_limiter.check_and_consume(sender_phone)
    if not allowed:
        logger.warning("[RateLimit] Sender %s exceeded ingress rate limit. Tokens left: %d", sender_phone, remaining)
        return {
            "status": "RATE_LIMITED",
            "sender": sender_phone,
            "message": "Too many requests. Please wait before sending another message.",
        }

    # --- Layer 0: User Identity & Entitlement Verification ---
    from core_platform.app.identity.service import get_user_identity_service
    user_service = get_user_identity_service()
    user = user_service.get_user_by_phone(sender_phone)

    if settings.WHATSAPP_REQUIRE_REGISTRATION and not user:
        logger.warning("[WhatsApp Ingress] Unregistered sender %s rejected", sender_phone)
        rejection_body = (
            "🔒 Access Denied: Your phone number is not registered on this platform.\n"
            "Please contact your system administrator to register your phone number."
        )
        clean_to = sender_phone.lstrip("+")
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
                        "text": {"body": rejection_body},
                    }
                    await client.post(url, headers=headers, json=outbound_body)
            except Exception as e:
                logger.error("[WhatsApp Ingress] Outbound dispatch error: %s", e)
        return {
            "status": "UNREGISTERED_USER",
            "correlation_id": correlation_id,
            "node_id": node_id,
            "kiosk_id": node_id,
            "reply_message": rejection_body,
        }

    if user and user.status != "active":
        logger.warning("[WhatsApp Ingress] Inactive user %s rejected", sender_phone)
        suspended_body = "🔒 Access Suspended: Your account is currently inactive. Please contact your system administrator."
        clean_to = sender_phone.lstrip("+")
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
                        "text": {"body": suspended_body},
                    }
                    await client.post(url, headers=headers, json=outbound_body)
            except Exception as e:
                logger.error("[WhatsApp Ingress] Outbound dispatch error: %s", e)
        return {
            "status": "INACTIVE_USER",
            "correlation_id": correlation_id,
            "node_id": node_id,
            "kiosk_id": node_id,
            "reply_message": suspended_body,
        }

    # Heartbeat update for registered active user
    if user:
        try:
            user_service.update_whatsapp_heartbeat(user.id)
        except Exception as hb_err:
            logger.warning("[WhatsApp Ingress] Heartbeat update error for user %s: %s", user.id, hb_err)

    # Extract text, location, and image bytes
    text_content = ""
    is_image = "image" in msg
    is_location = "location" in msg or msg.get("type") == "location"
    if "text" in msg:
        text_content = str(msg["text"].get("body", "")).strip()
    elif is_image:
        text_content = str(msg["image"].get("caption", "")).strip()

    raw_image_bytes = await extract_image_bytes_from_msg(msg) if is_image else None

    # Handle incoming native WhatsApp location pin
    user_coords: Optional[tuple[float, float]] = None
    if is_location and "location" in msg:
        loc_data = msg["location"]
        lat = loc_data.get("latitude")
        lon = loc_data.get("longitude")
        if lat is not None and lon is not None:
            user_coords = (float(lat), float(lon))
            from core_platform.app.ingress.location_session import set_session_coordinates
            set_session_coordinates(sender_phone, user_coords)

    base_url = (
        settings.ORCHESTRATOR_BASE_URL.rstrip("/")
        if settings.ORCHESTRATOR_BASE_URL
        else f"http://localhost:{settings.ORCHESTRATOR_PORT}"
    )

    user_tenant_id = user.tenant_id if user else settings.TENANT_ID
    allowed_cartridges = user.allowed_cartridges if user else None

    context: Dict[str, Any] = {
        "sender_phone": sender_phone,
        "correlation_id": correlation_id,
        "base_url": base_url,
        "image_bytes": raw_image_bytes,
        "user_coords": user_coords,
        "node_id": node_id,
        "tenant_id": user_tenant_id,
        "user_id": user.id if user else None,
        "user": user,
        "user_full_name": user.full_name if user else None,
        "allowed_cartridges": allowed_cartridges,
        "organization_name": settings.ORGANIZATION_NAME,
        "station_name": settings.STATION_NAME,
    }

    # Dynamic Cartridge Resolution via PluginLoader
    reply_text: Optional[str] = None
    response_kiosk_id: Optional[str] = None
    try:
        from core_platform.main import plugin_loader
        loaded_apps = plugin_loader.get_all_applications()
    except Exception:
        loaded_apps = {}

    # Filter apps by user's allowed cartridges if user profile is present
    if allowed_cartridges is not None and "*" not in allowed_cartridges:
        candidate_apps = {k: v for k, v in loaded_apps.items() if k in allowed_cartridges}
    else:
        candidate_apps = loaded_apps

    target_app: Optional[Any] = None

    if user and len(candidate_apps) == 0:
        logger.warning("[WhatsApp Ingress] User %s has no allowed cartridges active on this node", sender_phone)
        reply_text = (
            "🔒 No Entitled Applications: You do not have permissions to access any applications configured on this node.\n"
            "Please contact your administrator to assign application entitlements."
        )
    elif len(candidate_apps) == 1:
        # Single allowed cartridge direct shortcut
        target_app = next(iter(candidate_apps.values()))
    else:
        # Multi-cartridge priority resolution across candidate_apps
        # Priority 0: Active interactive triage/conversation session check
        for app_id, app_inst in candidate_apps.items():
            if hasattr(app_inst, "has_active_session") and app_inst.has_active_session(sender_phone):
                target_app = app_inst
                break

        # Priority 1: Match intent / keywords against active cartridges
        if not target_app:
            cmd_lower = text_content.lower()
            for app_id, app_inst in candidate_apps.items():
                app_keywords = getattr(app_inst, "keywords", [])
                if any(kw.lower() in cmd_lower for kw in app_keywords):
                    target_app = app_inst
                    break

        # Priority 2: Use SemanticRouter for natural language queries across cartridges (confident routes only)
        if not target_app and text_content and len(candidate_apps) > 1:
            try:
                from core_platform.app.routing.semantic_router import SemanticRouter
                route_decision = await SemanticRouter.route(
                    text_content=text_content,
                    candidate_apps=list(candidate_apps.keys()),
                    sender_id=sender_phone,
                )
                if (
                    route_decision
                    and route_decision.selected_app in candidate_apps
                    and not route_decision.requires_disambiguation
                ):
                    target_app = candidate_apps[route_decision.selected_app]
                    logger.info(
                        "[WhatsApp Ingress] SemanticRouter directed query to '%s' (conf: %.2f)",
                        route_decision.selected_app,
                        route_decision.confidence,
                    )
            except Exception as ex:
                logger.warning("[WhatsApp Ingress] SemanticRouter routing attempt failed: %s", ex)

        # Priority 3: Native Location Payload routing to location-aware cartridge
        if not target_app and is_location:
            for app_inst in candidate_apps.values():
                keywords = getattr(app_inst, "keywords", [])
                if any(k in ("location", "gps", "geofence", "attendance", "kiosk") for k in keywords):
                    target_app = app_inst
                    break

        # Priority 4: If sender is a registered employee in any loaded cartridge
        if not target_app:
            for app_inst in candidate_apps.values():
                db_svc = getattr(app_inst, "db_service", None)
                if db_svc and hasattr(db_svc, "get_employee_by_phone"):
                    try:
                        if db_svc.get_employee_by_phone(sender_phone) is not None:
                            target_app = app_inst
                            break
                    except Exception:
                        pass

        # Priority 5: If image submitted, default to first vision/photo cartridge
        if not target_app and is_image:
            for app_inst in candidate_apps.values():
                keywords = getattr(app_inst, "keywords", [])
                if any(k in ("photo", "image", "camera", "vision", "face", "temperature") for k in keywords):
                    target_app = app_inst
                    break

        # Priority 6: First available application fallback
        if not target_app and candidate_apps:
            target_app = next(iter(candidate_apps.values()))


    # Delegate execution to matched cartridge handler
    if target_app is not None:
        handler = target_app.get_whatsapp_handler()
        if handler is not None and hasattr(handler, "dispatch"):
            try:
                res_dispatch = await handler.dispatch(msg, context)
                if isinstance(res_dispatch, dict):
                    reply_text = str(res_dispatch.get("reply_message", ""))
                    response_kiosk_id = res_dispatch.get("kiosk_id")
                else:
                    reply_text = str(res_dispatch)
            except Exception as exc:
                logger.error("[WhatsApp Ingress] Error executing cartridge handler for %s: %s", target_app.app_id, exc)
                reply_text = f"⚠️ Application Error: {exc}"

    # Pure Core Fallback if no cartridge is installed or handled
    if not reply_text:
        reply_text = (
            f"🤖 Release100 Platform Node [{node_id}]\n\n"
            "Message received. No active application cartridge is configured to process this request.\n"
            "Please contact your administrator or configure applications in the Admin Shell."
        )

    # Dispatch outbound message via Meta Graph API if configured
    clean_to = sender_phone.lstrip("+")
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
                resp = await client.post(url, headers=headers, json=outbound_body)
                if not resp.is_success:
                    logger.warning("[WhatsApp Ingress] Meta Graph API returned error %d: %s", resp.status_code, resp.text)
        except Exception as e:
            logger.error("[WhatsApp Ingress] Outbound dispatch error: %s", e)

    return {
        "status": "EVENT_RECEIVED",
        "correlation_id": correlation_id,
        "node_id": node_id,
        "kiosk_id": response_kiosk_id or node_id,
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
