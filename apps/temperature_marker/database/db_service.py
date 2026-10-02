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
Database Service Subsystem for Temperature & Attendance Marker.

Adheres strictly to Plan 03 v1.3. Handles employee management,
attendance records, and local offline outbox transactions.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid
from sqlalchemy import create_engine, or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.temperature_marker.database.models import (
    AttendanceRecord,
    Base,
    Employee,
    InternalMessageQueue,
    KioskMonitoringConfig,
    OutboxItem,
)


class DatabaseService:
    """Service managing local SQLite database storage and outbox queues."""

    _instance: Optional["DatabaseService"] = None

    @classmethod
    def get_instance(
        cls,
        db_url: Optional[str] = None,
        engine: Optional[Engine] = None,
    ) -> "DatabaseService":
        """Get or initialize singleton instance of DatabaseService."""
        if cls._instance is None:
            cls._instance = cls(db_url=db_url, engine=engine)
        return cls._instance

    def __init__(
        self,
        db_url: Optional[str] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        """Initialize DatabaseService and configure session factory.

        Args:
            db_url: Optional explicit connection string (isolated test mode only).
            engine: Optional pre-configured SQLAlchemy Engine instance (Core-Facilitated).
        """
        if engine is not None:
            self.engine = engine
            Base.metadata.create_all(bind=self.engine)
        elif db_url is not None:
            if db_url.startswith("sqlite:///"):
                db_path = db_url.replace("sqlite:///", "")
                if db_path != ":memory:":
                    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(db_url, echo=False)
            Base.metadata.create_all(bind=self.engine)
        else:
            from core_platform.app.db.manager import get_db_manager
            self.engine = get_db_manager().get_engine()
            Base.metadata.create_all(bind=self.engine)

        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        if DatabaseService._instance is None:
            DatabaseService._instance = self

    def bind_engine(self, engine: Engine) -> None:
        """Bind or reconfigure database engine."""
        self.engine = engine
        self.SessionLocal.configure(bind=engine)

    def close(self) -> None:
        """Cleanly release cartridge session handles without disposing shared platform engine."""
        pass

    def create_tables(self) -> None:
        """Create domain database tables (utility helper for test fixtures)."""
        Base.metadata.create_all(bind=self.engine)

    def register_employee(
        self,
        emp_code: str,
        full_name: str,
        phone_number: str,
        assigned_kiosk_id: str,
        encrypted_face_embedding: Optional[str] = None,
        status: str = "ACTIVE",
        role: str = "OPERATOR",
        reporting_manager_emp_code: Optional[str] = None,
    ) -> Employee:
        """Register or update an employee in the kiosk database.

        Args:
            emp_code: Unique employee code (e.g. 'EMP-1042').
            full_name: Operator name.
            phone_number: Normalized E.164 phone number.
            assigned_kiosk_id: Kiosk code (e.g. 'CANEBOT-PUNE-04').
            encrypted_face_embedding: AES-256-GCM encrypted base64 vector.
            status: 'ACTIVE' or 'PENDING_APPROVAL'.
            role: 'OPERATOR', 'SUPERVISOR', 'MANAGER', or 'TECHNICIAN'.
            reporting_manager_emp_code: Optional reporting supervisor employee code.

        Returns:
            The created Employee instance.
        """
        with self.SessionLocal() as session:
            existing = session.query(Employee).filter(
                or_(Employee.emp_code == emp_code, Employee.phone_number == phone_number)
            ).first()
            if existing:
                existing.emp_code = emp_code
                existing.full_name = full_name
                existing.phone_number = phone_number
                existing.assigned_kiosk_id = assigned_kiosk_id
                existing.status = status
                existing.role = role
                if reporting_manager_emp_code:
                    existing.reporting_manager_emp_code = reporting_manager_emp_code
                if encrypted_face_embedding:
                    existing.encrypted_face_embedding = encrypted_face_embedding
                session.commit()
                session.refresh(existing)
                return existing

            new_emp = Employee(
                emp_code=emp_code,
                full_name=full_name,
                phone_number=phone_number,
                assigned_kiosk_id=assigned_kiosk_id,
                encrypted_face_embedding=encrypted_face_embedding,
                status=status,
                role=role,
                reporting_manager_emp_code=reporting_manager_emp_code,
            )
            session.add(new_emp)
            session.commit()
            session.refresh(new_emp)
            return new_emp

    def update_employee_photo(
        self,
        emp_code: str,
        photo_bytes: Optional[bytes] = None,
        embedding: Optional[Union[str, Any]] = None,
        status: Optional[str] = "PENDING_APPROVAL",
    ) -> Optional[Employee]:
        """Update face photo embedding and onboarding status for an employee."""
        with self.SessionLocal() as session:
            emp = session.query(Employee).filter(Employee.emp_code == emp_code).first()
            if not emp:
                return None
            if embedding is not None:
                if isinstance(embedding, str):
                    emp.encrypted_face_embedding = embedding
                elif hasattr(embedding, "tobytes"):
                    from core_platform.app.skills.face_recognizer import get_platform_face_recognizer
                    emp.encrypted_face_embedding = get_platform_face_recognizer().encrypt_embedding(embedding)
            if status is not None:
                emp.status = status
            session.commit()
            session.refresh(emp)
            return emp

    def update_employee(
        self,
        emp_code: str,
        full_name: Optional[str] = None,
        phone_number: Optional[str] = None,
        assigned_kiosk_id: Optional[str] = None,
        reporting_manager_emp_code: Optional[str] = None,
        status: Optional[str] = None,
        role: Optional[str] = None,
    ) -> Optional[Employee]:
        """Update profile and assignment fields for an existing employee.

        Args:
            emp_code: Unique employee code.
            full_name: Updated full name.
            phone_number: Updated normalized phone number.
            assigned_kiosk_id: Updated assigned kiosk ID.
            reporting_manager_emp_code: Updated reporting supervisor code.
            status: Updated operational status (e.g. ACTIVE, PENDING_APPROVAL).
            role: Updated organizational role.

        Returns:
            Updated Employee instance, or None if not found.
        """
        with self.SessionLocal() as session:
            emp = session.query(Employee).filter(Employee.emp_code == emp_code).first()
            if not emp:
                return None
            if full_name is not None and full_name.strip():
                emp.full_name = full_name.strip()
            if phone_number is not None and phone_number.strip():
                emp.phone_number = phone_number.strip()
            if assigned_kiosk_id is not None and assigned_kiosk_id.strip():
                emp.assigned_kiosk_id = assigned_kiosk_id.strip()
            if reporting_manager_emp_code is not None:
                emp.reporting_manager_emp_code = reporting_manager_emp_code.strip() if reporting_manager_emp_code.strip() else None
            if status is not None and status.strip():
                emp.status = status.strip()
            if role is not None and role.strip():
                emp.role = role.strip()
            session.commit()
            session.refresh(emp)
            return emp

    def get_employee_by_phone(self, phone_number: str) -> Optional[Employee]:
        """Look up active employee by registered phone number.

        Tolerates '+' prefixes, spaces, and formatting variations.

        Args:
            phone_number: Normalized or raw E.164 phone string.

        Returns:
            Employee if found, else None.
        """
        raw = phone_number.strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        with self.SessionLocal() as session:
            # 1. Exact match
            emp = session.query(Employee).filter(Employee.phone_number == raw).first()
            if emp:
                return emp

            # 2. Alternate '+' prefix
            alt = raw[1:] if raw.startswith("+") else f"+{raw}"
            emp = session.query(Employee).filter(Employee.phone_number == alt).first()
            if emp:
                return emp

            # 3. Match last 10 digits
            if len(digits) >= 10:
                last10 = digits[-10:]
                all_emps = session.query(Employee).all()
                for e in all_emps:
                    e_digits = "".join(ch for ch in e.phone_number if ch.isdigit())
                    if e_digits.endswith(last10):
                        return e
            return None

    def get_employee_by_code(self, emp_code: str) -> Optional[Employee]:
        """Look up employee by unique employee code.

        Args:
            emp_code: Employee code.

        Returns:
            Employee if found, else None.
        """
        with self.SessionLocal() as session:
            return session.query(Employee).filter(Employee.emp_code == emp_code).first()

    def get_all_employees(self) -> List[Employee]:
        """Retrieve all registered employees across all kiosks.

        Returns:
            List of all Employee records.
        """
        with self.SessionLocal() as session:
            return session.query(Employee).order_by(Employee.id.asc()).all()

    def get_supervisor_for_kiosk(self, kiosk_id: str) -> Optional[Employee]:
        """Fetch active supervisor assigned to a specific kiosk or fallback supervisor.

        Args:
            kiosk_id: Kiosk identifier.

        Returns:
            Supervisor Employee instance if found, else None.
        """
        with self.SessionLocal() as session:
            sup = (
                session.query(Employee)
                .filter(
                    Employee.assigned_kiosk_id == kiosk_id,
                    Employee.role == "SUPERVISOR",
                    Employee.status == "ACTIVE",
                )
                .first()
            )
            if sup:
                return sup

            return (
                session.query(Employee)
                .filter(
                    Employee.role.in_(["SUPERVISOR", "MANAGER"]),
                    Employee.status == "ACTIVE",
                )
                .first()
            )

    def assign_employee_to_kiosk(self, emp_code: str, new_kiosk_id: str) -> bool:
        """Reassign an employee to a different kiosk.

        Args:
            emp_code: Unique employee code.
            new_kiosk_id: Target kiosk identifier.

        Returns:
            True if updated, False if employee not found.
        """
        with self.SessionLocal() as session:
            emp = session.query(Employee).filter(Employee.emp_code == emp_code).first()
            if emp:
                emp.assigned_kiosk_id = new_kiosk_id
                session.commit()
                return True
            return False

    def create_or_update_operator(
        self,
        emp_code: str,
        full_name: str,
        phone_number: str,
        assigned_kiosk_id: str,
        status: str = "ACTIVE",
    ) -> Employee:
        """Create or update an operator profile from the administrative console."""
        return self.register_employee(
            emp_code=emp_code,
            full_name=full_name,
            phone_number=phone_number,
            assigned_kiosk_id=assigned_kiosk_id,
            status=status,
        )


    def get_pending_approvals(self) -> List[Employee]:
        """Retrieve all employees waiting for admin onboarding approval.

        Returns:
            List of pending Employee records.
        """
        with self.SessionLocal() as session:
            return (
                session.query(Employee)
                .filter(Employee.status.in_(["PENDING_APPROVAL", "PENDING_PHOTO"]))
                .order_by(Employee.id.desc())
                .all()
            )

    def approve_employee(self, emp_code: str) -> bool:
        """Approve a pending operator for duty.

        Args:
            emp_code: Unique employee code.

        Returns:
            True if updated, False if employee not found.
        """
        with self.SessionLocal() as session:
            emp = session.query(Employee).filter(Employee.emp_code == emp_code).first()
            if emp:
                emp.status = "ACTIVE"
                session.commit()
                return True
            return False

    def reject_employee(self, emp_code: str) -> bool:
        """Reject a pending operator registration.

        Args:
            emp_code: Unique employee code.

        Returns:
            True if updated, False if employee not found.
        """
        with self.SessionLocal() as session:
            emp = session.query(Employee).filter(Employee.emp_code == emp_code).first()
            if emp:
                emp.status = "REJECTED"
                session.commit()
                return True
            return False

    def clear_employee_face_embedding(self, emp_code: str) -> bool:
        """Clear biometric face embedding for an operator to allow re-enrollment.

        Resets employee status to 'PENDING_PHOTO' and clears stored vector.

        Args:
            emp_code: Unique employee code.

        Returns:
            True if updated, False if employee not found.
        """
        with self.SessionLocal() as session:
            emp = session.query(Employee).filter(Employee.emp_code == emp_code).first()
            if emp:
                emp.encrypted_face_embedding = None
                emp.status = "PENDING_PHOTO"
                session.commit()
                return True
            return False

    def record_attendance(
        self,
        correlation_id: str,
        emp_code: str,
        kiosk_id: str,
        face_confidence: float,
        gps_distance_meters: float,
        geofence_verified: bool,
        chiller_temp_c: float,
        haccp_compliant: bool,
        haccp_status: str,
        ocr_engine_used: str = "local_onnx",
        is_duty_checkin: bool = True,
        photo_path: Optional[str] = None,
    ) -> AttendanceRecord:
        """Persist a verified attendance and temperature check-in record.

        Args:
            correlation_id: End-to-end trace ID.
            emp_code: Operator code.
            kiosk_id: Machine ID.
            face_confidence: Biometric match confidence.
            gps_distance_meters: Haversine distance from kiosk.
            geofence_verified: True if within radius.
            chiller_temp_c: Verified chiller temperature.
            haccp_compliant: True if within 2°C - 4°C.
            haccp_status: 'SAFE_RANGE' or 'CRITICAL_HAZARD'.
            ocr_engine_used: 'local_onnx' or 'cloud_gemini_vision'.
            is_duty_checkin: True for first shift checkin, False for periodic chiller checks.
            photo_path: Path to captured check-in JPEG.

        Returns:
            Saved AttendanceRecord instance.
        """
        with self.SessionLocal() as session:
            record = AttendanceRecord(
                correlation_id=correlation_id,
                emp_code=emp_code,
                kiosk_id=kiosk_id,
                face_confidence=face_confidence,
                gps_distance_meters=gps_distance_meters,
                geofence_verified=geofence_verified,
                chiller_temp_c=chiller_temp_c,
                haccp_compliant=haccp_compliant,
                haccp_status=haccp_status,
                ocr_engine_used=ocr_engine_used,
                is_duty_checkin=is_duty_checkin,
                photo_path=photo_path,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def has_attendance_today(self, emp_code: str) -> Optional[AttendanceRecord]:
        """Check if an active duty check-in has already been recorded for this operator today.

        Args:
            emp_code: Operator employee code.

        Returns:
            AttendanceRecord if exists today, else None.
        """
        now = datetime.now(timezone.utc)
        start_of_today = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)

        with self.SessionLocal() as session:
            return (
                session.query(AttendanceRecord)
                .filter(
                    AttendanceRecord.emp_code == emp_code,
                    AttendanceRecord.is_duty_checkin == True,  # noqa: E712
                    AttendanceRecord.checkin_time_utc >= start_of_today,
                )
                .order_by(AttendanceRecord.id.desc())
                .first()
            )

    def generate_next_emp_code(self, prefix: str = "EMP") -> str:
        """Generate next available sequential employee identifier.

        Args:
            prefix: Code prefix (default 'EMP').

        Returns:
            Unique employee code (e.g. 'EMP-1043').
        """
        with self.SessionLocal() as session:
            all_codes = [
                e.emp_code for e in session.query(Employee.emp_code).all()
                if e[0].startswith(f"{prefix}-")
            ]
            max_num = 1000
            for code in all_codes:
                try:
                    num_part = int(code.split("-")[1])
                    if num_part > max_num:
                        max_num = num_part
                except (IndexError, ValueError):
                    pass
            return f"{prefix}-{max_num + 1}"

    def resolve_attendance_record(
        self,
        record_id: int,
        resolution_status: str,
        notes: str,
    ) -> bool:
        """Manually approve or override an anomalous attendance record.

        Args:
            record_id: Record database primary key.
            resolution_status: e.g. 'APPROVED_OVERRIDE', 'DISPUTED', 'RESOLVED'.
            notes: Administrator explanation note.

        Returns:
            True if updated, False if not found.
        """
        with self.SessionLocal() as session:
            rec = session.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
            if rec:
                rec.manual_resolution_status = resolution_status
                rec.manual_resolution_notes = notes
                session.commit()
                return True
            return False

    def get_recent_attendance(self, limit: int = 20) -> List[AttendanceRecord]:
        """Fetch recent attendance records.

        Args:
            limit: Maximum records to return.

        Returns:
            List of recent AttendanceRecord instances.
        """
        with self.SessionLocal() as session:
            return (
                session.query(AttendanceRecord)
                .order_by(AttendanceRecord.id.desc())
                .limit(limit)
                .all()
            )

    def enqueue_outbox(
        self,
        correlation_id: str,
        target_gateway: str,
        payload: Dict[str, Any],
    ) -> OutboxItem:
        """Enqueue payload for downstream synchronization.

        Ensures zero data loss during network dropouts at factory kiosks.

        Args:
            correlation_id: Distributed trace ID.
            target_gateway: Connector identifier ('in_house_rest', 'direct_db', etc.).
            payload: Structured dictionary data.

        Returns:
            Created OutboxItem.
        """
        with self.SessionLocal() as session:
            item = OutboxItem(
                correlation_id=correlation_id,
                target_gateway=target_gateway,
                payload_json=json.dumps(payload),
                status="PENDING",
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            return item

    def get_pending_outbox_items(self, limit: int = 50) -> List[OutboxItem]:
        """Retrieve batch of pending outbox items awaiting synchronization.

        Args:
            limit: Maximum records to fetch.

        Returns:
            List of pending OutboxItems.
        """
        with self.SessionLocal() as session:
            return (
                session.query(OutboxItem)
                .filter(OutboxItem.status == "PENDING")
                .order_by(OutboxItem.id.asc())
                .limit(limit)
                .all()
            )

    def mark_outbox_synced(self, item_id: int) -> None:
        """Mark an outbox item as successfully synced upstream.

        Args:
            item_id: OutboxItem database ID.
        """
        with self.SessionLocal() as session:
            item = session.query(OutboxItem).filter(OutboxItem.id == item_id).first()
            if item:
                item.status = "SYNCED"
                item.synced_at_utc = datetime.now(timezone.utc)
                session.commit()

    def mark_outbox_failed(self, item_id: int, max_attempts: int = 5) -> None:
        """Record a dispatch failure on an outbox item, marking FAILED if attempts exceed threshold.

        Args:
            item_id: OutboxItem database ID.
            max_attempts: Maximum retry threshold before permanent failure.
        """
        with self.SessionLocal() as session:
            item = session.query(OutboxItem).filter(OutboxItem.id == item_id).first()
            if item:
                item.attempts += 1
                if item.attempts >= max_attempts:
                    item.status = "FAILED"
                session.commit()

    # --- Internal Operator-to-Manager Message Queue Methods ---

    def enqueue_internal_message(
        self,
        correlation_id: Optional[str] = None,
        sender_phone: str = "",
        sender_emp_code: str = "OPERATOR",
        sender_name: str = "Operator",
        kiosk_id: str = "KIOSK",
        recipient_emp_code: str = "SUPERVISOR",
        recipient_phone: str = "",
        message_text: str = "",
        media_path: Optional[str] = None,
        priority: int = 50,
        **kwargs: Any,
    ) -> InternalMessageQueue:
        """Enqueue an operational note or alert for a supervisor/manager.

        Supports both positional and keyword invocations.
        """
        cid = correlation_id or kwargs.get("correlation_id") or f"msg-{uuid.uuid4().hex[:8]}"
        s_phone = sender_phone or kwargs.get("sender_phone", "")
        s_emp = sender_emp_code or kwargs.get("sender_emp_code", "OPERATOR")
        s_name = sender_name or kwargs.get("sender_name", "Operator")
        k_id = kiosk_id or kwargs.get("kiosk_id", "KIOSK")
        r_emp = recipient_emp_code or kwargs.get("recipient_emp_code", "SUPERVISOR")
        r_phone = recipient_phone or kwargs.get("recipient_phone", "")
        m_text = message_text or kwargs.get("message_text", "")
        m_path = media_path or kwargs.get("media_path")
        prio = kwargs.get("priority", priority)

        with self.SessionLocal() as session:
            msg = InternalMessageQueue(
                correlation_id=cid,
                sender_phone=s_phone,
                sender_emp_code=s_emp,
                sender_name=s_name,
                kiosk_id=k_id,
                recipient_emp_code=r_emp,
                recipient_phone=r_phone,
                message_text=m_text,
                media_path=m_path,
                priority=prio,
                status="QUEUED",
                created_at_utc=datetime.now(timezone.utc),
            )
            session.add(msg)
            session.commit()
            session.refresh(msg)
            return msg

    def get_pending_messages_for_recipient(
        self,
        recipient_phone: str,
        limit: int = 10,
    ) -> List[InternalMessageQueue]:
        """Retrieve prioritized pending messages awaiting review by recipient.

        Sorted strictly by Priority (Descending, Critical first) then CreatedAt (Ascending, Oldest first).

        Args:
            recipient_phone: Manager phone number.
            limit: Maximum items to return (default 10 for single-screen digest).

        Returns:
            List of pending InternalMessageQueue items.
        """
        clean_phone = recipient_phone.replace("+", "").replace(" ", "").strip()
        with self.SessionLocal() as session:
            return (
                session.query(InternalMessageQueue)
                .filter(
                    or_(
                        InternalMessageQueue.recipient_phone == recipient_phone,
                        InternalMessageQueue.recipient_phone == f"+{clean_phone}",
                        InternalMessageQueue.recipient_phone == clean_phone,
                    ),
                    InternalMessageQueue.status == "QUEUED",
                )
                .order_by(
                    InternalMessageQueue.priority.desc(),
                    InternalMessageQueue.created_at_utc.asc(),
                )
                .limit(limit)
                .all()
            )

    def count_pending_messages_for_recipient(self, recipient_phone: str) -> int:
        """Count total unresolved messages for recipient."""
        clean_phone = recipient_phone.replace("+", "").replace(" ", "").strip()
        with self.SessionLocal() as session:
            return (
                session.query(InternalMessageQueue)
                .filter(
                    or_(
                        InternalMessageQueue.recipient_phone == recipient_phone,
                        InternalMessageQueue.recipient_phone == f"+{clean_phone}",
                        InternalMessageQueue.recipient_phone == clean_phone,
                    ),
                    InternalMessageQueue.status == "QUEUED",
                )
                .count()
            )

    def bind_outbound_wamid(self, message_id: int, wamid: str) -> None:
        """Bind outbound WhatsApp message ID (wamid) to queue item for swipe-to-reply matching."""
        with self.SessionLocal() as session:
            msg = session.query(InternalMessageQueue).filter(InternalMessageQueue.id == message_id).first()
            if msg:
                msg.wamid_outbound = wamid
                msg.status = "DELIVERED"
                msg.delivered_at_utc = datetime.now(timezone.utc)
                session.commit()

    def get_message_by_wamid(self, wamid: str) -> Optional[InternalMessageQueue]:
        """Retrieve queue item by outbound WhatsApp message ID (for quoted replies)."""
        with self.SessionLocal() as session:
            return session.query(InternalMessageQueue).filter(InternalMessageQueue.wamid_outbound == wamid).first()

    def get_message_by_id(self, message_id: int) -> Optional[InternalMessageQueue]:
        """Retrieve an internal message queue item by primary key.

        Used by the generic internal_dispatch module to avoid importing the
        InternalMessageQueue ORM model at module level (decoupling).

        Args:
            message_id: Primary key of the InternalMessageQueue row.

        Returns:
            InternalMessageQueue instance or None if not found.
        """
        with self.SessionLocal() as session:
            return session.query(InternalMessageQueue).filter(InternalMessageQueue.id == message_id).first()

    def resolve_internal_message(
        self,
        message_id: int,
        reply_context: str,
        resolved_by_phone: str,
    ) -> Optional[InternalMessageQueue]:
        """Mark message as RESOLVED with manager reply context."""
        with self.SessionLocal() as session:
            msg = session.query(InternalMessageQueue).filter(InternalMessageQueue.id == message_id).first()
            if msg:
                msg.status = "RESOLVED"
                msg.reply_context = reply_context
                msg.resolved_by_phone = resolved_by_phone
                msg.resolved_at_utc = datetime.now(timezone.utc)
                session.commit()
                session.refresh(msg)
                return msg
            return None

    def get_recent_messages_for_operator(
        self,
        operator_phone: str,
        limit: int = 5,
    ) -> List[InternalMessageQueue]:
        """Retrieve recent internal messages or manager replies for an operator."""
        clean_phone = operator_phone.replace("+", "").replace(" ", "").strip()
        with self.SessionLocal() as session:
            return (
                session.query(InternalMessageQueue)
                .filter(
                    or_(
                        InternalMessageQueue.sender_phone == operator_phone,
                        InternalMessageQueue.sender_phone == f"+{clean_phone}",
                        InternalMessageQueue.sender_phone == clean_phone,
                        InternalMessageQueue.recipient_phone == operator_phone,
                        InternalMessageQueue.recipient_phone == f"+{clean_phone}",
                        InternalMessageQueue.recipient_phone == clean_phone,
                    )
                )
                .order_by(InternalMessageQueue.id.desc())
                .limit(limit)
                .all()
            )

    def get_recent_internal_messages(
        self,
        limit: int = 50,
        status_filter: Optional[str] = None,
    ) -> List[InternalMessageQueue]:
        """Retrieve recent internal communications across all kiosks.

        Args:
            limit: Maximum items to return.
            status_filter: Optional status ('QUEUED', 'RESOLVED', etc.).

        Returns:
            List of InternalMessageQueue records ordered newest first.
        """
        with self.SessionLocal() as session:
            q = session.query(InternalMessageQueue)
            if status_filter:
                q = q.filter(InternalMessageQueue.status == status_filter.upper())
            return q.order_by(InternalMessageQueue.id.desc()).limit(limit).all()

    def get_kiosk_config(self, kiosk_id: str) -> KioskMonitoringConfig:
        """Retrieve monitoring configuration for a kiosk or global default.

        Args:
            kiosk_id: Kiosk identifier.

        Returns:
            KioskMonitoringConfig instance.
        """
        with self.SessionLocal() as session:
            cfg = (
                session.query(KioskMonitoringConfig)
                .filter(KioskMonitoringConfig.kiosk_id == kiosk_id)
                .first()
            )
            if not cfg:
                # Check global default
                cfg = (
                    session.query(KioskMonitoringConfig)
                    .filter(KioskMonitoringConfig.kiosk_id == "GLOBAL_DEFAULT")
                    .first()
                )
            if not cfg:
                # Return default unpersisted object
                return KioskMonitoringConfig(
                    kiosk_id=kiosk_id,
                    required_daily_temp_checks=3,
                    check_interval_hours=4.0,
                    min_safe_temp=2.0,
                    max_safe_temp=4.0,
                    critical_alert_temp=7.0,
                    alert_manager_on_hazard=True,
                )
            return cfg

    def upsert_kiosk_config(
        self,
        kiosk_id: str,
        required_daily_temp_checks: int = 3,
        check_interval_hours: float = 4.0,
        min_safe_temp: float = 2.0,
        max_safe_temp: float = 4.0,
        critical_alert_temp: float = 7.0,
        alert_manager_on_hazard: bool = True,
    ) -> KioskMonitoringConfig:
        """Create or update monitoring settings for a kiosk.

        Args:
            kiosk_id: Kiosk code or 'GLOBAL_DEFAULT'.
            required_daily_temp_checks: Daily checks target (default 3).
            check_interval_hours: Re-check frequency in hours (default 4.0).
            min_safe_temp: Lower HACCP bound (default 2.0°C).
            max_safe_temp: Upper HACCP bound (default 4.0°C).
            critical_alert_temp: Critical spoilage limit (default 7.0°C).
            alert_manager_on_hazard: Whether to alert supervisor via WhatsApp.

        Returns:
            Updated KioskMonitoringConfig.
        """
        with self.SessionLocal() as session:
            cfg = (
                session.query(KioskMonitoringConfig)
                .filter(KioskMonitoringConfig.kiosk_id == kiosk_id)
                .first()
            )
            if not cfg:
                cfg = KioskMonitoringConfig(
                    kiosk_id=kiosk_id,
                    required_daily_temp_checks=required_daily_temp_checks,
                    check_interval_hours=check_interval_hours,
                    min_safe_temp=min_safe_temp,
                    max_safe_temp=max_safe_temp,
                    critical_alert_temp=critical_alert_temp,
                    alert_manager_on_hazard=alert_manager_on_hazard,
                )
                session.add(cfg)
            else:
                cfg.required_daily_temp_checks = required_daily_temp_checks
                cfg.check_interval_hours = check_interval_hours
                cfg.min_safe_temp = min_safe_temp
                cfg.max_safe_temp = max_safe_temp
                cfg.critical_alert_temp = critical_alert_temp
                cfg.alert_manager_on_hazard = alert_manager_on_hazard
                cfg.updated_at_utc = datetime.now(timezone.utc)

            session.commit()
            session.refresh(cfg)
            return cfg

    def get_all_kiosk_configs(self) -> Dict[str, KioskMonitoringConfig]:
        """Return map of all stored kiosk configurations."""
        with self.SessionLocal() as session:
            all_cfgs = session.query(KioskMonitoringConfig).all()
            return {c.kiosk_id: c for c in all_cfgs}

    def get_kiosk_daily_attendance_summary(self) -> List[Dict[str, Any]]:
        """Compute real-time operational summary matrix for all registered kiosks.

        Integrates KnowledgeGraphService roster, today's attendance records,
        temperature check progress against required daily target, and overdue alerts.

        Returns:
            List of kiosk summary dictionaries.
        """
        from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
        from core_platform.app.common.timezone import to_local_ist

        kg = KnowledgeGraphService()
        all_kiosks = kg.list_all_kiosks()
        configs = self.get_all_kiosk_configs()
        global_cfg = configs.get("GLOBAL_DEFAULT")

        now = datetime.now(timezone.utc)
        start_of_today = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)

        summaries: List[Dict[str, Any]] = []

        with self.SessionLocal() as session:
            for k in all_kiosks:
                k_id = k["kiosk_id"]
                site_name = k.get("name", k_id)
                city = k.get("city", "")

                # Configured requirements
                cfg = configs.get(k_id) or global_cfg
                required_checks = cfg.required_daily_temp_checks if cfg else 3
                interval_hours = cfg.check_interval_hours if cfg else 4.0

                # Assigned operators for this kiosk
                assigned_emps = (
                    session.query(Employee)
                    .filter(Employee.assigned_kiosk_id == k_id, Employee.status == "ACTIVE")
                    .all()
                )
                op_names = [e.full_name for e in assigned_emps]

                # Attendance records today for this kiosk
                records_today = (
                    session.query(AttendanceRecord)
                    .filter(
                        AttendanceRecord.kiosk_id == k_id,
                        AttendanceRecord.checkin_time_utc >= start_of_today,
                    )
                    .order_by(AttendanceRecord.id.asc())
                    .all()
                )

                # 1. Duty Check-in Status
                duty_rec = next((r for r in records_today if r.is_duty_checkin), None)
                has_checkin = duty_rec is not None
                checkin_time_str = to_local_ist(duty_rec.checkin_time_utc) if duty_rec else None
                checkin_emp_code = duty_rec.emp_code if duty_rec else None
                checkin_op_name = None
                if duty_rec:
                    matched_op = next((e for e in assigned_emps if e.emp_code == duty_rec.emp_code), None)
                    checkin_op_name = matched_op.full_name if matched_op else duty_rec.emp_code

                # 2. Temperature capture tracking
                temp_records = [
                    r for r in records_today
                    if r.chiller_temp_c is not None
                    and r.chiller_temp_c > 0.0
                    and r.haccp_status not in ("PENDING_CHILLER_PHOTO", "READING_UNAVAILABLE")
                ]
                total_temp_checks = len(temp_records)
                progress_pct = min(100, int((total_temp_checks / max(1, required_checks)) * 100))

                latest_temp_rec = temp_records[-1] if temp_records else None
                latest_temp_val = latest_temp_rec.chiller_temp_c if latest_temp_rec else None
                latest_haccp_status = latest_temp_rec.haccp_status if latest_temp_rec else "PENDING_PHOTO"
                latest_temp_time_str = to_local_ist(latest_temp_rec.checkin_time_utc) if latest_temp_rec else None

                # 3. Overdue & Hazard evaluation
                is_temp_overdue = False
                if has_checkin and total_temp_checks < required_checks:
                    if total_temp_checks == 0:
                        # Attendance marked but no temperature captured yet
                        is_temp_overdue = True
                    elif latest_temp_rec:
                        # Check elapsed time since last capture
                        rec_time = latest_temp_rec.checkin_time_utc
                        if rec_time.tzinfo is None:
                            rec_time = rec_time.replace(tzinfo=timezone.utc)
                        elapsed_hrs = (now - rec_time).total_seconds() / 3600.0
                        if elapsed_hrs > interval_hours:
                            is_temp_overdue = True

                has_critical_hazard = any(
                    r.haccp_status in ("CRITICAL_HAZARD", "FREEZING_HAZARD")
                    or r.face_confidence < 0.82
                    or not r.geofence_verified
                    for r in records_today
                )

                summaries.append({
                    "kiosk_id": k_id,
                    "name": site_name,
                    "city": city,
                    "assigned_operators": op_names,
                    "has_checkin_today": has_checkin,
                    "checkin_operator_name": checkin_op_name,
                    "checkin_operator_emp_code": checkin_emp_code,
                    "checkin_time_ist": checkin_time_str,
                    "gps_distance_meters": duty_rec.gps_distance_meters if duty_rec else None,
                    "total_temp_checks_today": total_temp_checks,
                    "required_temp_checks": required_checks,
                    "temp_checks_progress_pct": progress_pct,
                    "latest_chiller_temp_c": latest_temp_val,
                    "latest_haccp_status": latest_haccp_status,
                    "latest_temp_time_ist": latest_temp_time_str,
                    "is_temp_overdue": is_temp_overdue,
                    "has_critical_hazard": has_critical_hazard,
                })

        return summaries

    def get_active_high_alerts(self) -> List[Dict[str, Any]]:
        """Retrieve unresolved critical safety and compliance alerts from today.

        Returns:
            List of alert event dictionaries.
        """
        from core_platform.app.common.timezone import to_local_ist

        now = datetime.now(timezone.utc)
        start_of_today = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
        alerts: List[Dict[str, Any]] = []

        with self.SessionLocal() as session:
            # 1. Critical HACCP hazards or tamper from AttendanceRecord
            crit_recs = (
                session.query(AttendanceRecord)
                .filter(
                    AttendanceRecord.checkin_time_utc >= start_of_today,
                    or_(
                        AttendanceRecord.haccp_status.in_(["CRITICAL_HAZARD", "FREEZING_HAZARD"]),
                        AttendanceRecord.face_confidence < 0.82,
                        AttendanceRecord.geofence_verified == False,  # noqa: E712
                    ),
                    AttendanceRecord.manual_resolution_status == None,  # noqa: E711
                )
                .order_by(AttendanceRecord.id.desc())
                .all()
            )

            for r in crit_recs:
                alert_type = "HACCP Hazard"
                desc = f"Chiller temp {r.chiller_temp_c:.1f}°C ({r.haccp_status})"
                if r.face_confidence < 0.82:
                    alert_type = "Biometric Mismatch"
                    desc = f"Face similarity {r.face_confidence:.2f} < 0.82"
                elif not r.geofence_verified:
                    alert_type = "Geofence Violation"
                    desc = f"Location distance {r.gps_distance_meters:.0f}m exceeds radius"

                alerts.append({
                    "id": r.id,
                    "type": alert_type,
                    "kiosk_id": r.kiosk_id,
                    "emp_code": r.emp_code,
                    "description": desc,
                    "time_ist": to_local_ist(r.checkin_time_utc),
                    "priority": 100,
                })

            # 2. Critical unresolved operator messages
            crit_msgs = (
                session.query(InternalMessageQueue)
                .filter(
                    InternalMessageQueue.created_at_utc >= start_of_today,
                    InternalMessageQueue.priority >= 100,
                    InternalMessageQueue.status != "RESOLVED",
                )
                .order_by(InternalMessageQueue.id.desc())
                .all()
            )

            for m in crit_msgs:
                alerts.append({
                    "id": m.id,
                    "type": "Urgent Message",
                    "kiosk_id": m.kiosk_id,
                    "emp_code": m.sender_emp_code,
                    "description": m.message_text[:80],
                    "time_ist": to_local_ist(m.created_at_utc),
                    "priority": m.priority,
                })

        return alerts

    def acknowledge_alert(self, record_id: int, ack_notes: str = "Acknowledged by manager") -> bool:
        """Mark a critical compliance record as acknowledged by manager."""
        with self.SessionLocal() as session:
            rec = session.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
            if rec:
                rec.manual_resolution_status = "ACKNOWLEDGED"
                rec.manual_resolution_notes = ack_notes
                session.commit()
                return True
            return False

    def resolve_internal_message_web(
        self,
        message_id: int,
        reply_text: str,
        resolver_phone: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Resolve an internal message from web UI and prepare outbound reply.

        Args:
            message_id: Internal message ID.
            reply_text: Supervisor response text.
            resolver_phone: Supervisor phone number.

        Returns:
            Tuple of (success, operator_phone, outbound_reply_body).
        """
        updated = self.resolve_internal_message(message_id, reply_text, resolver_phone)
        if updated:
            outbound_msg = (
                f"💬 Supervisor Reply (Ref: MSG-{updated.id}):\n"
                f"Re: \"{updated.message_text[:50]}...\"\n\n"
                f"{reply_text}\n\n"
                f"Status: RESOLVED ✅"
            )
            return True, updated.sender_phone, outbound_msg
        return False, None, None


