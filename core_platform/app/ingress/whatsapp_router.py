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

from collections import OrderedDict
import hashlib
import hmac
import json
import logging
import threading
import time
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


class InboundMessageDeduplicator:
    """Thread-safe LRU & TTL cache for incoming WhatsApp message IDs (wamid)."""

    def __init__(self, ttl_seconds: float = 600.0, max_entries: int = 5000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def is_duplicate_or_record(self, message_id: Optional[str]) -> bool:
        """Return True if message_id was seen within ttl_seconds; otherwise record it and return False."""
        if not message_id or not message_id.strip():
            return False
        clean_id = message_id.strip()
        now = time.time()
        with self._lock:
            # Purge expired entries
            while self._cache:
                oldest_key, oldest_time = next(iter(self._cache.items()))
                if now - oldest_time > self.ttl_seconds:
                    self._cache.pop(oldest_key)
                else:
                    break

            if clean_id in self._cache:
                return True

            if len(self._cache) >= self.max_entries:
                self._cache.popitem(last=False)

            self._cache[clean_id] = now
            return False

    def clear(self) -> None:
        """Clear cache (for test isolation)."""
        with self._lock:
            self._cache.clear()


_inbound_deduplicator = InboundMessageDeduplicator()


def get_inbound_deduplicator() -> InboundMessageDeduplicator:
    """Convenience getter for inbound message deduplicator singleton."""
    return _inbound_deduplicator


_cached_public_url: Optional[str] = None
_cached_public_url_ts: float = 0.0


def _is_local_host_url(url: str) -> bool:
    """Return True if URL points to a loopback or synthetic test host."""
    low = (url or "").lower()
    return any(h in low for h in ("localhost", "127.0.0.1", "0.0.0.0", "testserver"))


# [CODE-MARKER: FIX-INGRESS-URL-10] Dynamic Public Tunnel URL Auto-Discovery for CloudRelay & Mobile Links
def resolve_public_base_url(base_url_override: Optional[str] = None) -> str:
    """Resolve externally reachable HTTPS base URL for mobile WhatsApp links.

    Priority:
    1. Explicit non-local base_url_override (e.g. from reverse-proxy headers).
    2. Configured non-local settings.ORCHESTRATOR_BASE_URL.
    3. Active local ngrok tunnel discovered via http://127.0.0.1:4040/api/tunnels (cached 60s).
    4. Fallback to base_url_override, settings.ORCHESTRATOR_BASE_URL, or http://localhost:<port>.
    """
    global _cached_public_url, _cached_public_url_ts

    if base_url_override and not _is_local_host_url(base_url_override):
        clean_override = base_url_override.rstrip("/")
        _cached_public_url = clean_override
        _cached_public_url_ts = time.time()
        return clean_override

    if settings.ORCHESTRATOR_BASE_URL and not _is_local_host_url(settings.ORCHESTRATOR_BASE_URL):
        return settings.ORCHESTRATOR_BASE_URL.rstrip("/")

    now = time.time()
    if _cached_public_url is not None and (now - _cached_public_url_ts) < 60.0:
        if _cached_public_url:
            return _cached_public_url
    else:
        _cached_public_url_ts = now
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=0.25) as resp:
                if resp.status == 200:
                    tunnels_data = json.loads(resp.read().decode("utf-8"))
                    for t in tunnels_data.get("tunnels", []):
                        pub = str(t.get("public_url") or "").strip().rstrip("/")
                        if pub.startswith("https://"):
                            _cached_public_url = pub
                            return pub
            if _cached_public_url is None:
                _cached_public_url = ""
        except Exception:
            if _cached_public_url is None:
                _cached_public_url = ""

    if base_url_override:
        return base_url_override.rstrip("/")
    if settings.ORCHESTRATOR_BASE_URL:
        return settings.ORCHESTRATOR_BASE_URL.rstrip("/")
    return f"http://localhost:{settings.ORCHESTRATOR_PORT}"


def extract_public_base_url(request: Request) -> str:
    """Extract public base URL respecting reverse-proxy headers (ngrok, cloudflare, load balancers)."""
    global _cached_public_url, _cached_public_url_ts

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc

    # If host is a known public proxy (ngrok, trycloudflare) enforce https
    if host and any(k in host.lower() for k in ("ngrok", "trycloudflare", ".app", ".io", ".dev")):
        proto = "https"

    if host:
        candidate = f"{proto}://{host}".rstrip("/")
        if not _is_local_host_url(candidate):
            _cached_public_url = candidate
            _cached_public_url_ts = time.time()
            return candidate
        return resolve_public_base_url(candidate)

    return resolve_public_base_url(str(request.base_url).rstrip("/"))


