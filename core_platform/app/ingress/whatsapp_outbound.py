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


async def send_whatsapp_message(to_phone: str, text: str) -> Optional[str]:
    """Send an outbound text message to a user WhatsApp phone via Meta Graph API v21.0.

    Args:
        to_phone: Target phone number (E.164 or numeric).
        text: Plain-text message body.

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
    if not (settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID):
        logger.warning("[WhatsApp Outbound] WhatsApp credentials not configured; skipping dispatch to +%s", clean_to)
        return None

    if not _HAS_HTTPX or httpx is None:
        logger.error("[WhatsApp Outbound] httpx is not installed; cannot deliver outbound message.")
        return None

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
                "text": {"body": text},
            }
            logger.info("[WhatsApp Outbound] Dispatching message to +%s (text length: %d)", clean_to, len(text))
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
