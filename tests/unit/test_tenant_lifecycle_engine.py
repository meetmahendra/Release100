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
Unit tests for DevOps Tenant Lifecycle Operations Engine.
Validates:
1. Atomic tenant provisioning with isolated DB and root admin user.
2. Decommission & Archive with SHA-256 tamper-evident audit bundle export.
3. Deep-Clone tenant (full configuration + database data snapshot copy).
4. Geo-Specific and Intra-Region tenant transfer and data streaming.
"""

from pathlib import Path
import pytest
from sqlalchemy import create_engine, select, text

from core_platform.app.db.tenant_provisioner import get_tenant_schema_provisioner
from core_platform.app.identity.models import Base, PlatformUser, Tenant, TenantAuditLog
from ops_control_plane.tenant_lifecycle import TenantLifecycleManager


@pytest.fixture
def lifecycle_mgr(tmp_path: Path) -> TenantLifecycleManager:
    """Create lifecycle manager with test database."""
    db_file = tmp_path / "test_platform_registry.db"
    return TenantLifecycleManager(db_url=f"sqlite:///{db_file}")


def test_provision_tenant_atomic(lifecycle_mgr: TenantLifecycleManager) -> None:
    """Verify atomic tenant provisioning creating DB, admin user, and audit log."""
    import uuid
    slug = f"alpha_{uuid.uuid4().hex[:6]}"
    res = lifecycle_mgr.provision_tenant(
        slug=slug,
        name="Alpha Corporation",
        admin_phone="+919876543210",
        admin_name="Alpha Root Admin",
        license_tier="ENTERPRISE",
        max_users=25,
        storage_region="ap-south-1",
        custom_domain=f"mail.{slug}.com",
    )

    assert res["tenant"]["id"] == slug
    assert res["tenant"]["name"] == "Alpha Corporation"
    assert res["admin_user"]["phone_number"] == "+919876543210"
    assert res["admin_user"]["role"] == "admin"

    # Verify audit log recorded
    with lifecycle_mgr.session_factory() as session:
        logs = list(session.scalars(select(TenantAuditLog).where(TenantAuditLog.tenant_id == slug)).all())
        assert len(logs) == 1
        assert logs[0].action == "PROVISION"
        assert len(logs[0].record_hash) == 64


def test_archive_tenant_with_audit_bundle(lifecycle_mgr: TenantLifecycleManager) -> None:
    """Verify tenant archive sets status to ARCHIVED and outputs audit bundle."""
    import uuid
    slug = f"beta_{uuid.uuid4().hex[:6]}"
    lifecycle_mgr.provision_tenant(
        slug=slug,
        name="Beta Logistics",
        admin_phone="+919876543211",
        admin_name="Beta Admin",
    )

    res = lifecycle_mgr.archive_tenant(slug)
    assert res["status"] == "ARCHIVED"
    assert res["audit_records_count"] >= 1
    assert "audit_trail_bundle" in res


def test_deep_clone_tenant_full_data(lifecycle_mgr: TenantLifecycleManager) -> None:
    """Verify Deep-Clone operation copies configuration and historical database data snapshot."""
    import uuid
    src_slug = f"gamma_{uuid.uuid4().hex[:6]}"
    tgt_slug = f"{src_slug}_sandbox"

    # 1. Provision source tenant
    lifecycle_mgr.provision_tenant(
        slug=src_slug,
        name="Gamma Production",
        admin_phone="+919876543212",
        admin_name="Gamma Admin",
    )

    # 2. Insert dummy operational data into source tenant database
    provisioner = get_tenant_schema_provisioner()
    src_engine = provisioner.get_tenant_engine(src_slug)

    with src_engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO mail_rules (rule_type, pattern, action, is_active, created_at) "
            "VALUES ('vip', 'ceo@gamma.com', 'tag_vip', 1, CURRENT_TIMESTAMP)"
        ))
        conn.commit()

    # 3. Deep clone to target sandbox
    clone_res = lifecycle_mgr.deep_clone_tenant(
        source_slug=src_slug,
        target_slug=tgt_slug,
        target_name="Gamma Staging Sandbox",
    )

    assert clone_res["target_tenant"]["id"] == tgt_slug
    assert clone_res["copied_tables"]["mail_rules"] == 1

    # 4. Verify cloned database has the data row
    tgt_engine = provisioner.get_tenant_engine(tgt_slug)
    with tgt_engine.connect() as conn:
        rows = list(conn.execute(text("SELECT pattern FROM mail_rules")).all())
        assert len(rows) == 1
        assert rows[0][0] == "ceo@gamma.com"


def test_transfer_tenant_intra_and_geo(lifecycle_mgr: TenantLifecycleManager, tmp_path: Path) -> None:
    """Verify transfer operation streams database to new target engine/region."""
    import uuid
    slug = f"delta_{uuid.uuid4().hex[:6]}"

    lifecycle_mgr.provision_tenant(
        slug=slug,
        name="Delta Corp",
        admin_phone="+919876543213",
        admin_name="Delta Admin",
        storage_region="ap-south-1",
    )

    # Transfer to a dedicated DB in eu-central-1
    target_db = tmp_path / f"{slug}_frankfurt_dedicated.db"
    target_db_url = f"sqlite:///{target_db}"

    res = lifecycle_mgr.transfer_tenant(
        slug=slug,
        target_db_url=target_db_url,
        target_region="eu-central-1",
    )

    assert res["status"] == "ACTIVE"
    assert res["storage_region"] == "eu-central-1"

    with lifecycle_mgr.session_factory() as session:
        t = session.scalar(select(Tenant).where(Tenant.id == slug))
        assert t is not None
        assert t.storage_region == "eu-central-1"
        assert t.db_connection_url == target_db_url


def test_provision_tenant_duplicate_domain_and_slug_rejected(lifecycle_mgr: TenantLifecycleManager) -> None:
    """Verify that duplicate custom vanity domains and slugs are strictly rejected."""
    import uuid
    slug1 = f"tenant1_{uuid.uuid4().hex[:6]}"
    slug2 = f"tenant2_{uuid.uuid4().hex[:6]}"
    shared_domain = f"custom.{uuid.uuid4().hex[:6]}.example.com"

    # 1. Provision first tenant with shared_domain
    lifecycle_mgr.provision_tenant(
        slug=slug1,
        name="Tenant One",
        admin_phone="+919876543220",
        admin_name="Admin One",
        custom_domain=shared_domain,
    )

    # 2. Attempting to provision duplicate slug raises ValueError
    with pytest.raises(ValueError, match="already exists"):
        lifecycle_mgr.provision_tenant(
            slug=slug1,
            name="Tenant One Duplicate",
            admin_phone="+919876543221",
            admin_name="Admin Dup",
        )

    # 3. Attempting to provision second tenant with same custom domain raises ValueError
    with pytest.raises(ValueError, match="already registered to tenant"):
        lifecycle_mgr.provision_tenant(
            slug=slug2,
            name="Tenant Two",
            admin_phone="+919876543222",
            admin_name="Admin Two",
            custom_domain=shared_domain,
        )

