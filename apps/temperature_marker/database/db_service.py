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
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import Session, sessionmaker

from apps.temperature_marker.database.models import (
    AttendanceRecord,
    Base,
    Employee,
    OutboxItem,
)


class DatabaseService:
    """Service managing local SQLite database storage and outbox queues."""

    _instance: Optional["DatabaseService"] = None

    @classmethod
    def get_instance(cls, db_url: str = "sqlite:///logs/temperature_marker.db") -> "DatabaseService":
        """Get or initialize singleton instance of DatabaseService."""
        if cls._instance is None:
            cls._instance = cls(db_url=db_url)
        return cls._instance

    def __init__(self, db_url: str = "sqlite:///logs/temperature_marker.db") -> None:
        """Initialize DatabaseService and bind SQLAlchemy engine.

        Args:
            db_url: SQLAlchemy connection string.
        """
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(db_url, echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.create_tables()

    def close(self) -> None:
        """Dispose SQLAlchemy connection pool and release file handles on Windows."""
        self.engine.dispose()

    def create_tables(self) -> None:
        """Create all database tables if they do not already exist."""
        Base.metadata.create_all(bind=self.engine)

    def register_employee(
        self,
        emp_code: str,
        full_name: str,
        phone_number: str,
        assigned_kiosk_id: str,
        encrypted_face_embedding: Optional[str] = None,
        status: str = "ACTIVE",
    ) -> Employee:
        """Register or update an employee in the kiosk database.

        Args:
            emp_code: Unique employee code (e.g. 'EMP-1042').
            full_name: Operator name.
            phone_number: Normalized E.164 phone number.
            assigned_kiosk_id: Kiosk code (e.g. 'CANEBOT-PUNE-04').
            encrypted_face_embedding: AES-256-GCM encrypted base64 vector.
            status: 'ACTIVE' or 'PENDING_APPROVAL'.

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
            )
            session.add(new_emp)
            session.commit()
            session.refresh(new_emp)
            return new_emp

    def get_employee_by_phone(self, phone_number: str) -> Optional[Employee]:
        """Look up active employee by registered phone number.

        Args:
            phone_number: Normalized E.164 phone string.

        Returns:
            Employee if found, else None.
        """
        with self.SessionLocal() as session:
            return session.query(Employee).filter(Employee.phone_number == phone_number).first()

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
                .filter(Employee.status == "PENDING_APPROVAL")
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
                .order_by(AttendanceRecord.id.asc())
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
