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
Domain-Specific WhatsApp Ingress Handler for Temperature & Attendance Marker.

Adheres strictly to GEES v2.0 Microkernel Architecture (Rule 3).
Owns all KioskNode kiosk, station roster, attendance check-in, operator onboarding,
and chiller gauge verification conversational interactions over WhatsApp.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from apps.temperature_marker.services.conversational_agent import generate_conversational_response
from apps.temperature_marker.services.intent_router import (
    IngressIntent,
    classify_ingress_intent,
    infer_message_priority_and_category,
)
from apps.temperature_marker.services.internal_dispatch import (
    ManagerTriageSessionManager,
    build_fleet_executive_digest,
    build_top10_digest,
    handle_manager_navigation,
    handle_manager_reply,
    send_whatsapp_raw_message,
)
from core_platform.app.common.timezone import to_local_ist
from core_platform.app.config import settings
from core_platform.app.skills.face_recognizer import get_platform_face_recognizer

logger = logging.getLogger("apps.temperature_marker.whatsapp_handler")


class TemperatureMarkerWhatsAppHandler:
    """Domain-specific WhatsApp conversational handler for Temperature Marker Cartridge."""

    def __init__(
        self,
        db_service: DatabaseService,
        kg_service: KnowledgeGraphService,
        workflow: TemperatureMarkerWorkflow,
    ) -> None:
        """Initialize with domain database, knowledge graph, and workflow engine."""
        self.db_service = db_service
        self.kg_service = kg_service
        self.workflow = workflow

    async def dispatch(self, msg: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Process inbound WhatsApp message for temperature & attendance domain.

        Args:
            msg: Inbound Meta WhatsApp message dictionary.
            context: Transport context (sender_phone, correlation_id, base_url, etc.).

        Returns:
            Dictionary containing reply_message and resolved kiosk_id.
        """
        sender_phone: str = str(context.get("sender_phone", "")).strip()
        correlation_id: str = str(context.get("correlation_id", f"wa-{uuid.uuid4().hex[:8]}"))
        base_url: str = str(context.get("base_url", f"http://localhost:{settings.ORCHESTRATOR_PORT}")).rstrip("/")

        # Extract text or caption
        text_content = ""
        is_image = "image" in msg
        if "text" in msg:
            text_content = str(msg["text"].get("body", "")).strip()
        elif is_image:
            text_content = str(msg["image"].get("caption", "")).strip()

        cmd_lower = text_content.lower()

        # Refresh roster
        self.kg_service.roster = self.kg_service._load_roster()

        # 1. Resolve User GPS Coordinates
        user_coords: Optional[Tuple[float, float]] = None
        if "location" in msg:
            loc = msg["location"]
            user_coords = (float(loc.get("latitude", 0.0)), float(loc.get("longitude", 0.0)))
            from core_platform.app.ingress.location_session import set_session_coordinates
            set_session_coordinates(sender_phone, user_coords, ttl_seconds=1800)
        else:
            from core_platform.app.ingress.location_session import get_session_coordinates
            user_coords = get_session_coordinates(sender_phone)

        # 2. Resolve Kiosk & Station
        explicit_kiosk: Optional[str] = None
        if any(cmd_lower.startswith(p) for p in ["checkin ", "check-in ", "duty ", "kiosk ", "station "]):
            tokens = text_content.split()
            for t in tokens[1:]:
                found = self.kg_service.find_kiosk(t)
                if found:
                    explicit_kiosk = found
                    break

        kiosk_id: Optional[str] = explicit_kiosk
        if not kiosk_id:
            kiosk_id = self.kg_service.resolve_kiosk_by_phone(sender_phone)

        emp = self.db_service.get_employee_by_phone(sender_phone)
        if not kiosk_id and emp and emp.assigned_kiosk_id:
            kiosk_id = emp.assigned_kiosk_id
            self.kg_service.assign_operator_to_kiosk(sender_phone, kiosk_id)

        if not user_coords and emp:
            att = self.db_service.has_attendance_today(emp.emp_code)
            if att is not None:
                assigned_kiosk = att.kiosk_id or kiosk_id or emp.assigned_kiosk_id
                kiosk_geo = self.kg_service.get_kiosk_coordinates(assigned_kiosk)
                if kiosk_geo:
                    user_coords = (kiosk_geo[0], kiosk_geo[1])

        if not kiosk_id and user_coords:
            nearest_res = self.kg_service.find_nearest_kiosk(user_coords)
            if nearest_res and nearest_res[1] <= 1500.0:
                kiosk_id = nearest_res[0]

        if not kiosk_id:
            kiosk_id = getattr(settings, "NODE_ID", getattr(settings, "KIOSK_ID", "NODE-01"))

        sender_role = emp.role if emp and emp.role else "OPERATOR"

        # 3. Explicit Geolocation Link Command (supports registered and unregistered users)
        if (cmd_lower in ["location", "loc", "gps", "link", "/location", "/loc"] or cmd_lower.startswith("loc ")) and not is_image:
            reply = self._handle_location_pin(sender_phone, user_coords, kiosk_id, base_url, correlation_id)
            return {"reply_message": reply, "kiosk_id": kiosk_id}

        # 4. Handle Registration / Enrollment Commands
        if cmd_lower.startswith("register") or cmd_lower.startswith("onboard"):
            reply = self._handle_registration_command(cmd_lower, text_content, sender_phone, sender_role, kiosk_id)
            return {"reply_message": reply, "kiosk_id": kiosk_id}

        # 5. Unregistered Sender Guard
        if emp is None:
            if "location" in msg:
                return {
                    "reply_message": (
                        f"👋 Welcome to KioskNode.\n\n"
                        f"Your phone number ({sender_phone}) is not registered with any KioskNode kiosk in the KioskNode Kiosk system.\n"
                        f"Please contact your supervisor to register you, or send 'register <NAME>' if authorized."
                    ),
                    "kiosk_id": kiosk_id,
                }
            return {
                "reply_message": (
                    f"👋 Welcome to KioskNode.\n\n"
                    f"Your phone number ({sender_phone}) is not registered in the KioskNode Kiosk system (not registered in the system).\n"
                    f"Please contact your supervisor to register you, or send 'register <NAME>' if authorized."
                ),
                "kiosk_id": kiosk_id,
            }

        # 6. Handle Operator Onboarding Lifecycle Gates
        if emp.status in ("PENDING_PHOTO", "PENDING_BIOMETRICS"):
            if is_image:
                raw_bytes = context.get("image_bytes")
                reply = await self._handle_onboarding_photo(emp, raw_bytes, correlation_id)
                return {"reply_message": reply, "kiosk_id": kiosk_id}
            else:
                kiosk_details = self.kg_service.get_kiosk_details(kiosk_id)
                station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else (emp.assigned_kiosk_id or "your station")
                return {
                    "reply_message": (
                        f"👋 Welcome to KioskNode, {emp.full_name}!\n\n"
                        f"Your account setup is pending. Please reply to this chat with a clear front-facing selfie photo to complete your enrollment for {station_name} ({emp.emp_code})."
                    ),
                    "kiosk_id": kiosk_id,
                }

        if emp.status == "PENDING_APPROVAL":
            return {
                "reply_message": (
                    f"⏳ Enrollment Under Review\n\n"
                    f"Hello {emp.full_name}, your onboarding portrait has been received and is currently awaiting Admin Approval.\n\n"
                    f"You will receive a WhatsApp confirmation once your account has been activated for shift duty."
                ),
                "kiosk_id": kiosk_id,
            }

        if emp.status in ("REJECTED", "SUSPENDED"):
            return {
                "reply_message": (
                    f"⛔ Account Inactive\n\n"
                    f"Hello {emp.full_name}, your KioskNode account is currently inactive or suspended.\n"
                    f"Please contact your supervisor or administrator for assistance."
                ),
                "kiosk_id": kiosk_id,
            }

        # 7. Intent Inference & Direct Routing
        session_mgr = ManagerTriageSessionManager.get_instance()
        has_active_triage = bool(session_mgr.get_active_message_id(sender_phone))
        has_quoted_reply = bool(msg.get("context", {}).get("id"))
        is_manager = any(r in sender_role.upper() for r in ["SUPERVISOR", "MANAGER", "ADMIN"])

        classification = classify_ingress_intent(
            text=text_content,
            is_image=is_image,
            sender_role=sender_role,
            has_quoted_reply=has_quoted_reply,
            has_active_triage=has_active_triage,
        )

        if is_manager and classification.intent == IngressIntent.OPERATOR_QUERY:
            classification.intent = IngressIntent.MANAGER_REPLY

        # 6a. Manager / Supervisor Triage Digest
        if classification.intent == IngressIntent.MANAGER_GREETING:
            if cmd_lower in ["fleet", "executive", "kiosks"]:
                digest = build_fleet_executive_digest(emp.full_name, self.db_service)
            else:
                digest = build_top10_digest(sender_phone, emp.full_name, self.db_service)
            return {"reply_message": digest, "kiosk_id": kiosk_id}

        # 6b. Manager Triage Navigation & Quoted Reply
        if classification.intent == IngressIntent.MANAGER_REPLY:
            if cmd_lower in ["next", "skip", "all", "list", "more"]:
                nav_res = handle_manager_navigation(sender_phone, emp.full_name, cmd_lower, self.db_service)
                return {"reply_message": nav_res, "kiosk_id": kiosk_id}

            quoted_wamid = msg.get("context", {}).get("id")
            mgr_confirm, op_phone, op_msg = handle_manager_reply(
                manager_phone=sender_phone,
                manager_name=emp.full_name,
                reply_text=text_content,
                quoted_wamid=quoted_wamid,
                db_service=self.db_service,
            )
            if op_phone and op_msg:
                await send_whatsapp_raw_message(to_phone=op_phone, text=op_msg)
            return {"reply_message": mgr_confirm, "kiosk_id": kiosk_id}

        # 6c. System Commands (Kiosk switcher, Location pin, etc.)
        if classification.intent == IngressIntent.SYSTEM_COMMAND:
            if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["kiosk", "kiosks", "station", "stations", "fleet"]):
                reply = self._handle_kiosk_station_command(cmd_lower, text_content, sender_phone, kiosk_id, base_url, correlation_id)
                return {"reply_message": reply, "kiosk_id": kiosk_id}

            if ("location" in msg or cmd_lower.startswith("loc")) and not is_image:
                reply = self._handle_location_pin(sender_phone, user_coords, kiosk_id, base_url, correlation_id)
                return {"reply_message": reply, "kiosk_id": kiosk_id}

            if cmd_lower in ["help", "menu", "status"]:
                reply = self._handle_operator_greeting(emp, kiosk_id, base_url, correlation_id)
                return {"reply_message": reply, "kiosk_id": kiosk_id}

        # 6d. Operator Friendly Greetings
        if classification.intent == IngressIntent.OPERATOR_GREETING:
            reply = self._handle_operator_greeting(emp, kiosk_id, base_url, correlation_id)
            return {"reply_message": reply, "kiosk_id": kiosk_id}

        # 6e. Operator Operational Inquiries & Procedural Q&A
        if classification.intent == IngressIntent.OPERATOR_QUERY:
            # Procedural question answering check
            if any(q in cmd_lower for q in ["temperature range", "what is", "how to", "why", "haccp", "procedure", "limit", "degrees", "range"]) or "?" in text_content:
                conv_reply = await generate_conversational_response(
                    sender_phone=sender_phone,
                    user_text=text_content,
                    emp=emp,
                    kiosk_id=kiosk_id,
                    kg_service=self.kg_service,
                    db_service=self.db_service,
                )
                return {"reply_message": conv_reply, "kiosk_id": kiosk_id}

            # Machine issue / supply request / operational note -> route to manager
            prio, cat = infer_message_priority_and_category(text_content)
            mgr_code = emp.reporting_manager_emp_code if emp else None
            mgr = self.db_service.get_employee_by_code(mgr_code) if mgr_code else None
            if not mgr:
                mgr = self.db_service.get_supervisor_for_kiosk(kiosk_id)

            mgr_phone = mgr.phone_number if mgr else "+919800099999"
            mgr_name = mgr.full_name if mgr else "Shift Supervisor"
            mgr_code_val = mgr.emp_code if mgr else "MGR-01"

            self.db_service.enqueue_internal_message(
                correlation_id=correlation_id,
                sender_phone=sender_phone,
                sender_emp_code=emp.emp_code,
                sender_name=emp.full_name,
                kiosk_id=kiosk_id,
                recipient_emp_code=mgr_code_val,
                recipient_phone=mgr_phone,
                message_text=text_content,
                priority=prio,
            )

            mgr_push_text = (
                f"🔔 *New Operator Message*\n"
                f"From: {emp.full_name} ({kiosk_id})\n"
                f"Priority: {prio} ({cat})\n"
                f'"{text_content}"\n\n'
                f"Reply with 'Hi' or directly reply to this message to respond."
            )
            await send_whatsapp_raw_message(to_phone=mgr_phone, text=mgr_push_text)

            return {
                "reply_message": f"📨 Message Dispatched to {mgr_name} ({mgr_code_val})\n\nPriority: {prio} ({cat.upper()})\nYour supervisor has been alerted and will reply shortly.",
                "kiosk_id": kiosk_id,
            }

        # 6f. Shift Check-in or Photo Attendance & Temperature Gauge Verification
        if classification.intent == IngressIntent.ATTENDANCE_CHECKIN or is_image:
            att = self.db_service.has_attendance_today(emp.emp_code)
            if att is not None and not is_image:
                checkin_time_ist = to_local_ist(att.checkin_time_utc)
                return {
                    "reply_message": (
                        f"✅ Shift Attendance Already Recorded!\n\n"
                        f"Hello {emp.full_name}, your attendance for today at {kiosk_id} is already logged.\n\n"
                        f"⏰ Check-in Time: {checkin_time_ist}\n\n"
                        f"To update chiller temperature readings throughout your shift, send a new photo of the temperature gauge display."
                    ),
                    "kiosk_id": kiosk_id,
                }

            raw_bytes = context.get("image_bytes")
            if not is_image or not raw_bytes:
                kiosk_details = self.kg_service.get_kiosk_details(kiosk_id)
                station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id
                from core_platform.app.ingress.location_session import bind_session_metadata
                bind_session_metadata(correlation_id, {"phone": sender_phone, "kiosk_id": kiosk_id})
                loc_url = f"{base_url}/loc?session={correlation_id}&kiosk_id={kiosk_id}"
                return {
                    "reply_message": (
                        f"📸 Shift Check-in Required for {station_name} ({kiosk_id}):\n\n"
                        f"1️⃣ Verify GPS Location:\n{loc_url}\n\n"
                        f"2️⃣ Submit Verification Photo:\nReply with a clear selfie showing your face and the chiller gauge."
                    ),
                    "kiosk_id": kiosk_id,
                }

            # Build state and execute state graph
            initial_state: TemperatureMarkerState = {
                "correlation_id": correlation_id,
                "sender_phone": sender_phone,
                "kiosk_id": kiosk_id,
                "raw_image_bytes": raw_bytes,
                "user_coords": user_coords,
            }
            final_state = await self.workflow.execute(initial_state)
            return {
                "reply_message": str(final_state.get("reply_message", "Attendance & temperature recorded.")),
                "kiosk_id": kiosk_id,
            }

        # Fallback to conversational agent
        reply = await generate_conversational_response(
            sender_phone=sender_phone,
            user_text=text_content,
            kiosk_id=kiosk_id,
            db_service=self.db_service,
            kg_service=self.kg_service,
            emp=emp,
            operation_id=correlation_id,
        )
        return {"reply_message": reply, "kiosk_id": kiosk_id}

    def _handle_operator_greeting(
        self,
        emp: Any,
        kiosk_id: str,
        base_url: str,
        correlation_id: str,
    ) -> str:
        """Compose self-service operator status dashboard greeting."""
        att = self.db_service.has_attendance_today(emp.emp_code)
        if att:
            checkin_str = f"✅ Marked at {to_local_ist(att.checkin_time_utc)}"
            if att.haccp_status == "PENDING_CHILLER_PHOTO" or att.chiller_temp_c == 0.0 or not att.chiller_temp_c:
                chiller_str = "⏳ Pending photo"
            else:
                chiller_str = f"{att.chiller_temp_c:.1f}°C ({'COMPLIANT' if att.haccp_compliant else 'NON-COMPLIANT'})"
        else:
            checkin_str = "❌ Not Marked"
            chiller_str = "N/A"

        # Check for instructions from supervisor directed to this employee
        instructions = self.db_service.get_pending_messages_for_recipient(emp.phone_number, limit=3)
        instr_lines = []
        for i in instructions:
            if i.sender_emp_code != emp.emp_code:  # Suppress own inquiries
                instr_lines.append(f"• From {i.sender_name}: {i.message_text}")

        instr_text = "\n".join(instr_lines) if instr_lines else "No new instructions from supervisor."

        return (
            f"👋 Hello {emp.full_name}!\n\n"
            f"📍 Active Station: {kiosk_id}\n\n"
            f"⏱️ Shift Attendance: {checkin_str}\n"
            f"❄️ Chiller Temperature: {chiller_str}\n\n"
            f"📋 Supervisor Instructions:\n"
            f"{instr_text}\n\n"
            f"👉 Send a photo of yourself and the chiller gauge to punch in or update temperature."
        )

    def _handle_registration_command(
        self,
        cmd_lower: str,
        text_content: str,
        sender_phone: str,
        sender_role: str,
        kiosk_id: str,
    ) -> str:
        """Process supervisor operator enrollment."""
        if sender_role.upper() not in ["SUPERVISOR", "MANAGER", "ADMIN"]:
            return (
                "❌ Self-Registration Disabled\n"
                "Operator self-registration via WhatsApp is not permitted.\n"
                "Please contact your Fleet Supervisor or HR administrator to provision your KioskNode account."
            )
        remainder = text_content.split(maxsplit=1)[1].strip() if " " in text_content.strip() else ""
        if not remainder:
            return (
                "📝 Supervisor Enrollment Format:\n"
                "register <EMP-CODE> <Full Name> <Phone>\n"
                "Example: register EMP-1050 Amit Patil +919800112233"
            )
        tokens = remainder.split()
        explicit_code = None
        phone_arg = None
        name_tokens: List[str] = []
        for t in tokens:
            if (t.startswith("EMP-") or (t.isdigit() and len(t) <= 6)) and explicit_code is None:
                explicit_code = t
            elif (t.startswith("+") or (t.isdigit() and len(t) >= 10)) and phone_arg is None:
                phone_arg = t
            else:
                name_tokens.append(t)
        full_name = " ".join(name_tokens) if name_tokens else "New Operator"
        target_phone = phone_arg or sender_phone
        emp_code = explicit_code or f"EMP-{uuid.uuid4().hex[:4].upper()}"

        self.db_service.register_employee(
            emp_code=emp_code,
            full_name=full_name,
            phone_number=target_phone,
            assigned_kiosk_id=kiosk_id,
            status="PENDING_PHOTO",
        )
        self.kg_service.assign_operator_to_kiosk(target_phone, kiosk_id)
        return (
            f"📝 Operator Enrolled by Supervisor:\n"
            f"Operator: {full_name} ({emp_code})\n"
            f"Assigned Station: {kiosk_id}\n"
            f"Phone: {target_phone}\n\n"
            "Status: PENDING_PHOTO. Operator has been enrolled and can now submit their selfie photo."
        )

    async def _handle_onboarding_photo(
        self,
        emp: Any,
        raw_bytes: Optional[bytes],
        correlation_id: str,
    ) -> str:
        """Process portrait submission for onboarding operators."""
        if not raw_bytes:
            return "❌ Could not process the photo. Please send a clear portrait photo directly from your camera."

        face_skill = get_platform_face_recognizer()
        ok, embedding, _ = await face_skill.compute_embedding(raw_bytes)
        if not ok or embedding is None:
            return (
                f"❌ Face Not Detected in Portrait\n\n"
                f"Hello {emp.full_name}, we could not clearly detect your face in the photo.\n\n"
                "Please submit a well-lit, front-facing selfie without sunglasses, masks, or extreme angles."
            )

        encrypted_emb = face_skill.encrypt_embedding(embedding)
        self.db_service.update_employee_photo(
            emp_code=emp.emp_code,
            photo_bytes=raw_bytes,
            embedding=encrypted_emb,
            status="PENDING_APPROVAL",
        )

        # Save profile photo to disk
        try:
            photo_dir = Path("logs/photos")
            photo_dir.mkdir(parents=True, exist_ok=True)
            photo_path = photo_dir / f"{emp.emp_code}_profile.jpg"
            photo_path.write_bytes(raw_bytes)
        except Exception as exc:
            logger.warning("[WhatsApp Ingress] Could not save photo to disk: %s", exc)

        return (
            f"📸 Onboarding Photo Received!\n\n"
            f"Thank you, {emp.full_name}! Your face biometric profile ({emp.emp_code}) has been created.\n\n"
            "Status: PENDING APPROVAL\n"
            "Your profile is awaiting manager confirmation before your first shift."
        )

    def _handle_kiosk_station_command(
        self,
        cmd_lower: str,
        text_content: str,
        sender_phone: str,
        kiosk_id: str,
        base_url: str,
        correlation_id: str,
    ) -> str:
        """Handle kiosk and station listing or switching."""
        all_k = self.kg_service.list_all_kiosks()
        tokens = text_content.split()
        if len(tokens) >= 2:
            arg = tokens[1]
            matched = self.kg_service.find_kiosk(arg)
            if matched:
                self.kg_service.assign_operator_to_kiosk(sender_phone, matched)
                k_details = self.kg_service.get_kiosk_details(matched)
                s_name = k_details.get("name", matched) if k_details else matched
                from core_platform.app.ingress.location_session import bind_session_metadata
                bind_session_metadata(correlation_id, {"phone": sender_phone, "kiosk_id": matched})
                loc_url = f"{base_url}/loc?session={correlation_id}&kiosk_id={matched}"
                return (
                    f"✅ Station Switched!\n"
                    f"Active Station: {s_name} ({matched})\n\n"
                    f"📍 Verify GPS Location (1-click):\n{loc_url}"
                )

        lines = [f"📍 KioskNode Fleet Stations (Your Active: {kiosk_id}):\n"]
        for k in all_k:
            mark = " ✅ (Active)" if k["kiosk_id"] == kiosk_id else ""
            lines.append(f"• {k['kiosk_id']}: {k['name']} ({k['city']}){mark}")
        lines.append(f"\nTo switch stations, reply: kiosk <KIOSK_ID> (e.g. 'kiosk NODE-PUNE-05')")
        return "\n".join(lines)

    def _handle_location_pin(
        self,
        sender_phone: str,
        user_coords: Optional[Tuple[float, float]],
        kiosk_id: str,
        base_url: str,
        correlation_id: str,
    ) -> str:
        """Handle native WhatsApp GPS location pin verification."""
        from core_platform.app.ingress.location_session import bind_session_metadata
        bind_session_metadata(correlation_id, {"phone": sender_phone, "kiosk_id": kiosk_id})
        kiosk_details = self.kg_service.get_kiosk_details(kiosk_id)
        station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id

        if user_coords:
            from core_platform.app.skills.geofencing import get_platform_geofencer
            kiosk_coords = self.kg_service.get_kiosk_coordinates(kiosk_id)
            if kiosk_coords:
                gf = get_platform_geofencer()
                in_bounds, dist_m = gf.verify_proximity(
                    user_lat=user_coords[0],
                    user_lon=user_coords[1],
                    target_lat=kiosk_coords[0],
                    target_lon=kiosk_coords[1],
                    radius_meters=self.kg_service.get_kiosk_geofence_radius(kiosk_id),
                )
                if in_bounds:
                    return (
                        f"📍 GPS Location Verified!\n"
                        f"Station: {station_name} ({kiosk_id})\n"
                        f"Distance: {int(dist_m)}m (Within safe perimeter).\n\n"
                        "Please now reply with your selfie photo and chiller gauge display to complete check-in."
                    )
                else:
                    return (
                        f"⚠️ GPS Location Outside Station Perimeter\n"
                        f"Station: {station_name} ({kiosk_id})\n"
                        f"Your Distance: {int(dist_m)}m (Allowed: {int(self.kg_service.get_kiosk_geofence_radius(kiosk_id))}m).\n\n"
                        "Please move closer to the kiosk and resend your photo or location."
                    )

        return (
            f"📍 Verify KioskNode location for {station_name} (1-click):\n"
            f"{base_url}/loc?session={correlation_id}&kiosk_id={kiosk_id}"
        )
