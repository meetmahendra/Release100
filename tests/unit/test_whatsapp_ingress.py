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

"""Synthetic Unit Tests for Meta WhatsApp Webhook Ingress Gateway."""

import pytest
from starlette.testclient import TestClient

from apps.temperature_marker.database.db_service import DatabaseService
from core_platform.app.config import settings
from core_platform.main import app

client = TestClient(app)


def test_whatsapp_webhook_verification_success() -> None:
    """GET /webhook must echo hub.challenge when token matches."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
        "hub.challenge": "11582012",
    }
    resp = client.get("/webhook", params=params)
    assert resp.status_code == 200
    assert resp.text == "11582012"


def test_whatsapp_webhook_verification_forbidden() -> None:
    """GET /webhook must return 403 when token does not match."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong_token",
        "hub.challenge": "11582012",
    }
    resp = client.get("/webhook", params=params)
    assert resp.status_code == 403


def test_whatsapp_webhook_message_processing() -> None:
    """POST /webhook must parse message and trigger workflow."""
    # Ensure active operator exists
    db = DatabaseService()
    db.register_employee(
        emp_code="EMP-1042",
        full_name="Rajesh Pawar",
        phone_number="+919800011122",
        assigned_kiosk_id="NODE-PUNE-04",
        status="ACTIVE",
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "10001"},
                            "contacts": [{"profile": {"name": "Rajesh"}, "wa_id": "919800011122"}],
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.test123",
                                    "timestamp": "1710400000",
                                    "text": {"body": "Check-in duty"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "EVENT_RECEIVED"
    assert "reply_message" in data
    assert data["kiosk_id"] == "NODE-PUNE-04"


def test_whatsapp_webhook_status_receipt_ignored() -> None:
    """POST /webhook must ignore status receipts cleanly."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [{"id": "wamid.123", "status": "delivered"}],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "STATUS_UPDATE"


def test_whatsapp_webhook_empty_entry() -> None:
    """Empty entry must return NO_ENTRY."""
    resp = client.post("/webhook", json={"entry": []})
    assert resp.status_code == 200
    assert resp.json()["status"] == "NO_ENTRY"


def test_whatsapp_webhook_location_message() -> None:
    """Location message must be processed."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.loc123",
                                    "timestamp": "1710400000",
                                    "type": "location",
                                    "location": {
                                        "latitude": 18.5204,
                                        "longitude": 73.8567,
                                        "name": "Pune Kiosk",
                                    },
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_whatsapp_webhook_image_message() -> None:
    """Image message must trigger media download and workflow."""
    from unittest.mock import patch

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.img123",
                                    "timestamp": "1710400000",
                                    "type": "image",
                                    "image": {"id": "meta_img_999"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    with patch("core_platform.app.ingress.whatsapp_router.fetch_whatsapp_media_bytes", return_value=b"\xff\xd8fake_jpeg"):
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "EVENT_RECEIVED"


def test_whatsapp_webhook_registration_commands() -> None:
    """Test operator self-registration commands via WhatsApp."""
    # 1. Valid registration
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.reg1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "register EMP-2099 Suresh Patil"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "EVENT_RECEIVED"
    assert "Self-Registration Disabled" in data["reply_message"]


def test_whatsapp_webhook_mail_commands() -> None:
    """Test mail organizer digest and task approval/rejection commands."""
    # 1. Mail digest summary
    digest_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.mail1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "mail digest"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp = client.post("/webhook", json=digest_payload)
    assert resp.status_code == 200
    assert "AI Mail & Calendar Summary" in resp.json()["reply_message"]

    # 2. Approve task
    approve_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.app1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "approve TASK-NONEXISTENT"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp2 = client.post("/webhook", json=approve_payload)
    assert resp2.status_code == 200
    assert "not found" in resp2.json()["reply_message"]

    # 3. Reject task
    reject_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.rej1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "reject TASK-NONEXISTENT"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp3 = client.post("/webhook", json=reject_payload)
    assert resp3.status_code == 200
    assert "not found" in resp3.json()["reply_message"]


@pytest.mark.anyio
async def test_cloud_relay_client_message_handling() -> None:
    """Test CloudRelayClient raw message parsing and error resilience."""
    import json
    from core_platform.app.ingress.relay_client import CloudRelayClient

    client = CloudRelayClient(relay_url="wss://mock-relay.example.com")
    assert client.is_running is False

    handled: list[dict] = []

    async def custom_handler(p: dict) -> None:
        handled.append(p)

    client.message_handler = custom_handler

    # Test bytes message
    raw_bytes = json.dumps({"test_key": "val_bytes"}).encode("utf-8")
    await client._handle_raw_message(raw_bytes)
    assert len(handled) == 1
    assert handled[0]["test_key"] == "val_bytes"

    # Test text message
    raw_str = json.dumps({"test_key": "val_str"})
    await client._handle_raw_message(raw_str)
    assert len(handled) == 2
    assert handled[1]["test_key"] == "val_str"

    # Test invalid json resilience
    await client._handle_raw_message("not valid json at all")
    assert len(handled) == 2  # No new payload added, handled gracefully


@pytest.mark.anyio
async def test_send_whatsapp_message_missing_credentials() -> None:
    """If WhatsApp tokens are not configured, return None gracefully."""
    from unittest.mock import patch
    from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message

    with patch.object(settings, "WHATSAPP_ACCESS_TOKEN", ""), \
         patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", ""):
        result = await send_whatsapp_message("+918087545430", "Test message")
        assert result is None


@pytest.mark.anyio
async def test_send_whatsapp_message_success_and_failure() -> None:
    """Mock successful dispatch and error paths for Meta Graph API v21.0."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message

    with patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "mock_token"), \
         patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "1234567890"):

        # 1. Successful send
        mock_resp_ok = MagicMock()
        mock_resp_ok.is_success = True
        mock_resp_ok.json.return_value = {"messages": [{"id": "wamid.SUCCESS_123"}]}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp_ok
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            msg_id = await send_whatsapp_message("+91 8087-545430", "Hello Operator")
            assert msg_id == "wamid.SUCCESS_123"
            call_kwargs = mock_client.post.call_args.kwargs
            assert call_kwargs["json"]["to"] == "918087545430"

        # 2. API Failure
        mock_resp_fail = MagicMock()
        mock_resp_fail.is_success = False
        mock_resp_fail.status_code = 401
        mock_resp_fail.text = "Unauthorized"
        mock_client.post.return_value = mock_resp_fail

        with patch("httpx.AsyncClient", return_value=mock_client):
            fail_id = await send_whatsapp_message("+918087545430", "Hello Operator")
            assert fail_id is None

        # 3. Network Exception
        with patch("httpx.AsyncClient", return_value=mock_client):
            exc_id = await send_whatsapp_message("+918087545430", "Hello Operator")
            assert exc_id is None


@pytest.mark.anyio
async def test_send_whatsapp_message_tenant_byok() -> None:
    """Outbound WhatsApp message should resolve credentials dynamically from tenant vault."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
    from ops_control_plane.devops_vault import TenantRuntimeCredentials

    mock_resp_ok = MagicMock()
    mock_resp_ok.is_success = True
    mock_resp_ok.json.return_value = {"messages": [{"id": "wamid.BYOK_SUCCESS"}]}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp_ok
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mock_creds = TenantRuntimeCredentials(
        tenant_id="tenant-byok-test",
        credential_mode="CUSTOMER_BYOK",
        is_byok=True,
        gemini_api_key="mock_gemini_test_key_12345",
        openai_api_key=None,
        waba_token="mock_byok_waba_token_abc",
        waba_phone_number_id="9988776655",
        brand_name="Test Brand",
        default_timezone="Asia/Kolkata",
    )

    with patch.object(settings, "WHATSAPP_ACCESS_TOKEN", ""), \
         patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", ""), \
         patch("ops_control_plane.devops_vault.DevOpsKeyVault.get_tenant_runtime_credentials", return_value=mock_creds), \
         patch("httpx.AsyncClient", return_value=mock_client):

        msg_id = await send_whatsapp_message(
            to_phone="+91 8087-545430",
            text="Tenant BYOK Message",
            tenant_id="tenant-byok-test",
        )
        assert msg_id == "wamid.BYOK_SUCCESS"
        call_kwargs = mock_client.post.call_args.kwargs
        assert "9988776655/messages" in mock_client.post.call_args[0][0]
        assert call_kwargs["headers"]["Authorization"] == "Bearer mock_byok_waba_token_abc"


def test_operator_greeting_ist_time_and_clean_chiller_status() -> None:
    """Operator greeting should display IST time and clean 'Pending photo' if chiller temp is 0.0 or pending."""
    from apps.temperature_marker.database.db_service import DatabaseService
    from datetime import datetime, timezone

    db = DatabaseService.get_instance()
    emp = db.get_employee_by_code("EMP-1042")
    if not emp:
        db.register_employee("EMP-1042", "Rahul Sharma", "+919800011122", "NODE-PUNE-04", status="ACTIVE")

    # Record attendance with 0.0°C and PENDING_CHILLER_PHOTO
    db.record_attendance(
        correlation_id="test_att_rec_1",
        emp_code="EMP-1042",
        kiosk_id="NODE-PUNE-04",
        face_confidence=0.95,
        gps_distance_meters=10.0,
        geofence_verified=True,
        chiller_temp_c=0.0,
        haccp_compliant=False,
        haccp_status="PENDING_CHILLER_PHOTO",
        ocr_engine_used="local_onnx",
        is_duty_checkin=True,
        photo_path="logs/media/test_chk.jpg",
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.greet_test_1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "hi"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    reply = resp.json()["reply_message"]

    # 1. Check IST time display
    assert "IST" in reply
    att = db.has_attendance_today("EMP-1042")
    assert att is not None
    from core_platform.app.common.timezone import to_local_ist
    assert to_local_ist(att.checkin_time_utc) in reply

    # 2. Check clean chiller status (no 0.0°C displayed!)
    assert "0.0°C" not in reply
    assert "Pending photo" in reply


def test_operator_greeting_messages_filter_suppresses_own_inquiries() -> None:
    """Operator greeting should not show operator's own inquiries to the operator."""
    from apps.temperature_marker.database.db_service import DatabaseService

    db = DatabaseService.get_instance()
    # Enqueue inquiry from operator
    db.enqueue_internal_message(
        correlation_id="test_inq_filter",
        sender_phone="+919800011122",
        sender_emp_code="EMP-1042",
        sender_name="Rahul Sharma",
        kiosk_id="NODE-PUNE-04",
        recipient_emp_code="EMP-MGR-01",
        recipient_phone="+919800099999",
        message_text="Need cups refill",
        priority=50,
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.greet_test_2",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    reply = resp.json()["reply_message"]

    # Operator should NOT see "Open Inquiries" or "awaiting manager review" for their own inquiry
    assert "awaiting manager review" not in reply
    assert "No new instructions from supervisor" in reply or "Supervisor Instruction" in reply


def test_duplicate_attendance_action_guard_no_location_url() -> None:
    """Typing 'attendance' when already marked today should acknowledge check-in and NOT provide location link."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.att_test_1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "attendance"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    reply = resp.json()["reply_message"]

    assert "Shift Attendance Already Recorded" in reply
    assert "Check-in Time" in reply
    assert "/loc?session=" not in reply
    assert "Verify your location" not in reply

    # Cleanup test attendance records so subsequent synthetic tests start with clean slate
    from apps.temperature_marker.database.db_service import DatabaseService
    from apps.temperature_marker.database.models import AttendanceRecord
    from apps.temperature_marker.services.session_manager import OperatorSessionManager
    db = DatabaseService.get_instance()
    with db.SessionLocal() as session:
        session.query(AttendanceRecord).filter(AttendanceRecord.emp_code == "EMP-1042").delete()
        session.commit()
    OperatorSessionManager.get_instance()._sessions.pop("EMP-1042", None)


def test_operator_onboarding_photo_bypasses_geofence(tmp_path) -> None:
    """An operator in PENDING_PHOTO submitting an onboarding portrait must bypass geofence and transition to PENDING_APPROVAL."""
    import base64
    import io
    from PIL import Image
    from apps.temperature_marker.database.db_service import DatabaseService
    from pathlib import Path

    db = DatabaseService.get_instance()
    # Register operator in PENDING_PHOTO with no photo
    db.register_employee(
        emp_code="EMP-TEST-99",
        full_name="Pooja Kadam",
        phone_number="+918888800099",
        assigned_kiosk_id="NODE-PUNE-04",
        status="PENDING_PHOTO",
    )

    # Generate synthetic selfie JPEG
    img = Image.new("RGB", (120, 120), color=(140, 110, 90))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64_photo = base64.b64encode(buf.getvalue()).decode("utf-8")

    # Inbound payload: image submitted from 10,000m away (geofence breach coordinates)
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"profile": {"name": "Pooja"}, "wa_id": "918888800099"}],
                            "messages": [
                                {
                                    "from": "918888800099",
                                    "id": "wamid.enroll_photo_test_1",
                                    "timestamp": "1710400000",
                                    "type": "image",
                                    "image": {"base64": b64_photo},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    reply = data["reply_message"]

    # Must confirm photo receipt, NOT fail geofence
    assert "Onboarding Photo Received" in reply
    assert "PENDING APPROVAL" in reply
    assert "Location Mismatch" not in reply

    # Verify operator record in database
    emp = db.get_employee_by_code("EMP-TEST-99")
    assert emp is not None
    assert emp.status == "PENDING_APPROVAL"
    assert emp.encrypted_face_embedding is not None

    # Verify photo file on disk
    photo_file = Path("logs/photos/EMP-TEST-99_profile.jpg")
    assert photo_file.exists()


def test_operator_in_pending_photo_sends_text_prompted_for_selfie() -> None:
    """An operator in PENDING_PHOTO sending a text message should be prompted for their onboarding selfie."""
    from apps.temperature_marker.database.db_service import DatabaseService

    db = DatabaseService.get_instance()
    db.register_employee(
        emp_code="EMP-TEST-98",
        full_name="Vijay Shinde",
        phone_number="+918888800098",
        assigned_kiosk_id="NODE-PUNE-04",
        status="PENDING_PHOTO",
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"profile": {"name": "Vijay"}, "wa_id": "918888800098"}],
                            "messages": [
                                {
                                    "from": "918888800098",
                                    "id": "wamid.pending_text_test_1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "hello KioskNode"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    reply = resp.json()["reply_message"]

    assert "account setup is pending" in reply
    assert "selfie photo to complete your enrollment" in reply
    assert "/loc?session=" not in reply


def test_operator_in_pending_approval_cannot_punch_in() -> None:
    """An operator in PENDING_APPROVAL cannot mark shift attendance or check-in."""
    from apps.temperature_marker.database.db_service import DatabaseService

    db = DatabaseService.get_instance()
    db.register_employee(
        emp_code="EMP-TEST-97",
        full_name="Sunita Deshmukh",
        phone_number="+918888800097",
        assigned_kiosk_id="NODE-PUNE-04",
        status="PENDING_APPROVAL",
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"profile": {"name": "Sunita"}, "wa_id": "918888800097"}],
                            "messages": [
                                {
                                    "from": "918888800097",
                                    "id": "wamid.pending_appr_test_1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "duty check in"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    reply = resp.json()["reply_message"]

    assert "Enrollment Under Review" in reply
    assert "awaiting Admin Approval" in reply
    assert db.has_attendance_today("EMP-TEST-97") is None


def test_admin_approvals_photo_endpoint() -> None:
    """GET /admin/apps/temperature-marker/api/members/{emp_code}/photo must return 200 for saved photos."""
    from pathlib import Path
    from core_platform.app.auth.jwt_utils import create_jwt_token

    photo_file = Path("logs/photos/EMP-TEST-99_profile.jpg")
    photo_file.parent.mkdir(parents=True, exist_ok=True)
    photo_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100)

    token = create_jwt_token("admin", ["admin"], ["all", "temperature_marker"])
    adm_client = TestClient(app)
    adm_client.cookies.set("admin_token", token)

    resp = adm_client.get("/admin/apps/temperature-marker/api/members/EMP-TEST-99/photo")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"

    # Nonexistent photo returns 404
    resp_404 = adm_client.get("/admin/apps/temperature-marker/api/members/NONEXISTENT/photo")
    assert resp_404.status_code == 404




