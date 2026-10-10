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
Universal Multi-Tenant Platform User Entity & Identity Models.

Adheres strictly to GEES v2.0 Microkernel Architecture (Rule 3) and Type Discipline (Rule 5).
Provides declarative SQLAlchemy 2.0 model for user identity, cartridge entitlements,
Google OAuth vault bindings, and WhatsApp customer service window heartbeats.
"""

from datetime import datetime, timezone
import json
import os
import secrets
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core_platform.app.db.base import Base, TimestampMixin


class PlatformUser(Base, TimestampMixin):
    """Central registered user and tenant operator entity."""

    __tablename__ = "platform_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True, nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="OPERATOR", nullable=False)  # OPERATOR, MANAGER, ADMIN
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True, nullable=False)  # ACTIVE, SUSPENDED, PENDING_AUTH

    # Cartridge entitlements stored as canonical JSON array string: '["mail_organizer", "temperature_marker"]'
    allowed_cartridges_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # Google OAuth2 credentials binding (AES-256-GCM encrypted payload)
    google_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    encrypted_oauth_tokens: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Cryptographic per-user salt for envelope encryption key derivation
    user_secret_salt: Mapped[str] = mapped_column(
        String(64),
        default=lambda: secrets.token_hex(16),
        nullable=False,
    )

    # WhatsApp 24-Hour Customer Care window timestamp
    last_whatsapp_interaction_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Timezone identifier (e.g., 'Asia/Kolkata', 'America/New_York', 'UTC')
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)

    @property
    def allowed_cartridges(self) -> List[str]:
        """Return parsed list of cartridge IDs enabled for this user."""
        try:
            parsed = json.loads(self.allowed_cartridges_json or "[]")
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            return []
        except Exception:
            return []

    @allowed_cartridges.setter
    def allowed_cartridges(self, cartridges: List[str]) -> None:
        """Serialize list of cartridge IDs into JSON format."""
        clean = [str(c).strip() for c in cartridges if str(c).strip()]
        self.allowed_cartridges_json = json.dumps(clean)

    def is_entitled_to(self, cartridge_id: str) -> bool:
        """Check if user has explicit access permission for a given cartridge."""
        if self.status != "ACTIVE":
            return False
        return cartridge_id in self.allowed_cartridges

    def is_within_whatsapp_24h_window(self) -> bool:
        """Check if user interacted with WhatsApp within the last 24 hours."""
        if not self.last_whatsapp_interaction_at:
            return False
        now_utc = datetime.now(timezone.utc)
        last_dt = self.last_whatsapp_interaction_at
        if isinstance(last_dt, str):
            try:
                last_dt = datetime.fromisoformat(last_dt)
            except Exception:
                return False
        if isinstance(last_dt, datetime):
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            return (now_utc - last_dt).total_seconds() <= 24 * 3600
        return False

    def is_within_24h_window(self) -> bool:
        """Alias for is_within_whatsapp_24h_window."""
        return self.is_within_whatsapp_24h_window()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize user object to safe dictionary."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "phone_number": self.phone_number,
            "full_name": self.full_name,
            "role": self.role,
            "status": self.status,
            "allowed_cartridges": self.allowed_cartridges,
            "google_email": self.google_email,
            "email": self.email,
            "has_password": bool(self.hashed_password),
            "has_google_auth": bool(self.encrypted_oauth_tokens),
            "last_whatsapp_interaction_at": (
                self.last_whatsapp_interaction_at.isoformat()
                if self.last_whatsapp_interaction_at
                else None
            ),
            "is_within_24h_window": self.is_within_whatsapp_24h_window(),
            "timezone": self.timezone,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Tenant(Base, TimestampMixin):
    """Central tenant organization entity."""

    __tablename__ = "platform_tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Slug (e.g. "acme_logistics", "public")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True, nullable=False)  # ACTIVE, SUSPENDED, ARCHIVED, MIGRATING
    license_tier: Mapped[str] = mapped_column(String(32), default="STARTER", nullable=False)  # STARTER, PROFESSIONAL, ENTERPRISE
    db_mode: Mapped[str] = mapped_column(String(32), default="SQLITE_WAL", nullable=False)  # SQLITE_WAL, POSTGRES_SCHEMA, DEDICATED_DB
    db_connection_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_users: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    storage_region: Mapped[str] = mapped_column(String(64), default="ap-south-1", nullable=False)
    allowed_cartridges_json: Mapped[str] = mapped_column(
        Text,
        default='["*"]',
        nullable=False,
    )
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    @property
    def allowed_cartridges(self) -> List[str]:
        """Return parsed list of cartridge IDs enabled for this tenant."""
        try:
            parsed = json.loads(self.allowed_cartridges_json or "[]")
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            return ["*"]
        except Exception:
            return ["*"]

    @allowed_cartridges.setter
    def allowed_cartridges(self, cartridges: List[str]) -> None:
        """Serialize list of cartridge IDs into JSON format."""
        clean = [str(c).strip() for c in cartridges if str(c).strip()]
        self.allowed_cartridges_json = json.dumps(clean)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize tenant object to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "license_tier": self.license_tier,
            "db_mode": self.db_mode,
            "has_dedicated_db": bool(self.db_connection_url),
            "max_users": self.max_users,
            "storage_region": self.storage_region,
            "allowed_cartridges": self.allowed_cartridges,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TenantDomain(Base, TimestampMixin):
    """Domain and custom CNAME routing entity for a tenant."""

    __tablename__ = "platform_tenant_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    domain_name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)  # e.g. "acme.release100.com", "mail.acme.com"
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize domain mapping to dictionary."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "domain_name": self.domain_name,
            "is_primary": self.is_primary,
            "is_verified": self.is_verified,
        }


class TenantConfig(Base, TimestampMixin):
    """Tenant-specific credential configuration & BYOK settings."""

    __tablename__ = "platform_tenant_configs"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credential_mode: Mapped[str] = mapped_column(String(32), default="PLATFORM_MANAGED", nullable=False)  # PLATFORM_MANAGED, CUSTOMER_BYOK
    llm_provider: Mapped[str] = mapped_column(String(32), default="gemini", nullable=False)  # gemini, openai
    encrypted_gemini_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    encrypted_openai_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    encrypted_waba_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    waba_phone_number_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    default_timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    brand_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    def to_dict(self, mask_secrets: bool = True) -> Dict[str, Any]:
        """Serialize config dictionary with optional secret masking."""
        return {
            "tenant_id": self.tenant_id,
            "credential_mode": self.credential_mode,
            "llm_provider": self.llm_provider or "gemini",
            "has_gemini_byok": bool(self.encrypted_gemini_api_key),
            "has_openai_byok": bool(self.encrypted_openai_api_key),
            "has_waba_byok": bool(self.encrypted_waba_token),
            "waba_phone_number_id": self.waba_phone_number_id,
            "default_timezone": self.default_timezone,
            "brand_name": self.brand_name,
        }


class TenantAuditLog(Base):
    """Tamper-evident audit log with SHA-256 cryptographic hash chaining for tenant operations."""

    __tablename__ = "platform_tenant_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # PROVISION, ARCHIVE, CLONE, TRANSFER, UPDATE_CONFIG
    performed_by: Mapped[str] = mapped_column(String(255), default="devops_admin", nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
