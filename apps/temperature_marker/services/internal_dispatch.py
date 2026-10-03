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
Internal Message Dispatcher, Manager Triage & Two-Way Quoted Reply Relay for Temperature Marker.

Adheres strictly to GEES v2.0 Microkernel Architecture (Rule 3).
1. Top-10 prioritized single-screen digest for managers on 'Hi' / greeting.
2. Step-by-step interactive 1-by-1 drill-down.
3. Two-way message relay attributing original operator note with 'Re: [quote]' context.
4. Meta Template Message bypass for critical emergencies / Tier 1 hazards.
5. Zero arbitrary @tagging.
"""

from datetime import datetime, timezone
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from core_platform.app.config import settings

logger = logging.getLogger("apps.temperature_marker.internal_dispatch")

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False


class ManagerTriageSessionManager:
    """Thread-safe state store for managers actively triaging pending messages."""

    _instance: Optional["ManagerTriageSessionManager"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ManagerTriageSessionManager":
        """Get singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        """Initialize triage store."""
        self._active_message: Dict[str, int] = {}  # manager_phone -> message_id
        self._current_index: Dict[str, int] = {}   # manager_phone -> index in list
        self._lock = threading.Lock()

    def set_active_message(self, manager_phone: str, message_id: int, index: int = 0) -> None:
        """Record the active message being reviewed by a manager."""
        clean = manager_phone.replace("+", "").replace(" ", "").strip()
        with self._lock:
            self._active_message[clean] = message_id
            self._current_index[clean] = index

    def get_active_message_id(self, manager_phone: str) -> Optional[int]:
        """Retrieve active message ID for a manager."""
        clean = manager_phone.replace("+", "").replace(" ", "").strip()
        with self._lock:
            return self._active_message.get(clean)

    def get_current_index(self, manager_phone: str) -> int:
        """Retrieve current navigation index for a manager."""
        clean = manager_phone.replace("+", "").replace(" ", "").strip()
        with self._lock:
            return self._current_index.get(clean, 0)

    def advance_index(self, manager_phone: str) -> int:
        """Increment current navigation index for a manager."""
        clean = manager_phone.replace("+", "").replace(" ", "").strip()
        with self._lock:
            curr = self._current_index.get(clean, 0) + 1
            self._current_index[clean] = curr
            return curr

    def clear_session(self, manager_phone: str) -> None:
        """Clear active triage state for a manager."""
        clean = manager_phone.replace("+", "").replace(" ", "").strip()
        with self._lock:
            self._active_message.pop(clean, None)
            self._current_index.pop(clean, None)


def _format_time_display(dt: Optional[datetime]) -> str:
    """Format UTC datetime into readable local/AM-PM string in IST."""
    if not dt:
        return ""
    from core_platform.app.common.timezone import to_local_ist
    return to_local_ist(dt)


def _get_priority_badge(priority: int) -> str:
    """Return visual icon for message priority."""
    if priority >= 100:
        return "🚨"
    if priority >= 75:
        return "⚠️"
    if priority >= 50:
        return "📦"
    return "❓"


def _short_summary(text: str, max_chars: int = 35) -> str:
    """Create clean single-line summary snippet."""
    cleaned = text.replace("\n", " ").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def build_top10_digest(
    manager_phone: str,
    manager_name: str,
    db_service: Any,
    session_mgr: Optional[ManagerTriageSessionManager] = None,
) -> str:
    """Compose prioritized single-screen digest and active Message 1 for manager.

    Args:
        manager_phone: Supervisor phone number.
        manager_name: Supervisor display name.
        db_service: Database service.
        session_mgr: Session manager instance.

    Returns:
        Formatted WhatsApp response text.
    """
    if session_mgr is None:
        session_mgr = ManagerTriageSessionManager.get_instance()

    total_pending = db_service.count_pending_messages_for_recipient(manager_phone)
    if total_pending == 0:
        session_mgr.clear_session(manager_phone)
        return (
            f"👋 Hello {manager_name}!\n"
            "🎉 0 pending messages in your queue. All kiosk operations running smoothly!"
        )

    pending_list = db_service.get_pending_messages_for_recipient(manager_phone, limit=10)
    lines: List[str] = [
        f"👋 Hello {manager_name}!",
        f"📬 {total_pending} messages pending (showing top {len(pending_list)}):",
    ]

    for idx, msg in enumerate(pending_list, start=1):
        badge = _get_priority_badge(msg.priority)
        snip = _short_summary(msg.message_text)
        lines.append(f"{idx}. {badge} {msg.kiosk_id} ({msg.sender_name}): {snip}")

    # Display Message 1 in full for immediate 1-by-1 reply
    first_msg = pending_list[0]
    session_mgr.set_active_message(manager_phone, first_msg.id, index=0)

    time_str = _format_time_display(first_msg.created_at_utc)
    badge = _get_priority_badge(first_msg.priority)

    lines.append("")
    lines.append(f"👉 Message 1 of {total_pending}:")
    lines.append("----------------------------------------")
    lines.append(f"{badge} From: {first_msg.sender_name} [{first_msg.kiosk_id}] ({time_str})")
    lines.append(f'"{first_msg.message_text}"')
    lines.append("----------------------------------------")
    lines.append("💬 Reply to this message to answer directly.")
    lines.append("(Send 'NEXT' to skip, or 'ALL' to view all)")

    return "\n".join(lines)


