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
from typing import Optional
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
