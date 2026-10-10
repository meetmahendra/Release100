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
Unit Test Suite for WhatsApp Google OAuth Magic Link Flow and Token Lifecycle.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from apps.mail_organizer.connectors.auth_manager import (
    decrypt_user_tokens,
    encrypt_user_tokens,
    get_user_access_token,
)
from core_platform.app.config import settings
from core_platform.app.identity.magic_link import generate_magic_link_token
from core_platform.app.identity.service import get_user_identity_service
from core_platform.app.ingress.whatsapp_router import dispatch_whatsapp_payload
from core_platform.main import app


@pytest.fixture
def registered_user() -> Any:
    """Create a test user in the identity registry."""
    service = get_user_identity_service()
    user = service.register_user(
        phone_number="+15559876543",
        full_name="OAuth Test User",
        tenant_id="tenant_oauth_test",
        allowed_cartridges=["mail_organizer"],
    )
    return user


class TestMagicLinkOAuthConnect:
    """Test /auth/google/connect initiation endpoint."""

    def test_connect_with_valid_token(self, registered_user: Any, monkeypatch: Any) -> None:
        client = TestClient(app)
        token = generate_magic_link_token(
            user_id=registered_user.id,
            phone_number=registered_user.phone_number,
            tenant_id=registered_user.tenant_id,
        )

        with patch("core_platform.app.ingress.oauth_router.find_client_credentials") as mock_creds:
            mock_creds.return_value = {
                "client_id": "test_client_id_123.apps.googleusercontent.com",
                "client_secret": "test_client_secret_xyz",
            }

            resp = client.get(f"/auth/google/connect?token={token}", follow_redirects=False)
            assert resp.status_code == 302
            redirect_url = resp.headers["location"]
            assert "accounts.google.com/o/oauth2/v2/auth" in redirect_url
            assert "client_id=test_client_id_123" in redirect_url
            assert f"state={token}" in redirect_url

    def test_connect_with_expired_token(self) -> None:
        client = TestClient(app)
        expired_token = generate_magic_link_token(
            user_id="user_dummy",
            phone_number="+10000000000",
            expiry_minutes=-10,
        )

        resp = client.get(f"/auth/google/connect?token={expired_token}")
        assert resp.status_code == 400
        assert "Authentication Link Expired or Invalid" in resp.text


