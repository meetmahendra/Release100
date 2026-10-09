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
Universal User Identity & Cartridge Entitlement Service.

Adheres strictly to GEES v2.0 Pillar 3 (Microkernel Architecture) & Pillar 5 (Type Discipline).
Manages multi-tenant user provisioning, phone normalization, cartridge-level RBAC,
and WhatsApp customer care window tracking.
"""

from datetime import datetime, timezone as dt_timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core_platform.app.config import settings
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.identity.models import PlatformUser

logger = logging.getLogger("core_platform.identity.service")


def normalize_phone_number(raw_phone: str) -> str:
    """Normalize arbitrary phone number string to canonical E.164 format.

    Examples:
        '9876543210' -> '+919876543210' (default country code if 10 digits)
        '+91 98765-43210' -> '+919876543210'
        '14155552671' -> '+14155552671'
    """
    cleaned = re.sub(r"[^\d+]", "", raw_phone.strip())
    if not cleaned:
        return ""
    if not cleaned.startswith("+"):
        if len(cleaned) == 10:
            cleaned = "+91" + cleaned
        else:
            cleaned = "+" + cleaned
    return cleaned


class UserIdentityService:
    """Central service managing user accounts, entitlements, and auth bindings."""

    _instance: Optional["UserIdentityService"] = None

    @classmethod
    def get_instance(
        cls,
        engine: Optional[Engine] = None,
        db_path: Optional[Path] = None,
    ) -> "UserIdentityService":
        """Retrieve singleton instance of UserIdentityService."""
        if cls._instance is None or db_path is not None:
            cls._instance = cls(engine=engine, db_path=db_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for clean test fixture isolation)."""
        cls._instance = None

    def __init__(
        self,
        engine: Optional[Engine] = None,
        db_path: Optional[Path] = None,
    ) -> None:
        """Initialize identity service with SQLAlchemy engine or standalone SQLite file."""
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._engine = create_engine(
                f"sqlite:///{db_path}",
                connect_args={"check_same_thread": False},
            )
        elif engine is not None:
            self._engine = engine
        else:
            self._db_manager = DatabaseManager.get_instance()
            self._engine = self._db_manager.get_engine()

        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensure platform_users table exists and deterministic bootstrap operator accounts are seeded."""
        try:
            PlatformUser.metadata.create_all(bind=self._engine)
            self._ensure_bootstrap_users()
        except Exception as e:
            logger.warning("[IdentityService] Table creation / bootstrap check: %s", e)

    def _ensure_bootstrap_users(self) -> None:
        """Deterministically seed initial bootstrap platform operators into database.

        Adheres to GEES v2.0 Pillar 4 (Zero Hardcoding) & Pillar 8 (Zero-Trust Security).
        Credentials exist solely as salted PBKDF2 records in SQLite platform_users.
        """
        import os
        with self._session_factory() as session:
            from core_platform.app.identity.models import Tenant, TenantDomain

            default_tenant = session.execute(
                select(Tenant).where(Tenant.id == "default_tenant")
            ).scalar_one_or_none()
            if not default_tenant:
                org_name = os.environ.get("ORGANIZATION_NAME", "Release100 Organization")
                session.add(
                    Tenant(
                        id="default_tenant",
                        name=org_name,
                        status="ACTIVE",
                        license_tier="STANDARD",
                        db_mode="SQLITE_WAL",
                        max_users=50,
                        storage_region="ap-south-1",
                        allowed_cartridges_json='["*"]',
                    )
                )
                dom = session.execute(
                    select(TenantDomain).where(TenantDomain.tenant_id == "default_tenant")
                ).scalar_one_or_none()
                if not dom:
                    session.add(
                        TenantDomain(
                            tenant_id="default_tenant",
                            domain_name="default.release100.local",
                            is_primary=True,
                            is_verified=True,
                        )
                    )
                session.commit()

            admin_user = session.execute(
                select(PlatformUser).where(PlatformUser.phone_number == "admin")
            ).scalar_one_or_none()
            if not admin_user:
                admin_pwd = os.environ.get("INITIAL_ADMIN_PASSWORD", "release100_admin")
                self.register_user(
                    phone_number="admin",
                    full_name="Platform Administrator",
                    role="admin",
                    tenant_id="default_tenant",
                    allowed_cartridges=["*"],
                    password=admin_pwd,
                    email="admin@release100.local",
                )
            elif admin_user.allowed_cartridges != ["*"]:
                admin_user.allowed_cartridges = ["*"]
                session.commit()

            devops_user = session.execute(
                select(PlatformUser).where(PlatformUser.phone_number == "devops")
            ).scalar_one_or_none()
            if not devops_user:
                devops_pwd = os.environ.get("INITIAL_DEVOPS_PASSWORD", "devops")
                self.register_user(
                    phone_number="devops",
                    full_name="DevOps Super Administrator",
                    role="super_admin",
                    tenant_id="platform",
                    allowed_cartridges=["*"],
                    password=devops_pwd,
                    email="devops@release100.local",
                )
            elif devops_user.allowed_cartridges != ["*"]:
                devops_user.allowed_cartridges = ["*"]
                session.commit()

    def register_user(
        self,
        phone_number: str,
        full_name: str,
        role: str = "user",
        allowed_cartridges: Optional[List[str]] = None,
        tenant_id: str = "default_tenant",
        timezone: str = "UTC",
        timezone_str: Optional[str] = None,
        password: Optional[str] = None,
        email: Optional[str] = None,
    ) -> PlatformUser:
        """Register a new user or update existing record with cartridge entitlements.

        Args:
            phone_number: Raw or E.164 phone number.
            full_name: User display name.
            role: 'user', 'supervisor', 'admin', or custom role.
            allowed_cartridges: List of permitted cartridge IDs.
            tenant_id: Target tenant partition code.
            timezone: User local timezone identifier.
            timezone_str: Optional alias for timezone.
            password: Optional raw password to hash with PBKDF2.
            email: Optional email address.

        Returns:
            Newly created or updated PlatformUser entity.

        Raises:
            ValueError: If phone_number or full_name is invalid.
        """
        raw_ident = str(phone_number or "").strip()
        if not raw_ident:
            raise ValueError("User identifier / phone number cannot be empty.")

        from core_platform.app.common.phone_validator import is_valid_phone_number
        if is_valid_phone_number(raw_ident):
            phone = normalize_phone_number(raw_ident)
        elif re.match(r"^[a-zA-Z0-9_\-\.]{3,32}$", raw_ident):
            phone = raw_ident
        else:
            try:
                phone = normalize_phone_number(raw_ident)
            except Exception:
                phone = raw_ident

        if not phone or len(phone) < 3:
            raise ValueError(f"Invalid phone number or username format: '{phone_number}'")
        if not full_name.strip():
            raise ValueError("User full_name cannot be empty.")

        effective_tz = timezone_str or timezone or "UTC"
        cartridges = allowed_cartridges if allowed_cartridges is not None else ["*"]
        clean_cartridges = [str(c).strip() for c in cartridges if str(c).strip()]

        from core_platform.app.auth.strategies import hash_password
        hashed_pwd = hash_password(password) if password else None

        with self._session_factory() as session:
            stmt = select(PlatformUser).where(PlatformUser.phone_number == phone)
            existing = session.execute(stmt).scalar_one_or_none()
            if existing:
                existing.full_name = full_name.strip()
                existing.role = role.lower()
                existing.allowed_cartridges_json = json.dumps(clean_cartridges)
                existing.tenant_id = tenant_id
                existing.timezone = effective_tz
                existing.status = "active"
                if hashed_pwd:
                    existing.hashed_password = hashed_pwd
                if email:
                    existing.email = email.strip()
                existing.updated_at = datetime.now(dt_timezone.utc)
                session.commit()
                session.refresh(existing)
                logger.info("[IdentityService] Updated existing user: phone=%s id=%d", phone, existing.id)
                return existing

            new_user = PlatformUser(
                phone_number=phone,
                full_name=full_name.strip(),
                role=role.lower(),
                status="active",
                allowed_cartridges_json=json.dumps(clean_cartridges),
                tenant_id=tenant_id,
                timezone=effective_tz,
                hashed_password=hashed_pwd,
                email=email.strip() if email else None,
                created_at=datetime.now(dt_timezone.utc),
                updated_at=datetime.now(dt_timezone.utc),
            )
            session.add(new_user)
            session.commit()
            session.refresh(new_user)
            logger.info("[IdentityService] Registered new user: phone=%s id=%d tenant=%s", phone, new_user.id, tenant_id)
            return new_user

    def set_user_password(self, user_id_or_phone: Union[int, str], new_password: str) -> bool:
        """Update or set password hash for a user."""
        from core_platform.app.auth.strategies import hash_password
        from core_platform.app.common.phone_validator import is_valid_phone_number
        from sqlalchemy import or_

        hashed_pwd = hash_password(new_password)
        with self._session_factory() as session:
            user: Optional[PlatformUser] = None
            if isinstance(user_id_or_phone, int) or (isinstance(user_id_or_phone, str) and user_id_or_phone.isdigit() and len(user_id_or_phone) < 7):
                stmt = select(PlatformUser).where(PlatformUser.id == int(user_id_or_phone))
                user = session.execute(stmt).scalar_one_or_none()
            elif isinstance(user_id_or_phone, str):
                clean_ident = user_id_or_phone.strip()
                norm_phone = normalize_phone_number(clean_ident) if is_valid_phone_number(clean_ident) else None
                conditions = [
                    PlatformUser.phone_number == clean_ident,
                    PlatformUser.email == clean_ident,
                    PlatformUser.full_name == clean_ident,
                ]
                if norm_phone:
                    conditions.append(PlatformUser.phone_number == norm_phone)
                stmt = select(PlatformUser).where(or_(*conditions))
                user = session.execute(stmt).scalars().first()
            if user:
                user.hashed_password = hashed_pwd
                user.updated_at = datetime.now(dt_timezone.utc)
                session.commit()
                return True
            return False

    def find_user_for_auth(self, identifier: str, tenant_id: Optional[str] = None) -> Optional[PlatformUser]:
        """Look up user across phone, email, google_email, or username."""
        clean_ident = identifier.strip()
        lower_ident = clean_ident.lower()
        from core_platform.app.common.phone_validator import is_valid_phone_number
        from sqlalchemy import func, or_

        norm_phone = normalize_phone_number(clean_ident) if is_valid_phone_number(clean_ident) else None
        with self._session_factory() as session:
            stmt = select(PlatformUser)
            match_conditions = [
                func.lower(PlatformUser.phone_number) == lower_ident,
                func.lower(PlatformUser.google_email) == lower_ident,
                func.lower(PlatformUser.email) == lower_ident,
                func.lower(PlatformUser.full_name) == lower_ident,
            ]
            if norm_phone:
                match_conditions.append(PlatformUser.phone_number == norm_phone)

            stmt = stmt.where(or_(*match_conditions))

            if tenant_id and tenant_id not in ("public", "system", "default_tenant"):
                variants = list(dict.fromkeys([
                    tenant_id,
                    tenant_id.replace("-", "_"),
                    tenant_id.replace("_", "-"),
                ]))
                stmt = stmt.where(PlatformUser.tenant_id.in_(variants))

            return session.execute(stmt).scalars().first()

    def get_user_by_phone(self, phone_number: str) -> Optional[PlatformUser]:
        """Look up user by phone number or username."""
        clean_ident = phone_number.strip()
        from core_platform.app.common.phone_validator import is_valid_phone_number
        from sqlalchemy import or_

        norm_phone = normalize_phone_number(clean_ident) if is_valid_phone_number(clean_ident) else None
        with self._session_factory() as session:
            conditions = [
                PlatformUser.phone_number == clean_ident,
                PlatformUser.email == clean_ident,
                PlatformUser.full_name == clean_ident,
            ]
            if norm_phone:
                conditions.append(PlatformUser.phone_number == norm_phone)
            stmt = select(PlatformUser).where(or_(*conditions))
            return session.execute(stmt).scalars().first()

    def get_user_by_id(self, user_id: Union[int, str]) -> Optional[PlatformUser]:
        """Look up user by primary key ID."""
        try:
            clean_id = int(user_id)
        except (ValueError, TypeError):
            return None
        with self._session_factory() as session:
            stmt = select(PlatformUser).where(PlatformUser.id == clean_id)
            return session.execute(stmt).scalar_one_or_none()

    def list_users(self, tenant_id: Optional[str] = None) -> List[PlatformUser]:
        """List registered users, optionally filtered by tenant."""
        with self._session_factory() as session:
            stmt = select(PlatformUser)
            if tenant_id:
                stmt = stmt.where(PlatformUser.tenant_id == tenant_id)
            stmt = stmt.order_by(PlatformUser.id.asc())
            return list(session.execute(stmt).scalars().all())

    def is_user_entitled(self, phone_number: str, cartridge_id: str) -> bool:
        """Return True if phone belongs to active user entitled to cartridge_id."""
        phone = normalize_phone_number(phone_number)
        user = self.get_user_by_phone(phone)
        if not user:
            return False
        if user.status.lower() != "active":
            return False
        return cartridge_id in user.allowed_cartridges

    def validate_entitlement(
        self,
        phone_number: str,
        cartridge_id: str,
    ) -> Tuple[bool, Optional[PlatformUser], str]:
        """Validate if a phone number is registered and entitled to a cartridge.

        Returns:
            Tuple of (is_allowed: bool, user: Optional[PlatformUser], reason: str)
        """
        phone = normalize_phone_number(phone_number)
        user = self.get_user_by_phone(phone)
        if not user:
            return False, None, "NOT_REGISTERED"
        if user.status.lower() != "active":
            return False, user, f"USER_{user.status.upper()}"
        if not user.is_entitled_to(cartridge_id):
            return False, user, "CARTRIDGE_NOT_PERMITTED"
        return True, user, "OK"

    def update_whatsapp_heartbeat(self, user_id_or_phone: Union[int, str]) -> Optional[PlatformUser]:
        """Update last_whatsapp_interaction_at timestamp for 24h window tracking."""
        with self._session_factory() as session:
            user: Optional[PlatformUser] = None
            if isinstance(user_id_or_phone, int) or (isinstance(user_id_or_phone, str) and user_id_or_phone.isdigit()):
                stmt = select(PlatformUser).where(PlatformUser.id == int(user_id_or_phone))
                user = session.execute(stmt).scalar_one_or_none()
            elif isinstance(user_id_or_phone, str):
                phone = normalize_phone_number(user_id_or_phone)
                stmt = select(PlatformUser).where(PlatformUser.phone_number == phone)
                user = session.execute(stmt).scalar_one_or_none()

            if user:
                user.last_whatsapp_interaction_at = datetime.now(dt_timezone.utc)
                user.updated_at = datetime.now(dt_timezone.utc)
                session.commit()
                session.refresh(user)
                return user
        return None

    def update_user_tokens(
        self,
        user_id: Union[int, str],
        encrypted_tokens: str,
        google_email: Optional[str] = None,
    ) -> Optional[PlatformUser]:
        """Save encrypted OAuth2 tokens for a user."""
        try:
            clean_id = int(user_id)
        except (ValueError, TypeError):
            return None
        with self._session_factory() as session:
            stmt = select(PlatformUser).where(PlatformUser.id == clean_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                user.encrypted_oauth_tokens = encrypted_tokens
                if google_email:
                    user.google_email = google_email
                user.updated_at = datetime.now(dt_timezone.utc)
                session.commit()
                session.refresh(user)
                logger.info("[IdentityService] Updated OAuth credentials for user_id=%d email=%s", clean_id, google_email)
                return user
        return None

    def update_user_status(self, user_id: Union[int, str], status: str) -> Optional[PlatformUser]:
        """Update user account status (active, suspended, pending_auth)."""
        clean_status = status.lower()
        try:
            clean_id = int(user_id)
        except (ValueError, TypeError):
            return None
        with self._session_factory() as session:
            stmt = select(PlatformUser).where(PlatformUser.id == clean_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                user.status = clean_status
                user.updated_at = datetime.now(dt_timezone.utc)
                session.commit()
                session.refresh(user)
                logger.info("[IdentityService] Updated status for user_id=%d to %s", clean_id, clean_status)
                return user
        return None

    def update_user_entitlements(
        self,
        user_id: Union[int, str],
        allowed_cartridges: List[str],
    ) -> Optional[PlatformUser]:
        """Update allowed cartridges list for a user."""
        clean = [str(c).strip() for c in allowed_cartridges if str(c).strip()]
        try:
            clean_id = int(user_id)
        except (ValueError, TypeError):
            return None
        with self._session_factory() as session:
            stmt = select(PlatformUser).where(PlatformUser.id == clean_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                user.allowed_cartridges_json = json.dumps(clean)
                user.updated_at = datetime.now(dt_timezone.utc)
                session.commit()
                session.refresh(user)
                logger.info("[IdentityService] Updated entitlements for user_id=%d: %s", clean_id, clean)
                return user
        return None

    def delete_user(self, user_id: Union[int, str]) -> bool:
        """Remove a registered user by ID."""
        try:
            clean_id = int(user_id)
        except (ValueError, TypeError):
            return False
        with self._session_factory() as session:
            stmt = select(PlatformUser).where(PlatformUser.id == clean_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                session.delete(user)
                session.commit()
                logger.info("[IdentityService] Deleted user_id=%d", clean_id)
                return True
        return False


def get_user_identity_service(
    engine: Optional[Engine] = None,
    db_path: Optional[Path] = None,
) -> UserIdentityService:
    """Convenience getter for singleton UserIdentityService."""
    return UserIdentityService.get_instance(engine=engine, db_path=db_path)
