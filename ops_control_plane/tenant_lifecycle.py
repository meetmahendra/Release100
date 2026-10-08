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
DevOps Tenant Lifecycle Engine (`tenant_lifecycle.py`).

Adheres strictly to GEES v2.0 Microkernel Architecture & Non-Repudiation (Rule 7).
Implements DevOps-exclusive operations:
1. Provision New Tenant (Atomic Schema + DB + Root Admin).
2. Decommission & Archive Tenant (SHA-256 Audit Bundle Export).
3. Deep-Clone Tenant (Full configuration + database schema + historical data snapshot).
4. Geo-Specific & Intra-Region Tenant Transfer (Physical database streaming + DNS cutover).
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple, Union
from sqlalchemy import MetaData, Table, create_engine, desc, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core_platform.app.common.phone_validator import normalize_phone_number
from core_platform.app.db.tenant_provisioner import get_tenant_schema_provisioner
from core_platform.app.db.base import Base
from core_platform.app.identity.models import (
    PlatformUser,
    Tenant,
    TenantAuditLog,
    TenantConfig,
    TenantDomain,
)
from core_platform.app.identity.service import get_user_identity_service
from core_platform.app.middleware.tenant_context import register_domain_mapping

logger = logging.getLogger("ops_control_plane.tenant_lifecycle")


GENESIS_HASH: str = "0" * 64


def compute_audit_hash(
    prev_hash: str,
    timestamp: Union[datetime, str],
    action: str,
    payload_str: str,
) -> str:
    """Compute deterministic SHA-256 hash for an audit record payload."""
    if isinstance(timestamp, datetime):
        ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(timestamp, str):
        try:
            dt = datetime.fromisoformat(timestamp)
            ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_str = timestamp
    else:
        ts_str = str(timestamp)

    raw_to_hash = f"{prev_hash}:{ts_str}:{action}:{payload_str}"
    return hashlib.sha256(raw_to_hash.encode("utf-8")).hexdigest()


