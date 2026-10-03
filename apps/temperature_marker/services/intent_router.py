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
Ingress Intent Inference Engine for Temperature & Attendance Marker Cartridge.

Adheres strictly to GEES v2.0 Microkernel Architecture (Rule 3).
Classifies inbound WhatsApp interactions for kiosk operations:
- ATTENDANCE_CHECKIN: Shift check-in photos, selfies, and chiller gauge logs.
- OPERATOR_QUERY: Machine issues, supply requests, and notes for reporting manager.
- OPERATOR_GREETING: Self-service shift status dashboard greeting.
- MANAGER_GREETING: Supervisor/manager typing 'hi' or checking queue digest.
- MANAGER_REPLY: Supervisor replying to an operator's open inquiry.
- SYSTEM_COMMAND: Built-in commands (help, kiosk, register, location).
"""

from enum import Enum
import re
from typing import Tuple
from pydantic import BaseModel, Field


class IngressIntent(str, Enum):
    """Categorization of incoming conversational and operational messages."""

    ATTENDANCE_CHECKIN = "ATTENDANCE_CHECKIN"
    OPERATOR_QUERY = "OPERATOR_QUERY"
    OPERATOR_GREETING = "OPERATOR_GREETING"
    MANAGER_GREETING = "MANAGER_GREETING"
    MANAGER_REPLY = "MANAGER_REPLY"
    SYSTEM_COMMAND = "SYSTEM_COMMAND"


class IngressClassification(BaseModel):
    """Structured classification result produced by the Intent Inference Engine."""

    intent: IngressIntent
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence")
    priority: int = Field(default=50, description="100=Critical, 75=Urgent, 50=Standard, 25=Query")
    category: str = Field(default="general", description="Subcategory: emergency, breakdown, supply, general")
    reasoning: str = Field(description="Deterministic inference rationale")


# Priority keyword dictionaries
_CRITICAL_KEYWORDS = {
    "fire", "smoke", "accident", "injury", "electric", "shock",
    "police", "theft", "breakdown", "spoilage", "emergency", "hazard",
    "collapsed", "exploded", "spark",
}

_URGENT_KEYWORDS = {
    "urgent", "leak", "leaking", "vibrat", "vibration", "grind",
    "grinding", "noise", "high temp", "warm", "stopped", "stuck",
    "broken", "failed", "cut", "jammed", "overheat", "smell",
}

_SUPPLY_KEYWORDS = {
    "cup", "cups", "straw", "straws", "ice", "cane", "sugar",
    "syrup", "cleaning", "stock", "bags", "bottle", "bottles",
    "lid", "lids", "sanitizer", "gloves", "napkin", "napkins",
}

_QUERY_KEYWORDS = {
    "when", "how", "who", "shift", "leave", "timing", "salary",
    "payout", "bonus", "holiday", "break", "lunch", "rule", "policy",
}

_MANAGER_GREETING_WORDS = {
    "hi", "hello", "hey", "digest", "queue", "pending", "review",
    "summary", "messages", "start", "triage", "inbox", "tasks",
}

_OPERATOR_GREETING_WORDS = {
    "hi", "hello", "hey", "hii", "helo", "good morning", "gm",
    "good afternoon", "good evening", "namaste", "namaskar",
    "greetings", "yo", "morning", "afternoon", "evening",
}


def infer_message_priority_and_category(text: str) -> Tuple[int, str]:
    """Determine message priority and category from content keywords.

    Returns:
        Tuple of (priority_int, category_str).
        100: Critical emergency/hazard
        75: Urgent mechanical or food safety alert
        50: Standard supply request or operational update
        25: General employee query
    """
    cleaned = text.lower()
    words = set(re.findall(r"\b\w+\b", cleaned))

    # 1. Critical Emergency / Hazard
    if any(k in cleaned for k in _CRITICAL_KEYWORDS):
        return 100, "emergency"

    # 2. Urgent Mechanical / Breakdown
    if any(k in cleaned for k in _URGENT_KEYWORDS):
        return 75, "breakdown"

    # 3. Supply Requests
    if any(k in words for k in _SUPPLY_KEYWORDS) or any(k in cleaned for k in ["run out", "running low", "out of", "need more"]):
        return 50, "supply"

    # 4. Queries
    if any(k in words for k in _QUERY_KEYWORDS) or "?" in text:
        return 25, "query"

    # Default operational note
    return 50, "operational_note"


def classify_ingress_intent(
    text: str,
    is_image: bool,
    sender_role: str = "OPERATOR",
    has_quoted_reply: bool = False,
    has_active_triage: bool = False,
) -> IngressClassification:
    """Classify incoming interaction into an actionable intent.

    Args:
        text: Message body or photo caption.
        is_image: True if message contains an attached photo.
        sender_role: 'OPERATOR', 'SUPERVISOR', 'MANAGER', or 'ADMIN'.
        has_quoted_reply: True if this WhatsApp message quotes a previous message.
        has_active_triage: True if supervisor has an ongoing active message triage session.

    Returns:
        IngressClassification instance.
    """
    cmd_lower = text.strip().lower()
    sender_role_upper = (sender_role or "OPERATOR").upper()
    is_manager_role = any(r in sender_role_upper for r in ["SUPERVISOR", "MANAGER", "ADMIN"])

    # 1. Images are classified as Attendance / Chiller verification by default
    if is_image:
        return IngressClassification(
            intent=IngressIntent.ATTENDANCE_CHECKIN,
            confidence=0.98,
            priority=50,
            category="attendance_chiller",
            reasoning="Inbound photo payload routes to attendance & chiller verification workflow.",
        )

    # 2. Explicit System Commands
    if cmd_lower in ["help", "/help", "#help", "menu", "status", "/status", "fleet", "dashboard", "alerts"]:
        return IngressClassification(
            intent=IngressIntent.SYSTEM_COMMAND,
            confidence=1.0,
            priority=25,
            category="system",
            reasoning="System command or fleet overview.",
        )

    if cmd_lower in ["kiosk", "kiosks", "kiosk list", "kiosks list"] or cmd_lower.startswith("kiosk ") or cmd_lower.startswith("switch "):
        return IngressClassification(
            intent=IngressIntent.SYSTEM_COMMAND,
            confidence=1.0,
            priority=25,
            category="system",
            reasoning="Kiosk management command.",
        )

    if cmd_lower.startswith("register") or cmd_lower.startswith("onboard"):
        return IngressClassification(
            intent=IngressIntent.SYSTEM_COMMAND,
            confidence=1.0,
            priority=50,
            category="system",
            reasoning="Employee registration command.",
        )

    if cmd_lower in ["location", "loc", "gps", "link", "/location", "/loc"]:
        return IngressClassification(
            intent=IngressIntent.SYSTEM_COMMAND,
            confidence=1.0,
            priority=50,
            category="system",
            reasoning="Explicit geolocation link request.",
        )

    if any(cmd_lower.startswith(p) for p in ["mail", "#email", "/mail", "email", "approve", "reject"]):
        return IngressClassification(
            intent=IngressIntent.SYSTEM_COMMAND,
            confidence=1.0,
            priority=50,
            category="system",
            reasoning="Mail or task approval command.",
        )

    # 3. Manager / Supervisor Triage Interactions
    if is_manager_role:
        if cmd_lower in _MANAGER_GREETING_WORDS:
            return IngressClassification(
                intent=IngressIntent.MANAGER_GREETING,
                confidence=0.95,
                priority=50,
                category="triage_digest",
                reasoning="Manager greeting or digest trigger.",
            )

        if has_quoted_reply or has_active_triage:
            return IngressClassification(
                intent=IngressIntent.MANAGER_REPLY,
                confidence=0.99,
                priority=50,
                category="triage_reply",
                reasoning="Manager replied to active triage message or quoted reply.",
            )

        # Numerical drilldown or reply commands (e.g. "1. tech sent", "next", "all", "reply ...")
        if (
            cmd_lower in ["next", "skip", "all", "list", "more"]
            or cmd_lower.startswith("reply ")
            or re.match(r"^\d+[\.\:\s]", cmd_lower)
        ):
            return IngressClassification(
                intent=IngressIntent.MANAGER_REPLY,
                confidence=0.92,
                priority=50,
                category="triage_action",
                reasoning="Manager interactive reply or navigation command.",
            )

    # 4. Explicit Attendance check-in text commands
    if any(cmd_lower.startswith(p) for p in ["checkin", "check-in", "duty", "attendance", "login", "punch"]):
        return IngressClassification(
            intent=IngressIntent.ATTENDANCE_CHECKIN,
            confidence=0.90,
            priority=50,
            category="attendance_checkin",
            reasoning="Explicit attendance check-in keyword.",
        )

    # 5. Friendly Greetings from Operators (interactive self-service status)
    if not is_manager_role:
        prio, cat = infer_message_priority_and_category(text)
        if prio < 75:  # Not an urgent breakdown or emergency
            if (
                cmd_lower in _OPERATOR_GREETING_WORDS
                or bool(re.match(r"^(hi|hello|hey|hii|helo|namaste|namaskar|good\s+(morning|afternoon|evening))\b", cmd_lower))
            ):
                return IngressClassification(
                    intent=IngressIntent.OPERATOR_GREETING,
                    confidence=0.98,
                    priority=25,
                    category="operator_greeting",
                    reasoning="Operator conversational greeting and operational status check.",
                )

    # 6. Non-attendance operational notes / supply requests from operators
    # Automatically route directly to reporting manager without requiring @tagging
    priority, category = infer_message_priority_and_category(text)
    return IngressClassification(
        intent=IngressIntent.OPERATOR_QUERY,
        confidence=0.92,
        priority=priority,
        category=category,
        reasoning=f"Operator operational note classified with priority {priority} ({category}).",
    )
