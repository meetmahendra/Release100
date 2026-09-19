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
    emp_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    assigned_kiosk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, PENDING_APPROVAL, REJECTED
    encrypted_face_embedding: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Base64 AES-256-GCM encrypted
    created_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)


class AttendanceRecord(Base):
    """Duty check-in and chiller verification record."""

    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_gateway: Mapped[str] = mapped_column(String(64), nullable=False)  # in_house_rest, direct_db, google_sheets, erp_mcp
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)  # PENDING, SYNCED, FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)
    synced_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
