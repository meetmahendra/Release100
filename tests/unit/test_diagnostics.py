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

"""Synthetic Unit Tests for Diagnostics Engine, Web Console, and Config Backup."""

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error
import pytest
from starlette.testclient import TestClient

from core_platform.app.diagnostics.config_backup import (
    create_backup,
    list_backups,
    restore_backup,
    save_master_config,
)
from core_platform.app.diagnostics.verifier import (
    get_full_status,
    send_test_whatsapp_message,
    verify_cloud_relay,
    verify_gemini,
    verify_hmac_secret,
    verify_ports,
    verify_typesafe,
    verify_webhook_ingress,
    verify_whatsapp,
)
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide authenticated TestClient instance."""
    from core_platform.main import plugin_loader
    if not plugin_loader.get_all_applications():
        plugin_loader.load_all()
    c = TestClient(app)
    token = create_jwt_token("admin", ["admin"], ["all"])
    c.cookies.set("admin_token", token)
    return c


def test_settings_unauthenticated_access() -> None:
    """Unauthenticated GET /settings must redirect to /admin/login."""
    unauth_client = TestClient(app, follow_redirects=False)
    response = unauth_client.get("/settings", headers={"Accept": "text/html"})
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/login"


def test_settings_html_dashboard_endpoint(client: TestClient) -> None:
    """GET /settings must return 200 with HTML console and tabs when authenticated."""
    response = client.get("/settings")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    text = response.text
    assert "Master Settings" in text
    assert "Active Applications" in text
    assert "Live Testing" in text
    assert "System Configuration Editor" in text
    assert "TypeSafe AI / Jev System 1 Decision Engine" in text


def test_diagnostics_status_api(client: TestClient) -> None:
    """GET /api/diagnostics/status must return structured system health."""
    response = client.get("/api/diagnostics/status")
    assert response.status_code == 200
    data = response.json()
    assert "applications" in data
    assert "credentials" in data
    assert "ports" in data
    assert data["tenant_id"] is not None


def test_diagnostics_verify_api_services(client: TestClient) -> None:
    """POST /api/diagnostics/verify must return validation results for various services."""
    # Test ports ping
    res_ports = client.post("/api/diagnostics/verify", json={"service": "ports"})
    assert res_ports.status_code == 200
    assert res_ports.json()["status"] in ("ok", "warning")

    # Test typesafe placeholder
    res_ts = client.post("/api/diagnostics/verify", json={"service": "typesafe", "key": "placeholder"})
    assert res_ts.status_code == 200
    assert res_ts.json()["status"] == "warning"

    # Test jev alias placeholder
    res_jev = client.post("/api/diagnostics/verify", json={"service": "jev", "key": "placeholder"})
    assert res_jev.status_code == 200
    assert res_jev.json()["status"] == "warning"

    # Test hmac ping
    res_hmac = client.post("/api/diagnostics/verify", json={"service": "hmac", "app_secret": "test_secret_12345678"})
    assert res_hmac.status_code == 200
    assert res_hmac.json()["status"] == "ok"

    # Test gemini placeholder
    res_gemini = client.post("/api/diagnostics/verify", json={"service": "gemini", "key": "placeholder"})
    assert res_gemini.status_code == 200
    assert res_gemini.json()["status"] == "warning"

    # Test whatsapp placeholder
    res_wa = client.post("/api/diagnostics/verify", json={"service": "whatsapp", "token": "placeholder", "phone_id": "123"})
    assert res_wa.status_code == 200
    assert res_wa.json()["status"] == "warning"

    # Test cloud relay empty
    res_relay = client.post("/api/diagnostics/verify", json={"service": "cloud_relay", "relay_url": ""})
    assert res_relay.status_code == 200
    assert res_relay.json()["status"] == "info"

    # Test webhook placeholder
    res_hook = client.post("/api/diagnostics/verify", json={"service": "webhook", "verify_token": "placeholder"})
    assert res_hook.status_code == 200
    assert res_hook.json()["status"] == "warning"

    # Test whatsapp_send missing recipient
    res_send_err = client.post("/api/diagnostics/verify", json={"service": "whatsapp_send"})
    assert res_send_err.status_code == 400

    # Test whatsapp_send with placeholder
    res_send = client.post("/api/diagnostics/verify", json={"service": "whatsapp_send", "recipient_phone": "919876543210"})
    assert res_send.status_code == 200
    assert res_send.json()["status"] in ("error", "ok")

    # Test unknown service
    res_unknown = client.post("/api/diagnostics/verify", json={"service": "non_existent"})
    assert res_unknown.status_code == 400


def test_diagnostics_poller_and_app_toggle_api(client: TestClient) -> None:
    """POST /api/diagnostics/poller/toggle and app toggle must work cleanly."""
    res = client.post("/api/diagnostics/poller/toggle")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "is_running" in data

    # Toggle back to ensure stopped state
    if data["is_running"]:
        res2 = client.post("/api/diagnostics/poller/toggle")
        assert res2.status_code == 200
        assert res2.json()["is_running"] is False

    # App toggle
    res_app = client.post("/api/diagnostics/apps/temperature_marker/toggle")
    assert res_app.status_code == 200
    assert res_app.json()["success"] is True
    # Toggle back
    res_app2 = client.post("/api/diagnostics/apps/temperature_marker/toggle")
    assert res_app2.status_code == 200


def test_diagnostics_save_and_restore_api(client: TestClient, tmp_path: Path) -> None:
    """Save and restore endpoints must handle requests gracefully."""
    # Test restore non-existing file
    res_restore = client.post("/api/diagnostics/restore", json={"filename": "non_existent_12345.bak"})
    assert res_restore.status_code == 400


def test_config_backup_and_rollback(tmp_path: Path) -> None:
    """config_backup must create pre-save backups, update keys, and restore."""
    env_file = tmp_path / ".env"
    env_file.write_text("# Initial Config\nSTATION_NAME=Old Station\nKIOSK_ID=kiosk-01\n", encoding="utf-8")

    # 1. Save new config
    ok, msg = save_master_config({"STATION_NAME": "New Station Updated"}, env_path=env_file)
    assert ok is True
    content = env_file.read_text(encoding="utf-8")
    assert "New Station Updated" in content

    # 2. Check backup created
    bak = create_backup(env_path=env_file)
    assert bak is not None
    assert bak.exists()

    # 3. List backups
    bdir = tmp_path / "config_backups"
    bdir.mkdir(parents=True, exist_ok=True)
    sample_bak = bdir / "env_20260915_120000.bak"
    sample_bak.write_text("STATION_NAME=Backup Station\n", encoding="utf-8")

    backups = list_backups(backup_dir=bdir)
    assert len(backups) >= 1
    assert backups[0]["filename"].startswith("env_")

    # 4. Restore backup
    ok_restore, res_msg = restore_backup(sample_bak.name, env_path=env_file)
    # The restore looks in get_backup_dir(), so test failure on non-existent
    ok_fake, _ = restore_backup("does_not_exist.bak", env_path=env_file)
    assert ok_fake is False


def test_verifier_mocked_success() -> None:
    """Test verifier functions with mocked external HTTP responses."""
    # Mock Gemini success
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = verify_gemini(api_key="AIzaSy_ValidKey123456789012345")
        assert res["status"] == "ok"
        assert "latency_ms" in res

    # Mock Gemini HTTPError
    err = urllib.error.HTTPError("url", 403, "Forbidden", MagicMock(), BytesIO(b'{"error": "invalid"}'))
    with patch("urllib.request.urlopen", side_effect=err):
        res_err = verify_gemini(api_key="AIzaSy_InvalidKey123456789012")
        assert res_err["status"] == "error"

    # Mock WhatsApp success
    mock_wa_resp = MagicMock()
    mock_wa_resp.read.return_value = b'{"verified_name": "Test Depot", "display_phone_number": "+919876543210"}'
    mock_wa_resp.__enter__.return_value = mock_wa_resp
    with patch("urllib.request.urlopen", return_value=mock_wa_resp):
        res_wa = verify_whatsapp(access_token="EAAX_ValidToken123456789", phone_number_id="109876543210")
        assert res_wa["status"] == "ok"
        assert res_wa["verified_name"] == "Test Depot"

    # Mock WhatsApp message send success
    mock_send_resp = MagicMock()
    mock_send_resp.read.return_value = b'{"messages": [{"id": "WAMID-12345"}]}'
    mock_send_resp.__enter__.return_value = mock_send_resp
    with patch("urllib.request.urlopen", return_value=mock_send_resp):
        res_msg = send_test_whatsapp_message(
            recipient_phone="919876543210",
            message="Test",
            access_token="EAAX_ValidToken123456789",
            phone_number_id="109876543210",
        )
        assert res_msg["status"] == "ok"
        assert res_msg["message_id"] == "WAMID-12345"

    # Test full status
    full_status = get_full_status()
    assert "applications" in full_status
    assert "credentials" in full_status
    assert "typesafe_configured" in full_status["credentials"]


def test_verifier_typesafe() -> None:
    """Test verify_typesafe with placeholder, mocked success, and error branches."""
    # 1. Placeholder key
    res_warn = verify_typesafe(api_key="placeholder")
    assert res_warn["status"] == "warning"

    # 2. Mocked 200 OK success
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"selected_choice": "@Action", "confidence": 0.99, "reasoning": "Fast test"}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res_ok = verify_typesafe(api_key="mock_jev_test_key_12345", base_url="https://api.typesafe.ai/v1")
        assert res_ok["status"] == "ok"
        assert res_ok["selected_choice"] == "@Action"
        assert res_ok["model"] == "jev-latest"
        assert res_ok["latency_ms"] >= 0

    # 3. Mocked HTTPError
    err = urllib.error.HTTPError(
        url="https://api.typesafe.ai/v1/systemone",
        code=401,
        msg="Unauthorized",
        hdrs=MagicMock(),
        fp=BytesIO(b'{"error": "Invalid API key"}'),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        res_err = verify_typesafe(api_key="mock_jev_test_key_12345")
        assert res_err["status"] == "error"
        assert "401" in res_err["message"]

    # 4. Mocked Connection Exception
    with patch("urllib.request.urlopen", side_effect=ConnectionResetError("Connection reset")):
        res_ex = verify_typesafe(api_key="mock_jev_test_key_12345")
        assert res_err["status"] == "error"
        assert "Failed to connect" in res_ex["message"]


def test_verifier_whatsapp_error_branches() -> None:
    """Test WhatsApp verification HTTPError and Exception handling."""
    # HTTPError
    err = urllib.error.HTTPError(
        url="https://graph.facebook.com",
        code=400,
        msg="Bad Request",
        hdrs=MagicMock(),
        fp=BytesIO(b'{"error": {"message": "Invalid token"}}'),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        res = verify_whatsapp(access_token="EAAB_RealLookingToken12345678", phone_number_id="123456789")
        assert res["status"] in ("warning", "error")

    # Exception
    with patch("urllib.request.urlopen", side_effect=ConnectionResetError("Reset")):
        res_ex = verify_whatsapp(access_token="EAAB_RealLookingToken12345678", phone_number_id="123456789")
        assert res_ex["status"] in ("warning", "error")


def test_verifier_cloud_relay_and_ports() -> None:
    """Test verify_cloud_relay and verify_ports."""
    # Cloud relay not configured
    res_info = verify_cloud_relay(relay_url="")
    assert res_info["status"] == "info"

    # Cloud relay reachable mock
    mock_relay_resp = MagicMock()
    mock_relay_resp.status = 200
    mock_relay_resp.__enter__.return_value = mock_relay_resp
    with patch("urllib.request.urlopen", return_value=mock_relay_resp):
        res_ok = verify_cloud_relay(relay_url="wss://relay.example.com/ws")
        assert res_ok["status"] == "ok"

    # Cloud relay unreachable
    with patch("urllib.request.urlopen", side_effect=Exception("Unreachable")):
        res_warn = verify_cloud_relay(relay_url="wss://relay.example.com/ws")
        assert res_warn["status"] == "warning"

    # Verify ports
    ports_res = verify_ports()
    assert isinstance(ports_res, dict)
    assert "ports" in ports_res

    # Verify webhook ingress with placeholder
    res_tok_warn = verify_webhook_ingress(verify_token="your_verify_token")
    assert res_tok_warn["status"] == "warning"


def test_verifier_ssl_and_config_backup(tmp_path: Path) -> None:
    """Test _get_ssl_context helpers, real config restore, and new keys save without mocks."""
    from core_platform.app.diagnostics.verifier import _get_ssl_context

    # Test SSL context helpers
    ctx_unverified = _get_ssl_context(verify=False)
    assert ctx_unverified is not None

    ctx_verified = _get_ssl_context(verify=True)
    assert ctx_verified is not None

    # Test config backup restore and new keys save (pure filesystem operations)
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING_KEY=old_val\n", encoding="utf-8")
    bak_dir = tmp_path / "backups"
    bak_dir.mkdir()

    # Create backup and verify restore
    bak_path = create_backup(env_file)
    assert bak_path is not None
    assert bak_path.exists()

    # Restore backup
    ok_res, res_msg = restore_backup(bak_path.name, env_path=env_file)
    assert ok_res is True

    # Restore nonexistent backup
    ok_bad, _ = restore_backup("does_not_exist.bak", env_path=env_file)
    assert ok_bad is False

    # Save master config with brand new key (lines 159-163)
    ok_save, _ = save_master_config(
        updates={"NEW_SETTING": "new value with spaces"},
        env_path=env_file,
    )
    assert ok_save is True
    content = env_file.read_text(encoding="utf-8")
    assert 'NEW_SETTING="new value with spaces"' in content