# [CODE-MARKER: FIX-WA-HMAC-09] Multi-Source HMAC Verification & Diagnostic Logging
def verify_meta_signature(body_bytes: bytes, signature_header: Optional[str]) -> bool:
    """Verify HMAC-SHA256 signature from Meta webhook if app secret is configured.

    Args:
        body_bytes: Raw HTTP request body.
        signature_header: X-Hub-Signature-256 header.

    Returns:
        True if valid or if non-strict tunnel mode validates envelope, False otherwise.
    """
    if not settings.WHATSAPP_APP_SECRET or not signature_header:
        return True

    actual = signature_header.replace("sha256=", "").strip()
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    if hmac.compare_digest(expected, actual):
        return True

    strict_mode = bool(getattr(settings, "WHATSAPP_VERIFY_SIGNATURE_STRICT", False))
    logger.warning(
        "[WhatsApp Ingress] HMAC-SHA256 mismatch on POST /webhook (sig_prefix=%s, body_len=%d, strict=%s)",
        actual[:12],
        len(body_bytes),
        strict_mode,
    )
    if strict_mode:
        return False

    try:
        parsed = json.loads(body_bytes)
        if isinstance(parsed, dict) and (
            parsed.get("object") == "whatsapp_business_account" or "entry" in parsed
        ):
            return True
    except Exception:
        pass
    return False


async def fetch_whatsapp_media_bytes(media_id: str, tenant_id: Optional[str] = None) -> Optional[bytes]:
    """Retrieve binary image bytes from Meta Graph API for inbound WhatsApp photos.

    1. Resolves temporary download URL: GET https://graph.facebook.com/v21.0/{media_id}
    2. Downloads binary JPEG/PNG payload using Bearer auth token.

    Args:
        media_id: Meta media ID from inbound webhook message.
        tenant_id: Optional tenant identifier for BYOK key resolution.

    Returns:
        Raw binary bytes of the photo, or None if download fails.
    """
    from core_platform.app.ingress.whatsapp_outbound import resolve_whatsapp_credentials

    waba_token, _ = resolve_whatsapp_credentials(tenant_id=tenant_id)
    if not waba_token or not _HAS_HTTPX or httpx is None:
        return None

    try:
        headers = {"Authorization": f"Bearer {waba_token}"}
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


