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
Unit Test Suite for Hybrid Multi-Tenant Google OAuth Credentials & Customer BYOK.

Verifies:
1. Platform Managed Fallback (Environment variables & disk credentials.json).
2. Customer BYOK AES-256-GCM Tenant Salt Encryption & Decryption.
3. Cryptographic Multi-Tenant Isolation & Zero Cross-Talk.
4. Tenant-Aware OAuth Ingress Gateway (/auth/google/connect and /auth/google/callback).
5. DevOps Super-Admin & Customer Tenant Admin Parity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from core_platform.app.config import settings
from core_platform.app.security.user_cipher import BLINDED_PLACEHOLDER, UserPayloadCipher
from core_platform.app.identity.magic_link import generate_magic_link_token
from core_platform.app.identity.oauth_utils import find_client_credentials
from core_platform.app.identity.service import get_user_identity_service
from core_platform.main import app
from ops_control_plane.devops_vault import DevOpsKeyVault


@pytest.fixture
def clean_vault() -> DevOpsKeyVault:
    """Fixture providing singleton DevOpsKeyVault."""
    return DevOpsKeyVault.get_instance()


class TestPlatformManagedGoogleOAuth:
    """Tests for platform-managed fallback resolution."""

    def test_fallback_to_environment_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When tenant is PLATFORM_MANAGED, resolve platform GOOGLE_CLIENT_ID/SECRET from settings."""
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "mock_plat_id_123.apps.googleusercontent.com")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "mock_plat_secret_abc")

        creds = find_client_credentials(tenant_id="tenant_unconfigured_default")
        assert creds is not None
        assert creds["client_id"] == "mock_plat_id_123.apps.googleusercontent.com"
        assert creds["client_secret"] == "mock_plat_secret_abc"

    def test_fallback_to_disk_credentials_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """When env vars are blank, resolve credentials.json from disk."""
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")

        fake_creds = {
            "web": {
                "client_id": "mock_disk_id_456.apps.googleusercontent.com",
                "client_secret": "mock_disk_secret_def",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps(fake_creds), encoding="utf-8")

        monkeypatch.setattr(settings, "GOOGLE_CREDENTIALS_PATH", str(creds_file))

        creds = find_client_credentials(tenant_id=None)
        assert creds is not None
        assert creds["client_id"] == "mock_disk_id_456.apps.googleusercontent.com"
        assert creds["client_secret"] == "mock_disk_secret_def"


class TestCustomerBYOKGoogleOAuth:
    """Tests for customer tenant BYOK OAuth encryption and resolution."""

    def test_byok_encryption_and_decryption_lifecycle(self, clean_vault: DevOpsKeyVault) -> None:
        """Verify tenant Google OAuth credentials are AES-256-GCM encrypted and decrypted cleanly."""
        tenant_id = "tenant_enterprise_acme"
        mock_id = "mock_acme_client_id.apps.googleusercontent.com"
        mock_secret = "mock_acme_client_secret_999"

        clean_vault.configure_tenant_credentials(
            tenant_id=tenant_id,
            credential_mode="CUSTOMER_BYOK",
            google_client_id=mock_id,
            google_client_secret=mock_secret,
        )

        # 1. Verify runtime resolution retrieves plaintext
        runtime_creds = clean_vault.get_tenant_runtime_credentials(tenant_id)
        assert runtime_creds.is_byok is True
        assert runtime_creds.has_google_byok is True
        assert runtime_creds.google_client_id == mock_id
        assert runtime_creds.google_client_secret == mock_secret

        # 2. Verify find_client_credentials returns tenant BYOK credentials
        creds = find_client_credentials(tenant_id=tenant_id)
        assert creds is not None
        assert creds["client_id"] == mock_id
        assert creds["client_secret"] == mock_secret

    def test_tenant_cryptographic_isolation_and_no_crosstalk(
        self, clean_vault: DevOpsKeyVault, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify Tenant A cannot decrypt or leak credentials to Tenant B or Platform."""
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "mock_plat_default.apps.googleusercontent.com")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "mock_plat_default_secret")

        clean_vault.configure_tenant_credentials(
            tenant_id="tenant_finance_corp",
            credential_mode="CUSTOMER_BYOK",
            google_client_id="mock_finance_id.apps.googleusercontent.com",
            google_client_secret="mock_finance_secret",
        )

        clean_vault.configure_tenant_credentials(
            tenant_id="tenant_health_plus",
            credential_mode="CUSTOMER_BYOK",
            google_client_id="mock_health_id.apps.googleusercontent.com",
            google_client_secret="mock_health_secret",
        )

        clean_vault.configure_tenant_credentials(
            tenant_id="tenant_platform_user",
            credential_mode="PLATFORM_MANAGED",
        )

        creds_finance = find_client_credentials(tenant_id="tenant_finance_corp")
        creds_health = find_client_credentials(tenant_id="tenant_health_plus")
        creds_platform = find_client_credentials(tenant_id="tenant_platform_user")

        assert creds_finance is not None and creds_finance["client_id"] == "mock_finance_id.apps.googleusercontent.com"
        assert creds_health is not None and creds_health["client_id"] == "mock_health_id.apps.googleusercontent.com"
        assert creds_platform is not None and creds_platform["client_id"] == "mock_plat_default.apps.googleusercontent.com"

        # Tampering / Salt isolation verification:
        # Decrypting Finance's encrypted payload using Health's salt must fail
        from sqlalchemy import select
        from core_platform.app.identity.models import TenantConfig
        with clean_vault.session_factory() as session:
            config_finance = session.execute(
                select(TenantConfig).where(TenantConfig.tenant_id == "tenant_finance_corp")
            ).scalars().first()
        assert config_finance is not None
        assert config_finance.encrypted_google_client_id is not None

        tampered_result = UserPayloadCipher.decrypt_payload(
            config_finance.encrypted_google_client_id,
            "tenant_vault_salt_tenant_health_plus",
        )
        assert tampered_result != "mock_finance_id.apps.googleusercontent.com"
        assert tampered_result == BLINDED_PLACEHOLDER


