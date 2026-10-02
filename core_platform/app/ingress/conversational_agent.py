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
Conversational Fleet Coordinator Agent.

Adheres strictly to GEES v1.0 (Pillar 1 - Multi-Layered Safety Architecture).
Addresses ISSUE-002 and ISSUE-004: Multi-turn conversational intelligence for WhatsApp ingress.
Constrains LLM reasoning to clamped temperature (0.1) with live kiosk state grounding.
"""

import logging
from typing import Any, Optional

from core_platform.app.config import settings
from core_platform.app.llm.gateway import get_platform_llm_gateway
from core_platform.app.messaging.conversation_memory import ConversationMemory

logger = logging.getLogger("core_platform.ingress.conversational_agent")


async def generate_conversational_response(
    sender_phone: str,
    user_text: str,
    emp: Optional[Any],
    kiosk_id: str,
    kg_service: Optional[Any] = None,
    db_service: Optional[Any] = None,
    operation_id: Optional[str] = None,
) -> str:
    """Generate a context-aware, grounded response for an operator conversational query.

    Args:
        sender_phone: Operator phone number.
        user_text: Incoming WhatsApp text.
        emp: Registered employee DB object (if enrolled).
        kiosk_id: Active kiosk ID.
        kg_service: KnowledgeGraphService for station and HACCP metadata.
        db_service: DatabaseService for attendance and shift status.
        operation_id: Optional correlation identifier.

    Returns:
        Natural language coordinator reply formatted for WhatsApp.
    """
    memory = ConversationMemory.get_instance()
    history_str = memory.format_history_for_prompt(sender_phone, limit=6)

    # 1. Gather Live Grounding Context
    op_name = emp.full_name if emp else "Operator"
    op_code = emp.emp_code if emp else "Unregistered"
    op_role = emp.role if emp and emp.role else "OPERATOR"
    station_name = kiosk_id

    haccp_info = "Chiller temperature must be between 2.0°C and 8.0°C for food safety compliance."
    manager_info = "No direct reporting manager configured."

    if kg_service:
        kiosk_info = kg_service.get_kiosk_details(kiosk_id)
        if kiosk_info:
            station_name = f"{kiosk_info.get('name', kiosk_id)} ({kiosk_id})"
            haccp_rule = kiosk_info.get("haccp_rule", {})
            if haccp_rule:
                haccp_info = (
                    f"Permissible chiller temperature: {haccp_rule.get('min_temp_c', 2.0)}°C to "
                    f"{haccp_rule.get('max_temp_c', 8.0)}°C."
                )

    if db_service and emp and emp.reporting_manager_emp_code:
        mgr = db_service.get_employee_by_code(emp.reporting_manager_emp_code)
        if mgr:
            manager_info = f"Reporting Manager: {mgr.full_name} ({mgr.emp_code}, Phone: {mgr.phone_number})"

    # Check shift attendance status today
    attendance_status = "Not checked in yet today. Step 1: 1-click location verification; Step 2: selfie photo with chiller display."
    if db_service and emp:
        att = db_service.has_attendance_today(emp.emp_code)
        if att:
            attendance_status = f"Checked in at station {att.kiosk_id or kiosk_id}. HACCP Status: {att.haccp_status or 'COMPLIANT'}."

    # 2. Construct Grounded System Instruction
    system_instruction = (
        f"You are the AI Operational Assistant for {settings.ORGANIZATION_NAME}. You assist field operators "
        "and station supervisors in executing operations, shift procedures, and compliance reporting.\n"
        "Grounding Context:\n"
        f"- Operator Name: {op_name} ({op_code}, Role: {op_role})\n"
        f"- Active Station: {station_name}\n"
        f"- Operating Guidelines: {haccp_info}\n"
        f"- {manager_info}\n"
        f"- Today's Shift Status: {attendance_status}\n\n"
        "Guidelines:\n"
        "1. Be polite, professional, concise, and helpful in WhatsApp markdown format.\n"
        "2. Answer procedural, safety, operating, and shift questions accurately using Grounding Context.\n"
        "3. If the user asks to mark attendance or report metrics, explain the required verification steps.\n"
        "4. If there is a critical hardware emergency, electrical fault, or safety hazard, instruct them to press the Emergency Stop button and call their manager.\n"
        "5. Keep replies under 3-4 sentences whenever possible."
    )

    prompt = (
        f"Conversation History:\n{history_str}\n\n"
        f"Operator: {user_text}\n"
        "Assistant:"
    ) if history_str else (
        f"Operator: {user_text}\n"
        "Assistant:"
    )

    # 3. Invoke LLMGateway
    gateway = get_platform_llm_gateway()
    reply_text: Optional[str] = None

    try:
        res = await gateway.generate(
            task="text_generation",
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.1,
            response_mime_type="text/plain",
            operation_id=operation_id or "op_conversational_turn",
        )
        if res and isinstance(res, dict):
            reply_text = str(res.get("text") or res.get("response") or res.get("content") or "").strip()
        elif isinstance(res, str):
            reply_text = res.strip()
    except Exception as exc:
        logger.warning("[ConversationalAgent] LLMGateway generation error: %s", exc)
        reply_text = None

    # Deterministic Fallback if LLM unavailable
    if not reply_text:
        query_lower = user_text.lower()
        if any(w in query_lower for w in ["temp", "temperature", "chiller", "cooling", "degree", "celsius"]):
            reply_text = f"❄️ {haccp_info}\nPlease take and send a clear photo of the gauge display to record compliance."
        elif any(w in query_lower for w in ["manager", "supervisor", "boss", "lead", "contact"]):
            reply_text = f"👤 {manager_info}\nSend 'help' or your question directly, and it will be forwarded to your supervisor."
        elif any(w in query_lower for w in ["attendance", "duty", "punch", "checkin", "check-in"]):
            reply_text = (
                f"📋 Shift Attendance Status: {attendance_status}\n"
                "To punch in: 1) Verify location coordinates, 2) Send your verification photo."
            )
        else:
            reply_text = (
                f"👋 Hello {op_name}! I am your AI Operational Assistant for {station_name}.\n"
                "You can submit your check-in photo, send operational notes, or ask for help at any time."
            )

    # Record turns in SQLite memory
    memory.record_turn(sender_phone=sender_phone, role="user", content=user_text, intent="CONVERSATIONAL_QUERY")
    memory.record_turn(sender_phone=sender_phone, role="assistant", content=reply_text, intent="COORDINATOR_REPLY")

    return reply_text