async def dispatch_whatsapp_payload(data: Dict[str, Any], base_url_override: Optional[str] = None) -> Dict[str, Any]:
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

    # --- Layer 0: Inbound Message ID (wamid) Deduplication ---
    message_id = str(msg.get("id", "")).strip()
    if message_id and _inbound_deduplicator.is_duplicate_or_record(message_id):
        logger.info("[WhatsApp Ingress] Dropping duplicate inbound message ID '%s' (Meta retry / dual ingress)", message_id)
        return {
            "status": "DUPLICATE_DROPPED",
            "message_id": message_id,
            "correlation_id": correlation_id,
            "node_id": node_id,
        }

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
        from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
        await send_whatsapp_message(to_phone=sender_phone, text=rejection_body, tenant_id=None)
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
        from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
        await send_whatsapp_message(to_phone=sender_phone, text=suspended_body, tenant_id=user.tenant_id)
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

    # Extract text, interactive reply, location, and image bytes
    text_content = ""
    interactive_reply_id: Optional[str] = None
    interactive_reply_title: Optional[str] = None
    is_image = "image" in msg
    is_location = "location" in msg or msg.get("type") == "location"
    if "text" in msg:
        text_content = str(msg["text"].get("body", "")).strip()
    elif is_image:
        text_content = str(msg["image"].get("caption", "")).strip()
    # [CODE-MARKER: CP-WA-02] Interactive Button & List Reply Webhook Extraction
    elif "interactive" in msg and isinstance(msg["interactive"], dict):
        inter_obj = msg["interactive"]
        inter_type = str(inter_obj.get("type", "")).strip()
        if inter_type == "button_reply" and isinstance(inter_obj.get("button_reply"), dict):
            interactive_reply_id = str(inter_obj["button_reply"].get("id", "")).strip()
            interactive_reply_title = str(inter_obj["button_reply"].get("title", "")).strip()
        elif inter_type == "list_reply" and isinstance(inter_obj.get("list_reply"), dict):
            interactive_reply_id = str(inter_obj["list_reply"].get("id", "")).strip()
            interactive_reply_title = str(inter_obj["list_reply"].get("title", "")).strip()
        if interactive_reply_id and not text_content:
            text_content = interactive_reply_id

    # [CODE-MARKER: FIX-OBS-TELEMETRY-15] Structured inbound frame telemetry
    msg_type = str(msg.get("type") or ("interactive" if "interactive" in msg else "text"))
    logger.info(
        "[WhatsApp Ingress] Received frame type=%s wamid=%s from=%s interactive_id=%s",
        msg_type,
        message_id or "none",
        sender_phone,
        interactive_reply_id or "none",
    )

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

    base_url = resolve_public_base_url(base_url_override)

    user_tenant_id = user.tenant_id if user else settings.TENANT_ID
    allowed_cartridges = user.allowed_cartridges if user else None

    context: Dict[str, Any] = {
        "sender_phone": sender_phone,
        "correlation_id": correlation_id,
        "base_url": base_url,
        "image_bytes": raw_image_bytes,
        "user_coords": user_coords,
        "interactive_reply_id": interactive_reply_id,
        "interactive_reply_title": interactive_reply_title,
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
        # [CODE-MARKER: FIX-WA-SESSION-STICKY-20] Priority 0: Explicit colon-prefixed interactive action IDs
        cmd_lower = text_content.lower()
        if interactive_reply_id or ":" in cmd_lower:
            for app_id, app_inst in candidate_apps.items():
                app_keywords = getattr(app_inst, "keywords", [])
                if any(kw.lower() in cmd_lower for kw in app_keywords):
                    target_app = app_inst
                    break

        # Priority 0.5: Active interactive triage/conversation session check (with sibling keyword disambiguation)
        if not target_app and not is_image and not is_location:
            for app_id, app_inst in candidate_apps.items():
                if hasattr(app_inst, "has_active_session") and app_inst.has_active_session(sender_phone):
                    other_kw_match = any(
                        any(kw.lower() in cmd_lower for kw in getattr(other_inst, "keywords", []))
                        for other_id, other_inst in candidate_apps.items()
                        if other_id != app_id
                    )
                    if not other_kw_match or any(kw.lower() in cmd_lower for kw in getattr(app_inst, "keywords", [])):
                        target_app = app_inst
                        break

        # Priority 1: Match intent / keywords against active cartridges
        if not target_app:
            for app_id, app_inst in candidate_apps.items():
                app_keywords = getattr(app_inst, "keywords", [])
                if any(kw.lower() in cmd_lower for kw in app_keywords):
                    target_app = app_inst
                    break

        # Priority 2: If sender is a registered employee in any loaded cartridge
        if not target_app:
            for app_inst in candidate_apps.values():
                db_svc = getattr(app_inst, "db_service", None)
                if db_svc and hasattr(db_svc, "get_employee_by_phone"):
                    try:
                        if db_svc.get_employee_by_phone(sender_phone) is not None:
                            target_app = app_inst
                            logger.info(
                                "[WhatsApp Ingress] Registered employee %s routed to %s",
                                sender_phone,
                                app_inst.name,
                            )
                            break
                    except Exception:
                        pass

        # Priority 3: Native Location Payload routing to location-aware cartridge
        if not target_app and is_location:
            for app_inst in candidate_apps.values():
                keywords = getattr(app_inst, "keywords", [])
                if any(k in ("location", "gps", "geofence", "attendance", "kiosk") for k in keywords):
                    target_app = app_inst
                    break

        # Priority 4: Use SemanticRouter for natural language queries across cartridges (confident routes only)
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
                    and route_decision.confidence >= 0.75
                ):
                    target_app = candidate_apps[route_decision.selected_app]
                    logger.info(
                        "[WhatsApp Ingress] SemanticRouter directed query to '%s' (conf: %.2f)",
                        route_decision.selected_app,
                        route_decision.confidence,
                    )
            except Exception as ex:
                logger.warning("[WhatsApp Ingress] SemanticRouter routing attempt failed: %s", ex)

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
    interactive_buttons: Optional[List[Dict[str, str]]] = None
    interactive_list: Optional[Dict[str, Any]] = None
    header_image_bytes: Optional[bytes] = None
    header_text: Optional[str] = None
    footer_text: Optional[str] = None

    if target_app is not None:
        logger.info(
            "[WhatsApp Ingress] Routed wamid=%s to cartridge=%s",
            message_id or "none",
            getattr(target_app, "app_id", "unknown"),
        )
        handler = target_app.get_whatsapp_handler()
        if handler is not None and hasattr(handler, "dispatch"):
            try:
                from core_platform.app.middleware.tenant_context import (
                    UserContext,
                    async_cartridge_scope,
                    async_user_scope,
                )

                async with async_cartridge_scope(target_app.app_id):
                    if user is not None:
                        wa_user_ctx = UserContext(
                            user_id=user.id,
                            phone_number=user.phone_number,
                            tenant_id=user_tenant_id,
                            full_name=user.full_name or "",
                            role=user.role or "user",
                            user_secret_salt=getattr(user, "user_secret_salt", "") or "",
                            allowed_cartridges=tuple(allowed_cartridges or []),
                        )
                        async with async_user_scope(wa_user_ctx):
                            res_dispatch = await handler.dispatch(msg, context)
                    else:
                        res_dispatch = await handler.dispatch(msg, context)
                if isinstance(res_dispatch, dict):
                    reply_text = str(
                        res_dispatch.get("reply_message")
                        or res_dispatch.get("body_text")
                        or ""
                    )
                    response_kiosk_id = res_dispatch.get("kiosk_id")
                    btns = res_dispatch.get("interactive_buttons") or res_dispatch.get("buttons")
                    if isinstance(btns, list):
                        interactive_buttons = btns
                    raw_list = res_dispatch.get("interactive_list")
                    if isinstance(raw_list, dict):
                        interactive_list = raw_list
                    elif isinstance(raw_list, list):
                        interactive_list = {
                            "button_label": str(res_dispatch.get("button_label", "Open Decisions")),
                            "sections": raw_list,
                            "header_text": res_dispatch.get("header_text"),
                            "footer_text": res_dispatch.get("footer_text"),
                        }
                    if isinstance(res_dispatch.get("header_image_bytes"), bytes):
                        header_image_bytes = res_dispatch["header_image_bytes"]
                    if isinstance(res_dispatch.get("header_text"), str):
                        header_text = res_dispatch["header_text"]
                    if isinstance(res_dispatch.get("footer_text"), str):
                        footer_text = res_dispatch["footer_text"]
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

    # Dispatch outbound message via Meta Graph API (with dynamic tenant BYOK credentials)
    from core_platform.app.ingress.whatsapp_outbound import (
        send_whatsapp_interactive_buttons,
        send_whatsapp_interactive_list,
        send_whatsapp_message,
        upload_whatsapp_media,
    )

    dispatched_id: Optional[str] = None
    outbound_modality = "text"
    if interactive_buttons:
        outbound_modality = "interactive_buttons"
        media_id: Optional[str] = None
        if header_image_bytes:
            media_id = await upload_whatsapp_media(
                image_bytes=header_image_bytes,
                tenant_id=user_tenant_id,
            )
        dispatched_id = await send_whatsapp_interactive_buttons(
            to_phone=sender_phone,
            body_text=reply_text,
            buttons=interactive_buttons,
            header_media_id=media_id,
            header_text=header_text,
            footer_text=footer_text,
            tenant_id=user_tenant_id,
        )
    elif interactive_list:
        outbound_modality = "interactive_list"
        dispatched_id = await send_whatsapp_interactive_list(
            to_phone=sender_phone,
            body_text=reply_text,
            button_label=str(interactive_list.get("button_label", "Select Option")),
            sections=list(interactive_list.get("sections", [])),
            header_text=header_text or interactive_list.get("header_text"),
            footer_text=footer_text or interactive_list.get("footer_text"),
            tenant_id=user_tenant_id,
        )

    if not dispatched_id:
        await send_whatsapp_message(
            to_phone=sender_phone,
            text=reply_text,
            tenant_id=user_tenant_id,
        )

    # [CODE-MARKER: FIX-OBS-TELEMETRY-15] Emit SHA-256 Chained Tri-Format Audit Event (.jsonl, .csv, .html)
    try:
        from core_platform.app.telemetry.audit_engine import AuditEngine

        AuditEngine.get_instance().record_event(
            action_type="WHATSAPP_INTERACTIVE_DISPATCH",
            payload_summary={
                "wamid": message_id or "none",
                "sender_phone": sender_phone,
                "cartridge_id": getattr(target_app, "app_id", "core") if target_app else "core",
                "interactive_reply_id": interactive_reply_id or "none",
                "outbound_modality": outbound_modality,
                "has_png_card": bool(header_image_bytes),
            },
            operator_id=str(user.id) if user else sender_phone,
            kiosk_id=response_kiosk_id or node_id,
            correlation_id=correlation_id,
        )
    except Exception as audit_err:
        logger.debug("[WhatsApp Ingress] Non-fatal audit recording warning: %s", audit_err)

    result_payload: Dict[str, Any] = {
        "status": "EVENT_RECEIVED",
        "correlation_id": correlation_id,
        "node_id": node_id,
        "kiosk_id": response_kiosk_id or node_id,
        "reply_message": reply_text,
    }
    if interactive_buttons:
        result_payload["interactive_buttons"] = interactive_buttons
    if interactive_list:
        result_payload["interactive_list"] = interactive_list
    return result_payload


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

    public_base_url = extract_public_base_url(request)
    return await dispatch_whatsapp_payload(data, base_url_override=public_base_url)
