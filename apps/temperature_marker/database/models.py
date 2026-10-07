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
SQLAlchemy ORM Data Models for Temperature & Attendance Marker.

Adheres strictly to Plan 03 v1.3 and GEES v1.0.
Provides models for:
1. Employee (biometric credentials, kiosk assignments, onboarding approvals).
2. AttendanceRecord (attendance, GPS verification, chiller reading).
3. OutboxItem (offline edge queue for downstream sync resilience).
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy models."""
    pass


class Employee(Base):
    """Registered kiosk operator or field technician."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    emp_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    assigned_kiosk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, PENDING_APPROVAL, REJECTED
    role: Mapped[str] = mapped_column(String(32), default="OPERATOR", nullable=False)  # OPERATOR, SUPERVISOR, MANAGER, TECHNICIAN
    reporting_manager_emp_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    encrypted_face_embedding: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Base64 AES-256-GCM encrypted
    created_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)


class AttendanceRecord(Base):
    """Duty check-in and chiller verification record."""

    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    emp_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kiosk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    checkin_time_utc: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Biometric & Location Verification
    face_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    gps_distance_meters: Mapped[float] = mapped_column(Float, nullable=False)
    geofence_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Chiller Temperature & Safety
    chiller_temp_c: Mapped[float] = mapped_column(Float, nullable=False)
    haccp_compliant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    haccp_status: Mapped[str] = mapped_column(String(32), nullable=False)  # SAFE_RANGE, CRITICAL_HAZARD
    ocr_engine_used: Mapped[str] = mapped_column(String(64), default="local_onnx")

    # Session & Operational Classification
    is_duty_checkin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    photo_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Manual Admin Resolution (GEES v1.0 Layer 2 Gate)
    manual_resolution_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    manual_resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)


class OutboxItem(Base):
    """Local SQLite outbox queue for edge resilience during internet drops."""

    __tablename__ = "outbox_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_gateway: Mapped[str] = mapped_column(String(64), nullable=False)  # in_house_rest, direct_db, google_sheets, erp_mcp
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)  # PENDING, SYNCED, FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)
    synced_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class InternalMessageQueue(Base):
    """Operator operational messages, supervisor alerts, and two-way reply tracking."""

    __tablename__ = "internal_message_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sender_phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sender_emp_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kiosk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    recipient_emp_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    recipient_phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    media_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)  # 100=Critical, 75=Urgent, 50=Standard, 25=Query
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", nullable=False)  # QUEUED, DELIVERED, RESOLVED

    # Two-way reply tracking
    wamid_outbound: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)  # WhatsApp msg ID sent to manager
    reply_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Context of reply from manager
    resolved_by_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    delivered_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class KioskMonitoringConfig(Base):
    """Configurable multi-check schedule and HACCP thresholds per kiosk."""

    __tablename__ = "kiosk_monitoring_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    kiosk_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    required_daily_temp_checks: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    check_interval_hours: Mapped[float] = mapped_column(Float, default=4.0, nullable=False)
    min_safe_temp: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    max_safe_temp: Mapped[float] = mapped_column(Float, default=4.0, nullable=False)
    critical_alert_temp: Mapped[float] = mapped_column(Float, default=7.0, nullable=False)
    alert_manager_on_hazard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

