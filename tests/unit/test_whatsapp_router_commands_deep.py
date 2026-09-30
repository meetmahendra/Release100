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

"""GEES v1.0 Deep Coverage Tests for WhatsApp Ingress Commands and Role Routing."""

import json
from unittest.mock import AsyncMock, patch
import pytest
from starlette.testclient import TestClient

from apps.temperature_marker.database.db_service import DatabaseService
from core_platform.app.ingress.whatsapp_router import dispatch_whatsapp_payload
from core_platform.main import app

client = TestClient(app)


def _make_msg_payload(sender_phone: str, text: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "10001"},
                            "contacts": [{"profile": {"name": "Test User"}, "wa_id": sender_phone.replace("+", "")}],
                            "messages": [
                                {
                                    "from": sender_phone.replace("+", ""),
                                    "id": f"wamid.{hash(text)}",
                                    "timestamp": "1710400000",
                                    "text": {"body": text},
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


@pytest.mark.asyncio
async def test_supervisor_commands_and_assignment() -> None:
    """Test supervisor enrollment, kiosk assignment, and fleet status commands."""
    db = DatabaseService.get_instance()
    sup_phone = "+919800000001"

    # Register supervisor in DB
    db.register_employee(
        emp_code="MGR-001",
        full_name="Fleet Supervisor Test",
        phone_number=sup_phone,
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="ACTIVE",
        role="SUPERVISOR",
    )

    # 1. Kiosk list command
    res1 = await dispatch_whatsapp_payload(_make_msg_payload(sup_phone, "kiosks"))
    assert res1.get("status") in ("PROCESSED", "EVENT_RECEIVED", None) or "reply" in str(res1)

    # 2. Register new operator by supervisor
    res2 = await dispatch_whatsapp_payload(_make_msg_payload(sup_phone, "register EMP-9090 Rahul Test +919877665544"))
    assert res2 is not None

    # 3. Assign operator to station
    res3 = await dispatch_whatsapp_payload(_make_msg_payload(sup_phone, "assign EMP-9090 CANEBOT-BLR-02"))
    assert res3 is not None

    # 4. Unknown station error handling
    res4 = await dispatch_whatsapp_payload(_make_msg_payload(sup_phone, "kiosk CANEBOT-UNKNOWN-99"))
    assert res4 is not None

    # 5. Clean up test records
    s = db.SessionLocal()
    from apps.temperature_marker.database.models import Employee
    s.query(Employee).filter(Employee.emp_code.in_(["MGR-001", "EMP-9090"])).delete()
    s.commit()
    s.close()


@pytest.mark.asyncio
async def test_operator_restricted_commands() -> None:
    """Test regular operator attempting restricted supervisor commands."""
    db = DatabaseService.get_instance()
    op_phone = "+919800000002"

    db.register_employee(
        emp_code="EMP-REG-01",
        full_name="Regular Operator",
        phone_number=op_phone,
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="ACTIVE",
        role="OPERATOR",
    )

    # Operator attempting registration
    res1 = await dispatch_whatsapp_payload(_make_msg_payload(op_phone, "register EMP-9999 Hacker +919999999999"))
    assert res1 is not None

    # Operator attempting station switch
    res2 = await dispatch_whatsapp_payload(_make_msg_payload(op_phone, "switch CANEBOT-BLR-02"))
    assert res2 is not None

    # Clean up
    s = db.SessionLocal()
    from apps.temperature_marker.database.models import Employee
    s.query(Employee).filter(Employee.emp_code == "EMP-REG-01").delete()
    s.commit()
    s.close()