def handle_manager_navigation(
    manager_phone: str,
    manager_name: str,
    command: str,
    db_service: Any,
    session_mgr: Optional[ManagerTriageSessionManager] = None,
) -> str:
    """Handle navigation commands ('NEXT', 'SKIP', 'ALL') from manager.

    Args:
        manager_phone: Supervisor phone number.
        manager_name: Supervisor display name.
        command: Command string.
        db_service: Database service.
        session_mgr: Session manager instance.

    Returns:
        Formatted WhatsApp response text.
    """
    if session_mgr is None:
        session_mgr = ManagerTriageSessionManager.get_instance()

    cmd_lower = command.strip().lower()
    total_pending = db_service.count_pending_messages_for_recipient(manager_phone)
    if total_pending == 0:
        session_mgr.clear_session(manager_phone)
        return f"🎉 Zero pending messages in your queue, {manager_name}!"

    pending_list = db_service.get_pending_messages_for_recipient(manager_phone, limit=10)

    # Command 'ALL': list all top 10 messages with full text
    if cmd_lower in ["all", "list", "more"]:
        lines = [
            f"📋 All Pending Messages ({len(pending_list)} of {total_pending}):",
            "========================================",
        ]
        for idx, m in enumerate(pending_list, start=1):
            badge = _get_priority_badge(m.priority)
            t_str = _format_time_display(m.created_at_utc)
            lines.append(f"[{idx}] {badge} {m.sender_name} ({m.kiosk_id}) - {t_str}")
            lines.append(f'    "{m.message_text}"')
            lines.append("----------------------------------------")
        lines.append("👉 Reply with '<number>. <your answer>' (e.g. '1. Approved') to answer any specific message.")
        return "\n".join(lines)

    # Command 'NEXT' or 'SKIP': advance to next message
    curr_idx = session_mgr.advance_index(manager_phone)
    if curr_idx >= len(pending_list):
        curr_idx = 0
        session_mgr.set_active_message(manager_phone, pending_list[0].id, index=0)

    target_msg = pending_list[curr_idx]
    session_mgr.set_active_message(manager_phone, target_msg.id, index=curr_idx)

    badge = _get_priority_badge(target_msg.priority)
    time_str = _format_time_display(target_msg.created_at_utc)

    return (
        f"👉 Message {curr_idx + 1} of {total_pending}:\n"
        "----------------------------------------\n"
        f"{badge} From: {target_msg.sender_name} [{target_msg.kiosk_id}] ({time_str})\n"
        f'"{target_msg.message_text}"\n'
        "----------------------------------------\n"
        "💬 Reply to this message to answer directly.\n"
        "(Send 'NEXT' to skip, or 'ALL' to view all)"
    )