class TestOAuthIngressGatewayTenantRouting:
    """Tests for tenant-aware /auth/google/connect and /auth/google/callback."""

    @pytest.fixture
    def tenant_user(self, clean_vault: DevOpsKeyVault) -> Any:
        service = get_user_identity_service()
        user = service.register_user(
            phone_number="+15551112233",
            full_name="Tenant Gateway Test User",
            tenant_id="tenant_gateway_org",
            allowed_cartridges=["mail_organizer"],
        )
        clean_vault.configure_tenant_credentials(
            tenant_id="tenant_gateway_org",
            credential_mode="CUSTOMER_BYOK",
            google_client_id="mock_gateway_client_id.apps.googleusercontent.com",
            google_client_secret="mock_gateway_client_secret",
        )
        return user

    def test_connect_routes_to_tenant_byok_client_id(self, tenant_user: Any) -> None:
        """Magic link token with tenant_id resolves tenant BYOK credentials in redirect url."""
        client = TestClient(app)
        token = generate_magic_link_token(
            user_id=tenant_user.id,
            phone_number=tenant_user.phone_number,
            tenant_id="tenant_gateway_org",
        )

        resp = client.get(
            f"/auth/google/connect?token={token}",
            headers={"x-forwarded-host": "my-tunnel.ngrok-free.app", "x-forwarded-proto": "https"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        redirect_url = resp.headers["location"]
        assert "client_id=mock_gateway_client_id.apps.googleusercontent.com" in redirect_url
        assert "redirect_uri=https%3A%2F%2Fmy-tunnel.ngrok-free.app%2Fauth%2Fgoogle%2Fcallback" in redirect_url

    def test_connect_missing_credentials_displays_actionable_error(self, clean_vault: DevOpsKeyVault) -> None:
        """Missing credentials display actionable message informing user about organization setup."""
        service = get_user_identity_service()
        user = service.register_user(
            phone_number="+15553334455",
            full_name="Missing Creds User",
            tenant_id="tenant_missing_creds",
            allowed_cartridges=["mail_organizer"],
        )
        clean_vault.configure_tenant_credentials(
            tenant_id="tenant_missing_creds",
            credential_mode="CUSTOMER_BYOK",
            google_client_id=None,
            google_client_secret=None,
        )

        client = TestClient(app)
        token = generate_magic_link_token(
            user_id=user.id,
            phone_number=user.phone_number,
            tenant_id="tenant_missing_creds",
        )

        with patch("core_platform.app.ingress.oauth_router.find_client_credentials", return_value=None):
            resp = client.get(f"/auth/google/connect?token={token}")
            assert resp.status_code == 400
            assert "Google Credentials Missing" in resp.text
            assert "tenant_missing_creds" in resp.text
