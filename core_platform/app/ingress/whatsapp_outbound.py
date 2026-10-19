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
Reusable Outbound Meta WhatsApp Cloud API Dispatcher.

Handles payload sanitation, formatting, bearer authorization, and
v21.0 Graph API message delivery with robust logging and causal error propagation.
"""

import logging
from typing import Any, Dict, List, Optional
from core_platform.app.config import settings

logger = logging.getLogger("core_platform.ingress.whatsapp_outbound")

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False


def resolve_whatsapp_credentials(
    tenant_id: Optional[str] = None,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve WhatsApp access token and phone number ID for a given tenant or platform fallback.

    Args:
        tenant_id: Optional multi-tenant partition identifier.
        access_token: Explicit access token (highest priority).
        phone_number_id: Explicit phone number ID (highest priority).

    Returns:
        Tuple of (resolved_token, resolved_phone_id).
    """
    token = access_token.strip() if access_token and access_token.strip() else None
    phone_id = phone_number_id.strip() if phone_number_id and phone_number_id.strip() else None

    if (not token or not phone_id) and tenant_id and tenant_id not in ("public", "system", "default", "default_tenant"):
        try:
            from ops_control_plane.devops_vault import DevOpsKeyVault
            vault = DevOpsKeyVault()
            creds = vault.get_tenant_runtime_credentials(tenant_id)
            if creds:
                if not token and creds.waba_token:
                    token = creds.waba_token
                if not phone_id and creds.waba_phone_number_id:
                    phone_id = creds.waba_phone_number_id
        except Exception as ex:
            logger.debug("[WhatsApp Outbound] Error resolving tenant vault credentials for %s: %s", tenant_id, ex)

    if not token and settings.WHATSAPP_ACCESS_TOKEN:
        token = settings.WHATSAPP_ACCESS_TOKEN
    if not phone_id and settings.WHATSAPP_PHONE_NUMBER_ID:
        phone_id = settings.WHATSAPP_PHONE_NUMBER_ID

    return token, phone_id


async def send_whatsapp_message(
    to_phone: str,
    text: str,
    tenant_id: Optional[str] = None,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> Optional[str]:
    """Send an outbound text message to a user WhatsApp phone via Meta Graph API v21.0.

    Args:
        to_phone: Target phone number (E.164 or numeric).
        text: Plain-text message body.
        tenant_id: Optional tenant ID for dynamic BYOK credentials resolution.
        access_token: Optional explicit access token override.
        phone_number_id: Optional explicit phone number ID override.

    Returns:
        Message ID if sent successfully, None otherwise.
    """
    from core_platform.app.common.phone_validator import normalize_phone_number

    try:
        norm_phone = normalize_phone_number(to_phone)
        clean_to = norm_phone.lstrip("+")
    except Exception as exc:
        logger.error("[WhatsApp Outbound] Invalid destination phone number '%s': %s", to_phone, exc)
        return None

    waba_token, waba_phone_id = resolve_whatsapp_credentials(
        tenant_id=tenant_id,
        access_token=access_token,
        phone_number_id=phone_number_id,
    )

    if not (waba_token and waba_phone_id):
        logger.warning("[WhatsApp Outbound] WhatsApp credentials not configured for tenant '%s'; skipping dispatch to +%s", tenant_id or "default", clean_to)
        return None

    if not _HAS_HTTPX or httpx is None:
        logger.error("[WhatsApp Outbound] httpx is not installed; cannot deliver outbound message.")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://graph.facebook.com/v21.0/{waba_phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {waba_token}",
                "Content-Type": "application/json",
            }
            outbound_body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": clean_to,
                "type": "text",
                "text": {"body": text},
            }
            logger.info("[WhatsApp Outbound] Dispatching message to +%s via phone_id %s (tenant: %s, length: %d)", clean_to, waba_phone_id, tenant_id or "default", len(text))
            resp = await client.post(url, headers=headers, json=outbound_body)
            if resp.is_success:
                resp_data = resp.json()
                outbound_id = str(resp_data.get("messages", [{}])[0].get("id", "SENT"))
                logger.info("[WhatsApp Outbound] Successfully delivered to +%s (ID: %s)", clean_to, outbound_id)
                return outbound_id
            else:
                logger.error("[WhatsApp Outbound] Meta API returned %d: %s", resp.status_code, resp.text)
                return None
    except Exception as exc:
        logger.error("[WhatsApp Outbound] Dispatch exception for +%s: %s", clean_to, exc)
        return None