def build_fleet_executive_digest(
    manager_name: str,
    db_service: Any,
) -> str:
    """Build a comprehensive multi-kiosk status matrix for managers via WhatsApp.

    Adheres to User Requirements:
    1. Daily attendance per kiosk (active/checked-in vs overdue/missing, operator, time in IST).
    2. Multi-point temperature capture status (X / Y checks, latest reading, overdue flags).
    3. Active emergency safety alerts (HACCP hazards, biometric mismatches, geofence breaches).

    Args:
        manager_name: Manager/Supervisor display name.
        db_service: DatabaseService instance.

    Returns:
        Formatted WhatsApp digest string.
    """
    kiosks = db_service.get_kiosk_daily_attendance_summary()
    active_alerts = db_service.get_active_high_alerts()

    checked_in_count = sum(1 for k in kiosks if k.get("has_checkin_today"))
    total_kiosks = len(kiosks)

    lines: List[str] = [
        f"📊 *CANECTAR FLEET EXECUTIVE STATUS*",
        f"Manager: {manager_name}",
        f"Active Kiosks: {checked_in_count}/{total_kiosks} Checked-in",
        "========================================",
    ]

    # 1. High alerts section if any active
    if active_alerts:
        lines.append(f"🚨 *CRITICAL SAFETY ALERTS ({len(active_alerts)})*")
        for a in active_alerts[:3]:
            lines.append(f"• [{a['kiosk_id']}] {a['type']}: {a['description']} ({a['time_ist']})")
        lines.append("----------------------------------------")

    # 2. Per-kiosk status matrix
    for k in kiosks:
        k_id = k["kiosk_id"]
        site = k.get("name", k_id)
        has_checkin = k.get("has_checkin_today", False)
        op_name = k.get("checkin_operator_name") or (k.get("assigned_operators", ["Unassigned"])[0] if k.get("assigned_operators") else "Unassigned")
        checks_done = k.get("total_temp_checks_today", 0)
        req_checks = k.get("required_temp_checks", 3)
        latest_temp = k.get("latest_chiller_temp_c")
        is_overdue = k.get("is_temp_overdue", False)
        has_hazard = k.get("has_critical_hazard", False)

        if has_hazard:
            status_icon = "🚨"
        elif is_overdue:
            status_icon = "⚠️"
        elif has_checkin:
            status_icon = "✅"
        else:
            status_icon = "⭕"

        chk_str = f"In: {k.get('checkin_time_ist')}" if has_checkin else "NOT CHECKED IN"
        temp_str = f"{latest_temp:.1f}°C" if latest_temp is not None else "No Temp"
        progress_str = f"[{checks_done}/{req_checks} checks]"

        lines.append(f"{status_icon} *{k_id}* ({site})")
        lines.append(f"   👤 {op_name} | {chk_str}")
        lines.append(f"   ❄️ Chiller: {temp_str} {progress_str}{' (OVERDUE)' if is_overdue else ''}")
        lines.append("")

    lines.append("----------------------------------------")
    lines.append("👉 Type 'messages' for operator inbox, or 'help' for commands.")

    return "\n".join(lines)