class TestMagicLinkOAuthCallback:
    """Test /auth/google/callback OAuth exchange and token vaulting."""

    def test_callback_success(self, registered_user: Any) -> None:
        client = TestClient(app)
        token = generate_magic_link_token(
            user_id=registered_user.id,
            phone_number=registered_user.phone_number,
            tenant_id=registered_user.tenant_id,
        )

        with patch("core_platform.app.ingress.oauth_router.find_client_credentials") as mock_creds, \
             patch("urllib.request.urlopen") as mock_urlopen:

            mock_creds.return_value = {
                "client_id": "mock_client_id_123",
                "client_secret": "mock_client_secret_xyz",
            }

            # Mock responses for token exchange and userinfo
            mock_token_resp = MagicMock()
            mock_token_resp.status = 200
            mock_token_resp.read.return_value = json.dumps({
                "access_token": "ya29.mock_access_token_12345",
                "refresh_token": "1//mock_refresh_token_67890",
                "expires_in": 3600,
                "token_type": "Bearer",
            }).encode("utf-8")
            mock_token_resp.__enter__.return_value = mock_token_resp

            mock_userinfo_resp = MagicMock()
            mock_userinfo_resp.status = 200
            mock_userinfo_resp.read.return_value = json.dumps({
                "email": "connected_user@example.com",
                "name": "Connected User",
            }).encode("utf-8")
            mock_userinfo_resp.__enter__.return_value = mock_userinfo_resp

            mock_urlopen.side_effect = [mock_token_resp, mock_userinfo_resp]


            resp = client.get(f"/auth/google/callback?code=mock_auth_code&state={token}")
            assert resp.status_code == 200
            assert "Account Connected Successfully" in resp.text

            # Verify user record updated in database
            service = get_user_identity_service()
            updated_user = service.get_user_by_id(registered_user.id)
            assert updated_user is not None
            assert updated_user.google_email == "connected_user@example.com"
            assert updated_user.encrypted_oauth_tokens is not None

            # Verify decrypted tokens
            decrypted = decrypt_user_tokens(updated_user.encrypted_oauth_tokens, updated_user.user_secret_salt)
            assert decrypted is not None
            assert decrypted["access_token"] == "ya29.mock_access_token_12345"
            assert decrypted["refresh_token"] == "1//mock_refresh_token_67890"

    def test_callback_notifies_cartridges_via_hook(self, registered_user: Any) -> None:
        """OAuth success must invoke on_account_linked on all active cartridges."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from core_platform.app.identity.magic_link import generate_magic_link_token

        token = generate_magic_link_token(registered_user.id, registered_user.phone_number, tenant_id=registered_user.tenant_id, expiry_minutes=15)
        client = TestClient(app)

        mock_app = MagicMock()
        mock_app.on_account_linked = AsyncMock()

        with patch("core_platform.app.ingress.oauth_router.find_client_credentials") as mock_creds, \
             patch("urllib.request.urlopen") as mock_urlopen, \
             patch("core_platform.main.plugin_loader.get_all_applications", return_value={"test_cartridge": mock_app}):

            mock_creds.return_value = {
                "client_id": "mock_client_id_123",
                "client_secret": "mock_client_secret_xyz",
            }

            mock_token_resp = MagicMock()
            mock_token_resp.status = 200
            mock_token_resp.read.return_value = json.dumps({
                "access_token": "ya29.mock_access_token_999",
                "refresh_token": "1//mock_refresh_token_999",
                "expires_in": 3600,
                "token_type": "Bearer",
            }).encode("utf-8")
            mock_token_resp.__enter__.return_value = mock_token_resp

            mock_userinfo_resp = MagicMock()
            mock_userinfo_resp.status = 200
            mock_userinfo_resp.read.return_value = json.dumps({
                "email": "hook_test_user@example.com",
            }).encode("utf-8")
            mock_userinfo_resp.__enter__.return_value = mock_userinfo_resp

            mock_urlopen.side_effect = [mock_token_resp, mock_userinfo_resp]

            resp = client.get(f"/auth/google/callback?code=mock_code&state={token}")
            assert resp.status_code == 200
            mock_app.on_account_linked.assert_called_once_with(
                user_id=registered_user.id,
                provider="google",
                details={
                    "email": "hook_test_user@example.com",
                    "phone_number": registered_user.phone_number,
                    "tenant_id": registered_user.tenant_id,
                },
            )

    def test_callback_with_oauth_error(self) -> None:
        client = TestClient(app)
        resp = client.get("/auth/google/callback?error=access_denied")
        assert resp.status_code == 400
        assert "Google Authorization Cancelled" in resp.text


class TestWhatsAppConnectCommand:
    """Test 'connect' command handling in WhatsApp ingress."""

    @pytest.mark.asyncio
    async def test_connect_command_returns_magic_link(self, registered_user: Any) -> None:
        payload: Dict[str, Any] = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": registered_user.phone_number.lstrip("+"),
                            "text": {"body": "connect"},
                        }]
                    }
                }]
            }]
        }

        res = await dispatch_whatsapp_payload(payload)
        assert res["status"] == "EVENT_RECEIVED"
        reply = res["reply_message"]
        assert "Connect Your Google Account" in reply
        assert "/auth/google/connect?token=" in reply


class TestPerUserTokenLifecycle:
    """Test encryption, decryption, and auto-refresh for individual user tokens."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        salt = "abcdef1234567890"
        tokens = {
            "access_token": "ya29.token123",
            "refresh_token": "1//refresh456",
            "email": "test@domain.com",
        }

        encrypted = encrypt_user_tokens(tokens, salt)
        assert isinstance(encrypted, str)
        assert encrypted != json.dumps(tokens)

        decrypted = decrypt_user_tokens(encrypted, salt)
        assert decrypted == tokens

    def test_get_user_access_token_active(self, registered_user: Any) -> None:
        service = get_user_identity_service()
        tokens = {
            "access_token": "ya29.valid_token_active",
            "refresh_token": "1//refresh_token",
            "client_id": "cid",
            "client_secret": "csec",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        enc = encrypt_user_tokens(tokens, registered_user.user_secret_salt)
        service.update_user_tokens(registered_user.id, enc, google_email="test@domain.com")

        user = service.get_user_by_id(registered_user.id)
        assert user is not None
        token = get_user_access_token(user)
        assert token == "ya29.valid_token_active"
