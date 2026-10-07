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
Unit Test Suite for Multi-Tenant Identity, User Registry, Schema Provisioning, and Magic Links.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, Generator
import pytest
from starlette.testclient import TestClient

from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.config import settings
from core_platform.app.db.tenant_provisioner import (
    get_tenant_engine,
    get_tenant_session,
    list_provisioned_tenants,
    provision_tenant,
)
from core_platform.app.identity.magic_link import (
    build_magic_link_url,
    generate_magic_link_token,
    verify_magic_link_token,
)
from core_platform.app.identity.models import PlatformUser
from core_platform.app.identity.service import UserIdentityService, get_user_identity_service
from core_platform.app.ingress.whatsapp_router import dispatch_whatsapp_payload
from core_platform.main import app


@pytest.fixture
def temp_user_db() -> Generator[UserIdentityService, None, None]:
    """Provide an isolated temporary UserIdentityService instance for tests."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_users.db"
    service = UserIdentityService(db_path=db_path)
    yield service
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestUserIdentityService:
    """Test user registration, querying, entitlements, and lifecycle."""

    def test_register_and_get_user(self, temp_user_db: UserIdentityService) -> None:
        user = temp_user_db.register_user(
            phone_number="+1 555-123-4567",
            full_name="Alice Smith",
            tenant_id="tenant_alpha",
            role="user",
            allowed_cartridges=["mail_organizer"],
            timezone="America/New_York",
        )

        assert user.phone_number == "+15551234567"
        assert user.full_name == "Alice Smith"
        assert user.tenant_id == "tenant_alpha"
        assert user.role == "user"
        assert user.status == "active"
        assert user.allowed_cartridges == ["mail_organizer"]
        assert user.user_secret_salt is not None
        assert len(user.user_secret_salt) == 32

        # Query by normalized phone
        fetched = temp_user_db.get_user_by_phone("+15551234567")
        assert fetched is not None
        assert fetched.id == user.id

        # Query by raw formatted phone
        fetched_raw = temp_user_db.get_user_by_phone("+1 (555) 123-4567")
        assert fetched_raw is not None
        assert fetched_raw.id == user.id

        # Query by ID
        fetched_id = temp_user_db.get_user_by_id(user.id)
        assert fetched_id is not None
        assert fetched_id.phone_number == "+15551234567"

    def test_re_register_updates_record(self, temp_user_db: UserIdentityService) -> None:
        user1 = temp_user_db.register_user(
            phone_number="+91 9876543210",
            full_name="Bob Original",
            tenant_id="tenant_beta",
            allowed_cartridges=["mail_organizer"],
        )
        assert user1.full_name == "Bob Original"

        user2 = temp_user_db.register_user(
            phone_number="+919876543210",
            full_name="Bob Updated",
            tenant_id="tenant_beta",
            allowed_cartridges=["mail_organizer", "temperature_marker"],
        )
        assert user2.id == user1.id
        assert user2.full_name == "Bob Updated"
        assert user2.allowed_cartridges == ["mail_organizer", "temperature_marker"]

    def test_entitlement_check(self, temp_user_db: UserIdentityService) -> None:
        temp_user_db.register_user(
            phone_number="+1234567890",
            full_name="Charlie",
            allowed_cartridges=["temperature_marker"],
        )

        assert temp_user_db.is_user_entitled("+1234567890", "temperature_marker") is True
        assert temp_user_db.is_user_entitled("+1234567890", "mail_organizer") is False
        assert temp_user_db.is_user_entitled("+9999999999", "mail_organizer") is False

    def test_whatsapp_heartbeat_and_24h_window(self, temp_user_db: UserIdentityService) -> None:
        user = temp_user_db.register_user(
            phone_number="+1987654321",
            full_name="Dave",
        )
        assert user.last_whatsapp_interaction_at is None
        assert user.is_within_24h_window() is False

        # Update heartbeat
        updated = temp_user_db.update_whatsapp_heartbeat(user.id)
        assert updated is not None
        assert updated.last_whatsapp_interaction_at is not None
        assert updated.is_within_24h_window() is True

        # Test window boundary
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        user.last_whatsapp_interaction_at = old_time
        assert user.is_within_24h_window() is False

    def test_token_update_and_status_toggle(self, temp_user_db: UserIdentityService) -> None:
        user = temp_user_db.register_user(
            phone_number="+1122334455",
            full_name="Eve",
        )

        # Update tokens
        updated = temp_user_db.update_user_tokens(
            user_id=user.id,
            google_email="eve@example.com",
            encrypted_tokens="enc_token_payload_xyz",
        )
        assert updated is not None
        assert updated.google_email == "eve@example.com"
        assert updated.encrypted_oauth_tokens == "enc_token_payload_xyz"

        # Update status
        suspended = temp_user_db.update_user_status(user.id, "suspended")
        assert suspended is not None
        assert suspended.status == "suspended"

        # Update entitlements
        entitled = temp_user_db.update_user_entitlements(user.id, ["mail_organizer"])
        assert entitled is not None
        assert entitled.allowed_cartridges == ["mail_organizer"]

        # Delete
        assert temp_user_db.delete_user(user.id) is True
        assert temp_user_db.get_user_by_id(user.id) is None


class TestTenantProvisioner:
    """Test isolated tenant schema and physical SQLite WAL partitioning."""

    def test_provision_tenant_sqlite(self) -> None:
        tenant_id = "tenant_test_unit_01"
        res = provision_tenant(
            tenant_id=tenant_id,
            db_dialect="sqlite",
            cartridges=["mail_organizer", "temperature_marker"],
        )

        assert res["tenant_id"] == tenant_id
        assert res["dialect"] == "sqlite"
        assert "mail_organizer" in res["cartridges"]
        assert "temperature_marker" in res["cartridges"]

        # Engine & Session test
        engine = get_tenant_engine(tenant_id)
        assert engine is not None

        with get_tenant_session(tenant_id) as session:
            # Verify tables exist in SQLite sqlite_master
            from sqlalchemy import text
            result = session.execute(text("SELECT name FROM sqlite_master WHERE type='table';")).fetchall()
            table_names = [r[0] for r in result]
            assert "email_actions" in table_names or "attendance_records" in table_names

        # List tenants
        tenants = list_provisioned_tenants()
        tenant_ids = [t["tenant_id"] for t in tenants]
        assert tenant_id in tenant_ids


class TestMagicLink:
    """Test ephemeral signed JWT magic link generation and verification."""

    def test_generate_and_verify_magic_link(self) -> None:
        token = generate_magic_link_token(
            user_id="user_123",
            phone_number="+15550001111",
            tenant_id="tenant_xyz",
            expiry_minutes=15,
        )
        assert token is not None

        payload = verify_magic_link_token(token)
        assert payload is not None
        assert payload["user_id"] == "user_123"
        assert payload["phone_number"] == "+15550001111"
        assert payload["tenant_id"] == "tenant_xyz"

    def test_verify_expired_token(self) -> None:
        token = generate_magic_link_token(
            user_id="user_123",
            phone_number="+15550001111",
            expiry_minutes=-5,  # Already expired
        )
        payload = verify_magic_link_token(token)
        assert payload is None

    def test_verify_tampered_token(self) -> None:
        token = generate_magic_link_token(
            user_id="user_123",
            phone_number="+15550001111",
        )
        tampered = token[:-4] + "abcd"
        payload = verify_magic_link_token(tampered)
        assert payload is None

    def test_build_magic_link_url(self) -> None:
        url = build_magic_link_url(
            user_id="u_99",
            phone_number="+15559998888",
            base_url="https://relay.release100.example.com",
        )
        assert url.startswith("https://relay.release100.example.com/auth/google/connect?token=")


class TestWhatsAppIngressMultiTenantGate:
    """Test WhatsApp ingress routing with user registration & entitlement gating."""

    @pytest.mark.asyncio
    async def test_unregistered_user_rejection(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(settings, "WHATSAPP_REQUIRE_REGISTRATION", True)
        
        # Dispatch message from unknown sender
        payload: Dict[str, Any] = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "9999999999",
                            "text": {"body": "Hello"},
                        }]
                    }
                }]
            }]
        }

        res = await dispatch_whatsapp_payload(payload)
        assert res["status"] == "UNREGISTERED_USER"
        assert "Access Denied" in res["reply_message"]

    @pytest.mark.asyncio
    async def test_inactive_user_rejection(self, monkeypatch: Any) -> None:
        service = get_user_identity_service()
        user = service.register_user(phone_number="+19998887777", full_name="Inactive Test")
        service.update_user_status(user.id, "suspended")

        payload: Dict[str, Any] = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "19998887777",
                            "text": {"body": "Hello"},
                        }]
                    }
                }]
            }]
        }

        res = await dispatch_whatsapp_payload(payload)
        assert res["status"] == "INACTIVE_USER"
        assert "Access Suspended" in res["reply_message"]


class TestAdminShellUsersAndTenants:
    """Test Admin Shell routes for /admin/users and /admin/tenants."""

    def test_admin_users_and_tenants_view(self) -> None:
        token = create_jwt_token(principal_id="admin_test", roles=["admin"], permitted_apps=["*"])
        client = TestClient(app, cookies={"admin_token": token, "csrf_token": "test_csrf"})

        # GET /admin/users
        resp = client.get("/admin/users")
        assert resp.status_code == 200
        assert "User Registry" in resp.text or "Multi-Tenant" in resp.text

        # GET /admin/tenants
        resp_tenants = client.get("/admin/tenants")
        assert resp_tenants.status_code == 200
        assert "Company Profile" in resp_tenants.text or "Tenant" in resp_tenants.text

        # POST /admin/users create
        resp_post = client.post(
            "/admin/users",
            data={
                "phone_number": "+14155552671",
                "full_name": "Admin Registered User",
                "tenant_id": "default_tenant",
                "role": "user",
                "timezone": "America/Los_Angeles",
                "cartridge_mail": "mail_organizer",
                "csrf_token": "test_csrf",
            },
            follow_redirects=False,
        )
        assert resp_post.status_code == 303

        # Verify created
        service = get_user_identity_service()
        user = service.get_user_by_phone("+14155552671")
        assert user is not None
        assert user.full_name == "Admin Registered User"

        # GET /admin/users/{user_id}/magic-link
        resp_ml = client.get(f"/admin/users/{user.id}/magic-link")
        assert resp_ml.status_code == 200
        ml_data = resp_ml.json()
        assert "magic_link" in ml_data
        assert str(ml_data["user_id"]) == str(user.id)
