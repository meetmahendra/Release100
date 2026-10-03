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

"""High-Priority Safety & Operational Alert Dispatcher.

Handles multi-channel alert delivery (WhatsApp push to supervisor & dashboard tracking)
with in-memory de-duplication to prevent spamming operators or managers during repeated readings.
"""

import asyncio
from datetime import datetime, timezone
import logging
import threading
from typing import Dict, Optional, Tuple

from core_platform.app.config import settings

logger = logging.getLogger("apps.temperature_marker.alert_dispatcher")

# Cooldown registry: (kiosk_id, alert_type) -> last_dispatched_timestamp
_ALERT_COOLDOWN: Dict[Tuple[str, str], float] = {}
_COOLDOWN_LOCK = threading.Lock()
_DEFAULT_COOLDOWN_SECONDS = 3600.0  # 1 hour per incident type


def should_dispatch_alert(kiosk_id: str, alert_type: str, cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS) -> bool:
    """Check if an alert should be dispatched or if it is currently in cooldown.

    Args:
        kiosk_id: Physical kiosk identifier.
        alert_type: Type of alert ('HACCP_HAZARD', 'BIOMETRIC_MISMATCH', etc.).
        cooldown_seconds: Cooldown duration in seconds.

    Returns:
        True if the alert can be dispatched, False if silenced.
    """
    key = (kiosk_id, alert_type)
    now = datetime.now(timezone.utc).timestamp()
    with _COOLDOWN_LOCK:
        last_sent = _ALERT_COOLDOWN.get(key, 0.0)
        if (now - last_sent) >= cooldown_seconds:
            _ALERT_COOLDOWN[key] = now
            return True
        return False


def reset_alert_cooldown(kiosk_id: Optional[str] = None) -> None:
    """Reset the cooldown cache (useful for testing)."""
    with _COOLDOWN_LOCK:
        if kiosk_id:
            keys_to_del = [k for k in _ALERT_COOLDOWN if k[0] == kiosk_id]
            for k in keys_to_del:
                del _ALERT_COOLDOWN[k]
        else:
            _ALERT_COOLDOWN.clear()


async def dispatch_critical_hazard_alert(
    kiosk_id: str,
    operator_name: str,
    alert_type: str,
    details: str,
    supervisor_phone: Optional[str] = None,
) -> bool:
    """Dispatch immediate WhatsApp high-alert to supervisor with cooldown de-duplication.

    Args:
        kiosk_id: Kiosk code.
        operator_name: Name of reporting operator.
        alert_type: Alert classification ('HACCP_HAZARD', 'BIOMETRIC_MISMATCH', etc.).
        details: Short summary text.
        supervisor_phone: Target supervisor WhatsApp number.

    Returns:
        True if dispatched or accepted for delivery, False if suppressed.
    """
    if not should_dispatch_alert(kiosk_id, alert_type):
        logger.info(
            "[AlertDispatcher] Suppressing duplicate alert %s for kiosk %s (cooldown active)",
            alert_type,
            kiosk_id,
        )
        return False

    target_phone = supervisor_phone or getattr(settings, "SUPERVISOR_PHONE", "+919800000000")
    if not target_phone:
        return False

    alert_text = (
        f"🚨 IMMEDIATE SAFETY ALERT: {alert_type}\n"
        f"Machine: {kiosk_id}\n"
        f"Operator: {operator_name}\n"
        f"Details: {details}\n\n"
        f"👉 Action: Please inspect via Admin Console or contact kiosk operator immediately."
    )

    from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
    from apps.temperature_marker.services.internal_dispatch import send_urgent_meta_template_alert

    # Async background delivery
    try:
        asyncio.create_task(send_whatsapp_message(target_phone, alert_text))
        asyncio.create_task(
            send_urgent_meta_template_alert(
                recipient_phone=target_phone,
                operator_name=operator_name,
                kiosk_id=kiosk_id,
                alert_summary=details[:60],
            )
        )
        logger.info(
            "[AlertDispatcher] Successfully dispatched high-alert %s to supervisor %s",
            alert_type,
            target_phone,
        )
        return True
    except Exception as exc:
        logger.error("[AlertDispatcher] Failed to dispatch alert to %s: %s", target_phone, exc)
        return False