class TenantLifecycleManager:
    """DevOps-exclusive engine for tenant lifecycle and data migration operations."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        """Initialize with underlying platform registry engine."""
        if db_url:
            self.engine = create_engine(db_url, echo=False)
        else:
            from core_platform.app.db.manager import get_db_manager
            self.engine = get_db_manager().get_engine()

        Base.metadata.create_all(bind=self.engine)
        from core_platform.app.db.migrations import DatabaseMigrationHelper
        DatabaseMigrationHelper.auto_migrate_columns(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.provisioner = get_tenant_schema_provisioner()

    def _log_audit_event(
        self,
        session: Session,
        tenant_id: str,
        action: str,
        performed_by: str,
        payload: Dict[str, Any],
    ) -> TenantAuditLog:
        """Append a tamper-evident audit record with SHA-256 hash chaining."""
        stmt = select(TenantAuditLog).where(
            TenantAuditLog.tenant_id == tenant_id
        ).order_by(desc(TenantAuditLog.id)).limit(1)
        last_log = session.scalar(stmt)
        prev_hash = last_log.record_hash if last_log else GENESIS_HASH

        now_utc = datetime.now(timezone.utc)
        payload_str = json.dumps(payload, sort_keys=True)
        record_hash = compute_audit_hash(
            prev_hash=prev_hash,
            timestamp=now_utc,
            action=action,
            payload_str=payload_str,
        )

        audit_entry = TenantAuditLog(
            tenant_id=tenant_id,
            action=action,
            performed_by=performed_by,
            prev_hash=prev_hash,
            record_hash=record_hash,
            payload_json=payload_str,
            timestamp=now_utc,
        )
        session.add(audit_entry)
        session.commit()
        return audit_entry

    def provision_tenant(
        self,
        slug: str,
        name: str,
        admin_phone: Optional[str] = None,
        admin_name: Optional[str] = None,
        license_tier: str = "STARTER",
        db_mode: str = "SQLITE_WAL",
        db_url: Optional[str] = None,
        max_users: int = 10,
        storage_region: str = "ap-south-1",
        custom_domain: Optional[str] = None,
        allowed_cartridges: Optional[List[str]] = None,
        admin_password: Optional[str] = None,
        admin_email: Optional[str] = None,
        performed_by: str = "devops_admin",
    ) -> Dict[str, Any]:
        """Atomically provision a new tenant, its isolated database, and root admin user."""
        clean_slug = slug.lower().strip().replace(" ", "_").replace("-", "_")
        cartridges = allowed_cartridges if allowed_cartridges is not None else ["*"]
        effective_pwd = admin_password.strip() if admin_password and admin_password.strip() else f"{clean_slug.capitalize()}@2026"

        with self.session_factory() as session:
            # 1. Check existing tenant
            existing = session.scalar(select(Tenant).where(Tenant.id == clean_slug))
            if existing:
                raise ValueError(f"Tenant workspace with slug '{clean_slug}' already exists.")

            # 2. Check domain uniqueness
            dns_slug = clean_slug.replace("_", "-")
            subdomain = f"{dns_slug}.release100.com"
            alt_subdomain = f"{clean_slug}.release100.com" if dns_slug != clean_slug else None

            existing_sub = session.scalar(select(TenantDomain).where(TenantDomain.domain_name.in_([subdomain, alt_subdomain] if alt_subdomain else [subdomain])))
            if existing_sub:
                raise ValueError(f"Subdomain '{subdomain}' is already assigned to tenant '{existing_sub.tenant_id}'.")

            c_dom = custom_domain.strip().lower() if custom_domain and custom_domain.strip() else None
            if c_dom:
                existing_dom = session.scalar(select(TenantDomain).where(TenantDomain.domain_name == c_dom))
                if existing_dom:
                    raise ValueError(
                        f"Custom vanity domain '{c_dom}' is already registered to tenant '{existing_dom.tenant_id}'. "
                        "Please specify a unique domain or leave the field blank."
                    )

            # 3. Provision isolated physical database & tables
            prov_res = self.provisioner.provision_tenant(
                tenant_id=clean_slug,
                db_dialect=db_mode.lower(),
                db_url_override=db_url,
                cartridges=cartridges,
            )

            # 4. Create Tenant Record
            tenant = Tenant(
                id=clean_slug,
                name=name.strip(),
                status="ACTIVE",
                license_tier=license_tier.upper().strip(),
                db_mode=db_mode.upper().strip(),
                db_connection_url=db_url,
                max_users=max_users,
                storage_region=storage_region.strip(),
                allowed_cartridges_json=json.dumps(cartridges),
            )
            session.add(tenant)

            # 5. Register Default and Custom Domains
            dom1 = TenantDomain(
                tenant_id=clean_slug,
                domain_name=subdomain,
                is_primary=True,
                is_verified=True,
            )
            session.add(dom1)
            register_domain_mapping(subdomain, clean_slug)

            if alt_subdomain:
                dom_alt = TenantDomain(
                    tenant_id=clean_slug,
                    domain_name=alt_subdomain,
                    is_primary=False,
                    is_verified=True,
                )
                session.add(dom_alt)
                register_domain_mapping(alt_subdomain, clean_slug)

            if c_dom:
                dom2 = TenantDomain(
                    tenant_id=clean_slug,
                    domain_name=c_dom,
                    is_primary=False,
                    is_verified=True,
                )
                session.add(dom2)
                register_domain_mapping(c_dom, clean_slug)

            # 6. Initialize Default Tenant Config (Platform-Managed)
            config = TenantConfig(
                tenant_id=clean_slug,
                credential_mode="PLATFORM_MANAGED",
                brand_name=name.strip(),
                default_timezone="Asia/Kolkata",
            )
            session.add(config)
            session.commit()

            # 6. Seed Root Tenant Admin User with PBKDF2 Password
            user_service = get_user_identity_service(self.engine)
            effective_admin_user = (admin_phone.strip() if admin_phone and admin_phone.strip() else f"admin_{clean_slug}")
            effective_admin_name = (admin_name.strip() if admin_name and admin_name.strip() else f"{name.strip()} Admin")
            effective_admin_email = (admin_email.strip() if admin_email and admin_email.strip() else f"admin@{clean_slug}.release100.com")

            admin_user = user_service.register_user(
                phone_number=effective_admin_user,
                full_name=effective_admin_name,
                tenant_id=clean_slug,
                role="admin",
                allowed_cartridges=cartridges,
                password=effective_pwd,
                email=effective_admin_email,
            )

            # 7. Audit Log
            audit_entry = self._log_audit_event(
                session=session,
                tenant_id=clean_slug,
                action="PROVISION",
                performed_by=performed_by,
                payload={
                    "slug": clean_slug,
                    "name": name,
                    "admin_phone": admin_user.phone_number,
                    "db_mode": db_mode,
                    "storage_region": storage_region,
                    "cartridges": cartridges,
                    "tables_created": prov_res.get("tables_created", []),
                },
            )

            logger.info("[TenantLifecycle] Successfully provisioned tenant: %s (Admin: %s)", clean_slug, admin_user.phone_number)
            return {
                "status": "PROVISIONED",
                "tenant_id": clean_slug,
                "name": name,
                "admin_phone": admin_user.phone_number,
                "admin_username": admin_user.phone_number,
                "admin_name": admin_user.full_name,
                "admin_password": effective_pwd,
                "allowed_cartridges": cartridges,
                "db_url": prov_res.get("db_url"),
                "audit_record_hash": audit_entry.record_hash,
                "tenant": tenant.to_dict(),
                "admin_user": admin_user.to_dict(),
                "provisioning": prov_res,
                "audit_record": {
                    "id": audit_entry.id,
                    "action": audit_entry.action,
                    "record_hash": audit_entry.record_hash,
                    "prev_hash": audit_entry.prev_hash,
                    "timestamp": audit_entry.timestamp.isoformat(),
                },
            }

    def update_tenant_cartridges(
        self,
        tenant_id: str,
        cartridges: List[str],
        performed_by: str = "devops_admin",
    ) -> Dict[str, Any]:
        """Update enabled application cartridges for a tenant workspace."""
        clean_cartridges = [str(c).strip() for c in cartridges if str(c).strip()]
        with self.session_factory() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id))
            if not tenant:
                raise ValueError(f"Tenant '{tenant_id}' not found.")
            tenant.allowed_cartridges = clean_cartridges
            session.commit()

            # Also update root admin user cartridges if any
            user_service = get_user_identity_service(self.engine)
            users = user_service.list_users(tenant_id=tenant_id)
            for u in users:
                if u.role.lower() == "admin":
                    u.allowed_cartridges = clean_cartridges
            session.commit()

            audit_entry = self._log_audit_event(
                session=session,
                tenant_id=tenant_id,
                action="UPDATE_CARTRIDGES",
                performed_by=performed_by,
                payload={"tenant_id": tenant_id, "cartridges": clean_cartridges},
            )
            return {
                "status": "UPDATED",
                "tenant_id": tenant_id,
                "allowed_cartridges": clean_cartridges,
                "audit_record_hash": audit_entry.record_hash,
            }

    def archive_tenant(
        self,
        slug: str,
        performed_by: str = "devops_admin",
    ) -> Dict[str, Any]:
        """Decommission and archive a tenant with cryptographic audit export."""
        clean_slug = slug.lower().strip()
        with self.session_factory() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.id == clean_slug))
            if not tenant:
                raise ValueError(f"Tenant '{clean_slug}' not found.")

            tenant.status = "ARCHIVED"

            # Fetch all audit history for export
            audit_stmt = select(TenantAuditLog).where(
                TenantAuditLog.tenant_id == clean_slug
            ).order_by(TenantAuditLog.id)
            audit_rows = list(session.scalars(audit_stmt).all())
            audit_export = [
                {
                    "id": a.id,
                    "action": a.action,
                    "performed_by": a.performed_by,
                    "record_hash": a.record_hash,
                    "prev_hash": a.prev_hash,
                    "timestamp": a.timestamp.isoformat(),
                    "payload": json.loads(a.payload_json or "{}"),
                }
                for a in audit_rows
            ]

            # Log archive action
            self._log_audit_event(
                session=session,
                tenant_id=clean_slug,
                action="ARCHIVE",
                performed_by=performed_by,
                payload={"status": "ARCHIVED", "total_audit_records": len(audit_rows)},
            )

            session.commit()
            logger.info("[TenantLifecycle] Archived tenant: %s", clean_slug)
            return {
                "tenant_id": clean_slug,
                "status": "ARCHIVED",
                "audit_records_count": len(audit_export),
                "audit_trail_bundle": audit_export,
            }

    def deep_clone_tenant(
        self,
        source_slug: str,
        target_slug: str,
        target_name: Optional[str] = None,
        performed_by: str = "devops_admin",
    ) -> Dict[str, Any]:
        """Deep-clone an entire tenant: configuration, database schema, and all data snapshots."""
        src_slug = source_slug.lower().strip()
        tgt_slug = target_slug.lower().strip()

        with self.session_factory() as session:
            src_tenant = session.scalar(select(Tenant).where(Tenant.id == src_slug))
            if not src_tenant:
                raise ValueError(f"Source tenant '{src_slug}' not found.")

            existing_tgt = session.scalar(select(Tenant).where(Tenant.id == tgt_slug))
            if existing_tgt:
                raise ValueError(f"Target tenant '{tgt_slug}' already exists.")

            src_config = session.scalar(select(TenantConfig).where(TenantConfig.tenant_id == src_slug))

            # 1. Provision target tenant database
            tgt_name = target_name or f"{src_tenant.name} (Clone)"
            tgt_prov = self.provisioner.provision_tenant(
                tenant_id=tgt_slug,
                db_dialect=src_tenant.db_mode.lower(),
            )

            # 2. Clone Tenant Record
            tgt_tenant = Tenant(
                id=tgt_slug,
                name=tgt_name,
                status="ACTIVE",
                license_tier=src_tenant.license_tier,
                db_mode=src_tenant.db_mode,
                max_users=src_tenant.max_users,
                storage_region=src_tenant.storage_region,
                metadata_json=src_tenant.metadata_json,
            )
            session.add(tgt_tenant)

            # 3. Clone Tenant Config
            if src_config:
                tgt_config = TenantConfig(
                    tenant_id=tgt_slug,
                    credential_mode=src_config.credential_mode,
                    encrypted_gemini_api_key=src_config.encrypted_gemini_api_key,
                    encrypted_openai_api_key=src_config.encrypted_openai_api_key,
                    encrypted_waba_token=src_config.encrypted_waba_token,
                    waba_phone_number_id=src_config.waba_phone_number_id,
                    default_timezone=src_config.default_timezone,
                    brand_name=tgt_name,
                    metadata_json=src_config.metadata_json,
                )
                session.add(tgt_config)

            # 4. Clone Domains
            subdomain = f"{tgt_slug}.release100.com"
            tgt_domain = TenantDomain(
                tenant_id=tgt_slug,
                domain_name=subdomain,
                is_primary=True,
                is_verified=True,
            )
            session.add(tgt_domain)
            register_domain_mapping(subdomain, tgt_slug)

            # 5. Clone Users belonging to source tenant into target tenant
            src_users = list(session.scalars(select(PlatformUser).where(PlatformUser.tenant_id == src_slug)).all())
            cloned_user_count = 0
            for u in src_users:
                # Disambiguate phone for clone (e.g. +clone_<tgt_slug>_<phone>)
                cloned_phone = f"+{tgt_slug}_{u.phone_number.lstrip('+')}"
                cloned_user = PlatformUser(
                    tenant_id=tgt_slug,
                    phone_number=cloned_phone,
                    full_name=u.full_name,
                    role=u.role,
                    status=u.status,
                    allowed_cartridges_json=u.allowed_cartridges_json,
                    timezone=u.timezone,
                )
                session.add(cloned_user)
                cloned_user_count += 1

            # 6. Deep Database Data Snapshot Copy (Table-by-Table)
            copied_tables: Dict[str, int] = {}
            src_engine = self.provisioner.get_tenant_engine(src_slug)
            tgt_engine = self.provisioner.get_tenant_engine(tgt_slug)

            src_meta = MetaData()
            src_meta.reflect(bind=src_engine)

            for table_name, table_obj in src_meta.tables.items():
                with src_engine.connect() as s_conn, tgt_engine.connect() as t_conn:
                    rows = list(s_conn.execute(select(table_obj)).mappings().all())
                    if rows:
                        t_conn.execute(table_obj.delete())
                        t_conn.execute(table_obj.insert(), [dict(r) for r in rows])
                        t_conn.commit()
                    copied_tables[table_name] = len(rows)

            # 7. Audit Log
            self._log_audit_event(
                session=session,
                tenant_id=tgt_slug,
                action="DEEP_CLONE",
                performed_by=performed_by,
                payload={
                    "source_tenant": src_slug,
                    "target_tenant": tgt_slug,
                    "cloned_users_count": cloned_user_count,
                    "copied_tables": copied_tables,
                },
            )

            session.commit()
            logger.info("[TenantLifecycle] Completed Deep-Clone from %s to %s", src_slug, tgt_slug)
            return {
                "source_tenant": src_slug,
                "target_tenant": tgt_tenant.to_dict(),
                "cloned_users_count": cloned_user_count,
                "copied_tables": copied_tables,
            }

    def transfer_tenant(
        self,
        slug: str,
        target_db_url: Optional[str] = None,
        target_region: Optional[str] = None,
        performed_by: str = "devops_admin",
    ) -> Dict[str, Any]:
        """Execute physical database migration and geo-region cutover for a tenant."""
        clean_slug = slug.lower().strip()
        with self.session_factory() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.id == clean_slug))
            if not tenant:
                raise ValueError(f"Tenant '{clean_slug}' not found.")

            # Step 1: Set state to MIGRATING
            tenant.status = "MIGRATING"
            session.commit()

            src_engine = self.provisioner.get_tenant_engine(clean_slug)
            src_meta = MetaData()
            src_meta.reflect(bind=src_engine)

            copied_tables: Dict[str, int] = {}

            # Step 2: Stream database rows if destination DB URL provided
            if target_db_url and target_db_url.strip():
                tgt_engine = create_engine(target_db_url.strip())
                src_meta.create_all(bind=tgt_engine)

                for table_name, table_obj in src_meta.tables.items():
                    with src_engine.connect() as s_conn, tgt_engine.connect() as t_conn:
                        rows = list(s_conn.execute(select(table_obj)).mappings().all())
                        if rows:
                            t_conn.execute(table_obj.delete())
                            t_conn.execute(table_obj.insert(), [dict(r) for r in rows])
                            t_conn.commit()
                        copied_tables[table_name] = len(rows)

                tenant.db_connection_url = target_db_url.strip()

            if target_region and target_region.strip():
                tenant.storage_region = target_region.strip()

            # Step 3: Set status back to ACTIVE
            tenant.status = "ACTIVE"

            self._log_audit_event(
                session=session,
                tenant_id=clean_slug,
                action="TRANSFER",
                performed_by=performed_by,
                payload={
                    "target_region": target_region,
                    "has_new_db": bool(target_db_url),
                    "copied_tables": copied_tables,
                },
            )

            session.commit()
            logger.info("[TenantLifecycle] Completed Transfer for %s (Region: %s)", clean_slug, tenant.storage_region)
            return {
                "tenant_id": clean_slug,
                "status": "ACTIVE",
                "storage_region": tenant.storage_region,
                "copied_tables": copied_tables,
            }

    def update_tenant_profile(
        self,
        slug: str,
        name: Optional[str] = None,
        license_tier: Optional[str] = None,
        status: Optional[str] = None,
        max_users: Optional[int] = None,
        admin_username: Optional[str] = None,
        admin_name: Optional[str] = None,
        admin_email: Optional[str] = None,
        admin_password: Optional[str] = None,
        performed_by: str = "devops_admin",
    ) -> Dict[str, Any]:
        """Update tenant configuration, display name, tier, and root admin credentials."""
        clean_slug = slug.lower().strip()
        variants = list(dict.fromkeys([clean_slug, clean_slug.replace("-", "_"), clean_slug.replace("_", "-")]))

        with self.session_factory() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.id.in_(variants)))
            if not tenant:
                raise ValueError(f"Tenant '{slug}' not found.")

            changes: Dict[str, Any] = {}
            if name and name.strip() and name.strip() != tenant.name:
                changes["name"] = {"from": tenant.name, "to": name.strip()}
                tenant.name = name.strip()
                # Update config brand_name if exists
                cfg = session.scalar(select(TenantConfig).where(TenantConfig.tenant_id.in_(variants)))
                if cfg:
                    cfg.brand_name = name.strip()

            if license_tier and license_tier.strip():
                clean_tier = license_tier.upper().strip()
                if clean_tier != tenant.license_tier:
                    changes["license_tier"] = {"from": tenant.license_tier, "to": clean_tier}
                    tenant.license_tier = clean_tier

            if status and status.strip():
                clean_status = status.upper().strip()
                if clean_status != tenant.status:
                    changes["status"] = {"from": tenant.status, "to": clean_status}
                    tenant.status = clean_status

            if max_users is not None and int(max_users) > 0:
                if int(max_users) != tenant.max_users:
                    changes["max_users"] = {"from": tenant.max_users, "to": int(max_users)}
                    tenant.max_users = int(max_users)

            # Update / Reset Root Admin Account
            admin_stmt = select(PlatformUser).where(
                PlatformUser.tenant_id.in_(variants),
                PlatformUser.role.in_(["admin", "ADMIN", "super_admin"]),
            ).limit(1)
            admin_user = session.scalar(admin_stmt)

            from core_platform.app.auth.strategies import hash_password
            if admin_user:
                if admin_username and admin_username.strip() and admin_username.strip() != admin_user.phone_number:
                    changes["admin_username"] = {"from": admin_user.phone_number, "to": admin_username.strip()}
                    admin_user.phone_number = admin_username.strip()
                if admin_name and admin_name.strip() and admin_name.strip() != admin_user.full_name:
                    changes["admin_name"] = {"from": admin_user.full_name, "to": admin_name.strip()}
                    admin_user.full_name = admin_name.strip()
                if admin_email and admin_email.strip() and admin_email.strip() != admin_user.email:
                    changes["admin_email"] = {"from": admin_user.email, "to": admin_email.strip()}
                    admin_user.email = admin_email.strip()
                if admin_password and admin_password.strip():
                    admin_user.hashed_password = hash_password(admin_password.strip())
                    changes["admin_password"] = "RESET_SUCCESS"
            elif admin_username and admin_username.strip():
                # Provision missing root admin
                user_service = get_user_identity_service(self.engine)
                admin_user = user_service.register_user(
                    phone_number=admin_username.strip(),
                    full_name=admin_name.strip() if admin_name else f"{tenant.name} Admin",
                    tenant_id=tenant.id,
                    role="admin",
                    allowed_cartridges=tenant.allowed_cartridges,
                    password=admin_password.strip() if admin_password and admin_password.strip() else f"{tenant.id.capitalize()}@2026",
                    email=admin_email.strip() if admin_email else None,
                )
                changes["admin_created"] = admin_user.phone_number

            session.commit()

            audit_entry = self._log_audit_event(
                session=session,
                tenant_id=tenant.id,
                action="UPDATE_PROFILE",
                performed_by=performed_by,
                payload={"tenant_id": tenant.id, "changes": changes},
            )

            logger.info("[TenantLifecycle] Updated tenant profile for %s (Changes: %s)", tenant.id, list(changes.keys()))
            return {
                "status": "UPDATED",
                "tenant_id": tenant.id,
                "name": tenant.name,
                "changes": changes,
                "audit_record_hash": audit_entry.record_hash,
            }

    def delete_tenant(
        self,
        slug: str,
        performed_by: str = "devops_admin",
    ) -> Dict[str, Any]:
        """Hard-delete a tenant partition, its domains, configs, users, and audit records."""
        clean_slug = slug.lower().strip()
        variants = list(dict.fromkeys([clean_slug, clean_slug.replace("-", "_"), clean_slug.replace("_", "-")]))

        with self.session_factory() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.id.in_(variants)))
            if not tenant:
                raise ValueError(f"Tenant '{slug}' not found.")

            real_id = tenant.id

            from sqlalchemy import delete as sql_delete
            # 1. Delete associated users
            session.execute(sql_delete(PlatformUser).where(PlatformUser.tenant_id.in_(variants)))
            # 2. Delete domains
            session.execute(sql_delete(TenantDomain).where(TenantDomain.tenant_id.in_(variants)))
            # 3. Delete config
            session.execute(sql_delete(TenantConfig).where(TenantConfig.tenant_id.in_(variants)))
            # 4. Delete audit logs
            session.execute(sql_delete(TenantAuditLog).where(TenantAuditLog.tenant_id.in_(variants)))
            # 5. Delete tenant record
            session.delete(tenant)
            session.commit()

            # Clean cache
            from core_platform.app.middleware.tenant_context import clear_domain_mappings
            clear_domain_mappings()

            logger.info("[TenantLifecycle] Deleted tenant: %s by %s", real_id, performed_by)
            return {
                "status": "DELETED",
                "tenant_id": real_id,
            }


# Global singleton
_manager_instance: Optional[TenantLifecycleManager] = None


def get_tenant_lifecycle_manager(db_url: Optional[str] = None) -> TenantLifecycleManager:
    """Retrieve global TenantLifecycleManager instance."""
    global _manager_instance
    if _manager_instance is None or db_url is not None:
        _manager_instance = TenantLifecycleManager(db_url=db_url)
    return _manager_instance