def handle_manager_reply(
    manager_phone: str,
    manager_name: str,
    reply_text: str,
    quoted_wamid: Optional[str],
    db_service: Any,
    session_mgr: Optional[ManagerTriageSessionManager] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Resolve active or quoted message and construct two-way operator forwarding text.

    Args:
        manager_phone: Manager phone number.
        manager_name: Manager display name.
        reply_text: Manager's reply text.
        quoted_wamid: Optional WhatsApp message ID if manager swiped to reply.
        db_service: Database service.
        session_mgr: Session manager instance.

    Returns:
        Tuple of (manager_confirm_msg, operator_phone, operator_forward_msg).
    """
    if session_mgr is None:
        session_mgr = ManagerTriageSessionManager.get_instance()

    target_msg: Optional[Any] = None
    clean_reply = reply_text.strip()

    # 1. Quoted reply via WhatsApp wamid
    if quoted_wamid:
        target_msg = db_service.get_message_by_wamid(quoted_wamid)

    # 2. Numbered reply syntax, e.g. "1. We sent a technician"
    match_num = re.match(r"^(\d+)[\.\:\s]+(.*)$", clean_reply)
    if not target_msg and match_num:
        num_idx = int(match_num.group(1)) - 1
        clean_reply = match_num.group(2).strip()
        pending = db_service.get_pending_messages_for_recipient(manager_phone, limit=10)
        if 0 <= num_idx < len(pending):
            target_msg = pending[num_idx]

    # 3. Active message in triage session
    if not target_msg:
        active_id = session_mgr.get_active_message_id(manager_phone) if session_mgr else None
        if active_id and hasattr(db_service, "get_message_by_id"):
            target_msg = db_service.get_message_by_id(active_id)

    # 4. Fallback to top-1 pending message
    if not target_msg:
        pending = db_service.get_pending_messages_for_recipient(manager_phone, limit=1)
        if pending:
            target_msg = pending[0]

    if not target_msg:
        return (
            f"ℹ️ No active message found in your queue to reply to, {manager_name}. "
            "Send 'Hi' to view your current messages.",
            None,
            None,
        )

    # Resolve message in database
    resolved = db_service.resolve_internal_message(
        message_id=target_msg.id,
        reply_context=clean_reply,
        resolved_by_phone=manager_phone,
    )

    orig_snippet = _short_summary(target_msg.message_text, max_chars=40)

    # Construct Two-Way Quoted Forwarding Message to Operator
    operator_forward_msg = (
        f"📩 Reply from Supervisor {manager_name}:\n"
        f'Re: "{orig_snippet}"\n'
        "----------------------------------------\n"
        f'"{clean_reply}"\n'
        "----------------------------------------\n"
        f"Kiosk: {target_msg.kiosk_id}"
    )

    # Check remaining pending messages for manager
    remaining_count = db_service.count_pending_messages_for_recipient(manager_phone)
    if remaining_count == 0:
        session_mgr.clear_session(manager_phone)
        manager_confirm = (
            f"✅ Reply delivered to {target_msg.sender_name} ({target_msg.kiosk_id})!\n"
            f'Re: "{orig_snippet}"\n\n'
            "🎉 All pending messages in your queue have been resolved!"
        )
        return manager_confirm, target_msg.sender_phone, operator_forward_msg

    # Advance to next message for manager
    next_pending = db_service.get_pending_messages_for_recipient(manager_phone, limit=1)[0]
    session_mgr.set_active_message(manager_phone, next_pending.id, index=0)
    badge = _get_priority_badge(next_pending.priority)
    time_str = _format_time_display(next_pending.created_at_utc)

    manager_confirm = (
        f"✅ Reply delivered to {target_msg.sender_name} ({target_msg.kiosk_id})!\n"
        f'Re: "{orig_snippet}"\n\n'
        f"👉 Next Message (1 of {remaining_count}):\n"
        "----------------------------------------\n"
        f"{badge} From: {next_pending.sender_name} [{next_pending.kiosk_id}] ({time_str})\n"
        f'"{next_pending.message_text}"\n'
        "----------------------------------------\n"
        "💬 Reply to answer directly, or send 'NEXT' to skip."
    )

    return manager_confirm, target_msg.sender_phone, operator_forward_msg


async def send_whatsapp_raw_message(to_phone: str, text: str) -> bool:
    """Send an outbound WhatsApp message via Meta Cloud API if configured."""
    if not (settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID and _HAS_HTTPX and httpx is not None):
        logger.info("[Internal Dispatch] Meta Cloud API not configured; simulated outbound to %s: %s", to_phone, text[:60])
        return True

    clean_to = to_phone.replace("+", "").replace(" ", "").replace("-", "").strip()
    url = f"https://graph.facebook.com/v21.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_to,
        "type": "text",
        "text": {"body": text},
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            return resp.is_success
    except Exception as err:
        logger.error("[Internal Dispatch] Failed to send outbound WhatsApp message: %s", err)
        return False


async def send_urgent_meta_template_alert(
    recipient_phone: str,
    operator_name: str,
    kiosk_id: str,
    alert_summary: str,
) -> bool:
    """Send a pre-approved Meta WhatsApp Template message to bypass the 24h window for Tier 1 hazards.

    Args:
        recipient_phone: Manager or supervisor phone number.
        operator_name: Sender employee name.
        kiosk_id: Kiosk physical identifier.
        alert_summary: Brief description of the urgent breakdown or safety hazard.

    Returns:
        True if sent successfully or simulated cleanly.
    """
    clean_to = recipient_phone.replace("+", "").replace(" ", "").replace("-", "").strip()
    logger.info(
        "[Internal Dispatch] Triggering Meta Template urgent alert to %s for kiosk %s (hazard: %s)",
        clean_to,
        kiosk_id,
        alert_summary[:40],
    )

    if not (settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID and _HAS_HTTPX and httpx is not None):
        return True

    url = f"https://graph.facebook.com/v21.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    template_body = {
        "messaging_product": "whatsapp",
        "to": clean_to,
        "type": "template",
        "template": {
            "name": "urgent_operator_alert",
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": operator_name},
                        {"type": "text", "text": kiosk_id},
                        {"type": "text", "text": alert_summary},
                    ],
                }
            ],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=template_body)
            return resp.is_success
    except Exception as err:
        logger.error("[Internal Dispatch] Failed to send Meta Template alert: %s", err)
        return False