# [CODE-MARKER: CP-WA-01] Meta Cloud API v21.0 Media Upload, Interactive Buttons, List Drawer & Templates
async def upload_whatsapp_media(
    image_bytes: bytes,
    mime_type: str = "image/png",
    filename: str = "executive_card.png",
    tenant_id: Optional[str] = None,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> Optional[str]:
    """Upload binary image bytes to Meta Graph API v21.0 and return the media_id."""
    if not image_bytes:
        return None

    waba_token, waba_phone_id = resolve_whatsapp_credentials(
        tenant_id=tenant_id,
        access_token=access_token,
        phone_number_id=phone_number_id,
    )
    if not (waba_token and waba_phone_id) or not _HAS_HTTPX or httpx is None:
        return None

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            url = f"https://graph.facebook.com/v21.0/{waba_phone_id}/media"
            headers = {"Authorization": f"Bearer {waba_token}"}
            files = {"file": (filename, image_bytes, mime_type)}
            data = {"messaging_product": "whatsapp", "type": mime_type}
            logger.info(
                "[WhatsApp Outbound] Uploading media (%s, %d bytes) via phone_id %s",
                filename,
                len(image_bytes),
                waba_phone_id,
            )
            resp = await client.post(url, headers=headers, data=data, files=files)
            if resp.is_success:
                media_id = resp.json().get("id")
                logger.info("[WhatsApp Outbound] Uploaded media_id=%s (%d bytes)", media_id, len(image_bytes))
                return str(media_id) if media_id else None
            logger.warning("[WhatsApp Outbound] Media upload returned %d: %s", resp.status_code, resp.text)
            return None
    except Exception as exc:
        logger.warning("[WhatsApp Outbound] Media upload exception: %s", exc)
        return None


async def send_whatsapp_interactive_buttons(
    to_phone: str,
    body_text: str,
    buttons: List[Dict[str, str]],
    *,
    header_media_id: Optional[str] = None,
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
    tenant_id: Optional[str] = None,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> Optional[str]:
    """Send an interactive button message (up to 3 reply buttons + optional image header) via Meta API v21.0."""
    from core_platform.app.common.phone_validator import normalize_phone_number

    try:
        norm_phone = normalize_phone_number(to_phone)
        clean_to = norm_phone.lstrip("+")
    except Exception as exc:
        logger.error("[WhatsApp Outbound] Invalid destination phone '%s': %s", to_phone, exc)
        return None

    waba_token, waba_phone_id = resolve_whatsapp_credentials(
        tenant_id=tenant_id,
        access_token=access_token,
        phone_number_id=phone_number_id,
    )
    if not (waba_token and waba_phone_id) or not _HAS_HTTPX or httpx is None:
        return None

    action_buttons: List[Dict[str, Any]] = []
    for btn in buttons[:3]:
        btn_id = str(btn.get("id", "act")).strip()[:256]
        btn_title = str(btn.get("title", "Select")).strip()[:20]
        action_buttons.append({
            "type": "reply",
            "reply": {"id": btn_id, "title": btn_title},
        })

    if not action_buttons:
        return await send_whatsapp_message(
            to_phone=to_phone,
            text=body_text,
            tenant_id=tenant_id,
            access_token=access_token,
            phone_number_id=phone_number_id,
        )

    interactive_obj: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text[:1024]},
        "action": {"buttons": action_buttons},
    }
    if header_media_id:
        interactive_obj["header"] = {"type": "image", "image": {"id": header_media_id}}
    elif header_text:
        interactive_obj["header"] = {"type": "text", "text": header_text[:60]}
    if footer_text:
        interactive_obj["footer"] = {"text": footer_text[:60]}

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_to,
        "type": "interactive",
        "interactive": interactive_obj,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://graph.facebook.com/v21.0/{waba_phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {waba_token}",
                "Content-Type": "application/json",
            }
            # [CODE-MARKER: FIX-OBS-TELEMETRY-15] Structured outbound interactive_buttons telemetry
            logger.info(
                "[WhatsApp Outbound] Dispatching interactive_buttons (%d buttons, media_id=%s) to +%s",
                len(action_buttons),
                header_media_id or "none",
                clean_to,
            )
            resp = await client.post(url, headers=headers, json=payload)
            if resp.is_success:
                resp_data = resp.json()
                outbound_id = str(resp_data.get("messages", [{}])[0].get("id", "SENT"))
                logger.info(
                    "[WhatsApp Outbound] Delivered interactive_buttons to +%s (ID: %s)",
                    clean_to,
                    outbound_id,
                )
                return outbound_id
            logger.error("[WhatsApp Outbound] Interactive buttons returned %d: %s", resp.status_code, resp.text)
            return None
    except Exception as exc:
        logger.error("[WhatsApp Outbound] Interactive buttons exception: %s", exc)
        return None


