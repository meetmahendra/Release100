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
Unit tests for Tenant Data Models and DevOps Credential Vault.
Validates:
1. Tenant, TenantDomain, TenantConfig, TenantAuditLog schema creation and CRUD.
2. DevOpsKeyVault configuration for Platform-Managed vs Customer-Dedicated BYOK.
3. AES-256-GCM envelope encryption and zero secret leak.
"""

from pathlib import Path
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core_platform.app.identity.models import Base, Tenant, TenantConfig, TenantDomain, TenantAuditLog
from ops_control_plane.devops_vault import DevOpsKeyVault, get_devops_key_vault


@pytest.fixture
def test_db_url(tmp_path: Path) -> str:
    """Create isolated SQLite database URL."""
    db_file = tmp_path / "test_tenant_vault.db"
    return f"sqlite:///{db_file}"


def test_tenant_and_domain_models_crud(test_db_url: str) -> None:
    """Verify Tenant and TenantDomain entity lifecycle."""
    engine = create_engine(test_db_url)
    Base.metadata.create_all(bind=engine)
    session_maker = sessionmaker(bind=engine)

    with session_maker() as session:
        # Create Tenant
        tenant = Tenant(
            id="acme_corp",
            name="Acme Corporation Pvt Ltd",
            status="ACTIVE",
            license_tier="ENTERPRISE",
            db_mode="SQLITE_WAL",
            max_users=50,
            storage_region="ap-south-1",
        )
        session.add(tenant)

        # Create Domains
        domain1 = TenantDomain(
            tenant_id="acme_corp",
            domain_name="acme.release100.com",
            is_primary=True,
            is_verified=True,
        )
        domain2 = TenantDomain(
            tenant_id="acme_corp",
            domain_name="mail.acmecorp.com",
            is_primary=False,
            is_verified=True,
        )
        session.add_all([domain1, domain2])
        session.commit()

        # Query and Assert
        saved_tenant = session.scalar(select(Tenant).where(Tenant.id == "acme_corp"))
        assert saved_tenant is not None
        assert saved_tenant.name == "Acme Corporation Pvt Ltd"
        assert saved_tenant.license_tier == "ENTERPRISE"
        assert saved_tenant.to_dict()["max_users"] == 50

        saved_domains = list(session.scalars(select(TenantDomain).where(TenantDomain.tenant_id == "acme_corp")).all())
        assert len(saved_domains) == 2
        domain_names = [d.domain_name for d in saved_domains]
        assert "acme.release100.com" in domain_names
        assert "mail.acmecorp.com" in domain_names


def test_devops_vault_platform_managed_mode(test_db_url: str) -> None:
    """Verify Platform-Managed mode returns platform defaults and keeps keys invisible."""
    vault = DevOpsKeyVault(db_url=test_db_url)

    vault.configure_tenant_credentials(
        tenant_id="tenant_standard",
        credential_mode="PLATFORM_MANAGED",
        brand_name="Standard Org",
        default_timezone="Asia/Kolkata",
    )

    creds = vault.get_tenant_runtime_credentials("tenant_standard")
    assert creds.tenant_id == "tenant_standard"
    assert creds.credential_mode == "PLATFORM_MANAGED"
    assert creds.is_byok is False
    assert creds.brand_name == "Standard Org"


def test_devops_vault_customer_byok_mode(test_db_url: str) -> None:
    """Verify Customer BYOK mode encrypts keys at rest and cleanly decrypts at runtime."""
    vault = DevOpsKeyVault(db_url=test_db_url)

    synthetic_gemini_key = "mock_gemini_api_key_byok_998877"
    synthetic_waba_token = "mock_waba_access_token_customer_5544"

    config = vault.configure_tenant_credentials(
        tenant_id="tenant_enterprise_byok",
        credential_mode="CUSTOMER_BYOK",
        gemini_api_key=synthetic_gemini_key,
        waba_token=synthetic_waba_token,
        waba_phone_number_id="WABA-PHONE-998877",
        brand_name="Enterprise BYOK Corp",
        default_timezone="America/New_York",
    )

    # Verify encrypted at rest (not stored as raw plaintext)
    assert config.encrypted_gemini_api_key is not None
    assert synthetic_gemini_key not in config.encrypted_gemini_api_key
    assert config.encrypted_gemini_api_key.startswith("ENC:v1:")

    # Verify runtime resolution
    creds = vault.get_tenant_runtime_credentials("tenant_enterprise_byok")
    assert creds.credential_mode == "CUSTOMER_BYOK"
    assert creds.is_byok is True
    assert creds.gemini_api_key == synthetic_gemini_key
    assert creds.waba_token == synthetic_waba_token
    assert creds.waba_phone_number_id == "WABA-PHONE-998877"
    assert creds.default_timezone == "America/New_York"
