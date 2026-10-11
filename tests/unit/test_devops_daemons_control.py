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

"""Unit tests for DevOps Host Daemon & Background Poller Supervision Controls."""

import pytest
from fastapi.testclient import TestClient

from apps.mail_organizer.services.poller_manager import MailPollerManager
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.main import app


@pytest.fixture
def devops_client() -> TestClient:
    """Return a TestClient authenticated as DevOps super-admin."""
    c = TestClient(app, follow_redirects=False)
    token = create_jwt_token(
        principal_id="devops_admin",
        roles=["devops_admin", "super_admin"],
        permitted_apps=["all"],
        tenant_id="platform",
    )
    c.cookies.set("admin_token", token)
    c.cookies.set("csrf_token", "csrf_test_token_12345")
    return c


@pytest.fixture
def customer_client() -> TestClient:
    """Return a TestClient authenticated as customer workspace admin."""
    c = TestClient(app, follow_redirects=False)
    token = create_jwt_token(
        principal_id="acme_admin",
        roles=["admin"],
        permitted_apps=["mail_organizer"],
        tenant_id="acme_corp",
    )
    c.cookies.set("admin_token", token)
    c.cookies.set("csrf_token", "csrf_test_token_12345")
    return c


def test_devops_daemons_access_control(devops_client: TestClient, customer_client: TestClient) -> None:
    """DevOps can view daemon controls while customer admins are blocked with 403."""
    # Customer admin must be blocked
    resp_cust = customer_client.get("/ops/daemons")
    assert resp_cust.status_code == 403

    # DevOps super-admin must be allowed
    resp_devops = devops_client.get("/ops/daemons")
    assert resp_devops.status_code == 200
    assert "Host-Level Background Daemons" in resp_devops.text or "Daemons" in resp_devops.text
    assert "AI Email Background Poller Daemon" in resp_devops.text or "Poller" in resp_devops.text


def test_email_poller_start_stop_lifecycle(devops_client: TestClient) -> None:
    """DevOps endpoints can cleanly start, stop, and toggle the background poller daemon."""
    mgr = MailPollerManager.get_instance()
    mgr.stop()
    assert mgr.is_running() is False

    # 1. Start daemon
    resp_start = devops_client.post(
        "/ops/daemons/email-poller/start",
        data={"csrf_token": "csrf_test_token_12345"},
    )
    assert resp_start.status_code == 303
    assert mgr.is_running() is True

    # 2. Stop daemon
    resp_stop = devops_client.post(
        "/ops/daemons/email-poller/stop",
        data={"csrf_token": "csrf_test_token_12345"},
    )
    assert resp_stop.status_code == 303
    assert mgr.is_running() is False

    # 3. Toggle daemon (start)
    resp_toggle1 = devops_client.post(
        "/ops/daemons/email-poller/toggle",
        data={"csrf_token": "csrf_test_token_12345"},
    )
    assert resp_toggle1.status_code == 303
    assert mgr.is_running() is True

    # 4. Toggle daemon (stop)
    resp_toggle2 = devops_client.post(
        "/ops/daemons/email-poller/toggle",
        data={"csrf_token": "csrf_test_token_12345"},
    )
    assert resp_toggle2.status_code == 303
    assert mgr.is_running() is False

    # 5. Invalid CSRF is rejected
    resp_bad_csrf = devops_client.post(
        "/ops/daemons/email-poller/start",
        data={"csrf_token": "invalid_csrf"},
    )
    assert resp_bad_csrf.status_code == 303
    assert "error" in resp_bad_csrf.headers["location"]