async def send_whatsapp_interactive_list(
    to_phone: str,
    body_text: str,
    button_label: str,
    sections: List[Dict[str, Any]],
    *,
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
    tenant_id: Optional[str] = None,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> Optional[str]:
    """Send a native Meta WhatsApp interactive list drawer (up to 10 rows) via Graph API v21.0."""
    from core_platform.app.common.phone_validator import normalize_phone_number

    try:
        norm_phone = normalize_phone_number(to_phone)
        clean_to = norm_phone.lstrip("+")
    except Exception as exc:
        logger.error("[WhatsApp Outbound] Invalid destination phone '%s': %s", to_phone, exc)
        return None

    waba_token, waba_phone_id = resolve_whatsapp_credentials(
        tenant_id=tenant_id,
        access_token=access_token,
        phone_number_id=phone_number_id,
    )
    if not (waba_token and waba_phone_id) or not _HAS_HTTPX or httpx is None:
        return None

    # [CODE-MARKER: FIX-WA-LIST-01] Defensively enforce Meta v21.0 interactive list length limits
    sanitized_sections: List[Dict[str, Any]] = []
    total_rows = 0
    for sec in sections[:10]:
        sec_title = str(sec.get("title") or "Options")[:24]
        raw_rows = sec.get("rows") or []
        clean_rows: List[Dict[str, str]] = []
        for r in raw_rows[:10]:
            clean_rows.append({
                "id": str(r.get("id") or "row_id")[:200],
                "title": str(r.get("title") or "Item")[:24],
                "description": str(r.get("description") or "")[:72],
            })
        if clean_rows:
            total_rows += len(clean_rows)
            sanitized_sections.append({"title": sec_title, "rows": clean_rows})

    interactive_obj: Dict[str, Any] = {
        "type": "list",
        "body": {"text": body_text[:1024]},
        "action": {
            "button": button_label[:20],
            "sections": sanitized_sections or sections,
        },
    }
    if header_text:
        interactive_obj["header"] = {"type": "text", "text": header_text[:60]}
    if footer_text:
        interactive_obj["footer"] = {"text": footer_text[:60]}

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_to,
        "type": "interactive",
        "interactive": interactive_obj,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://graph.facebook.com/v21.0/{waba_phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {waba_token}",
                "Content-Type": "application/json",
            }
            # [CODE-MARKER: FIX-OBS-TELEMETRY-15] Structured outbound interactive_list telemetry
            logger.info(
                "[WhatsApp Outbound] Dispatching interactive_list (button='%s', %d rows) to +%s",
                button_label[:20],
                total_rows,
                clean_to,
            )
            resp = await client.post(url, headers=headers, json=payload)
            if resp.is_success:
                resp_data = resp.json()
                outbound_id = str(resp_data.get("messages", [{}])[0].get("id", "SENT"))
                logger.info(
                    "[WhatsApp Outbound] Delivered interactive_list to +%s (ID: %s)",
                    clean_to,
                    outbound_id,
                )
                return outbound_id
            logger.error("[WhatsApp Outbound] Interactive list returned %d: %s", resp.status_code, resp.text)
            return None
    except Exception as exc:
        logger.error("[WhatsApp Outbound] Interactive list exception: %s", exc)
        return None


async def send_whatsapp_template(
    to_phone: str,
    template_name: str,
    language_code: str = "en_US",
    components: Optional[List[Dict[str, Any]]] = None,
    *,
    body_parameters: Optional[List[str]] = None,
    quick_reply_payloads: Optional[List[str]] = None,
    tenant_id: Optional[str] = None,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> Optional[str]:
    """Send a pre-approved Meta Utility Template message outside the 24-hour customer care window."""
    from core_platform.app.common.phone_validator import normalize_phone_number

    try:
        norm_phone = normalize_phone_number(to_phone)
        clean_to = norm_phone.lstrip("+")
    except Exception as exc:
        logger.error("[WhatsApp Outbound] Invalid destination phone '%s': %s", to_phone, exc)
        return None

    waba_token, waba_phone_id = resolve_whatsapp_credentials(
        tenant_id=tenant_id,
        access_token=access_token,
        phone_number_id=phone_number_id,
    )
    if not (waba_token and waba_phone_id) or not _HAS_HTTPX or httpx is None:
        return None

    eff_components: List[Dict[str, Any]] = list(components or [])
    if body_parameters and not eff_components:
        eff_components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in body_parameters],
        })
    if quick_reply_payloads:
        for idx, q_payload in enumerate(quick_reply_payloads[:3]):
            eff_components.append({
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(idx),
                "parameters": [{"type": "payload", "payload": str(q_payload)}],
            })

    template_obj: Dict[str, Any] = {
        "name": template_name,
        "language": {"code": language_code},
    }
    if eff_components:
        template_obj["components"] = eff_components

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_to,
        "type": "template",
        "template": template_obj,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://graph.facebook.com/v21.0/{waba_phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {waba_token}",
                "Content-Type": "application/json",
            }
            resp = await client.post(url, headers=headers, json=payload)
            if resp.is_success:
                resp_data = resp.json()
                return str(resp_data.get("messages", [{}])[0].get("id", "SENT"))
            logger.error("[WhatsApp Outbound] Template dispatch returned %d: %s", resp.status_code, resp.text)
            return None
    except Exception as exc:
        logger.error("[WhatsApp Outbound] Template dispatch exception: %s", exc)
        return None
