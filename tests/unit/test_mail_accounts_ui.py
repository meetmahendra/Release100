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
Actionable DOM Invariant & Clean-Slate Round-Trip Mutation tests for Mail Accounts UI.

Adheres strictly to GEES v3.1:
- Rule 4.1: Ban on Shallow Status 200 Tests (Asserts Actionable DOM Invariants)
- Rule 4.2: Mandatory Clean-Slate Round-Trip Mutation Testing (Day-1 Invariant)
- Rule 3.1: 100% strict typing
"""

from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.database.models import Base
from apps.mail_organizer.ui import routes as mail_routes
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.main import app


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Authenticated TestClient for tenant admin with hermetic database."""
    db_file = tmp_path / "accounts_ui_test.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    MailDatabaseService._instance = None
    db_service = MailDatabaseService.get_instance(engine=engine)
    mail_routes._db_service = db_service

    c = TestClient(app)
    token = create_jwt_token("admin", ["admin", "tenant_admin"], ["all", "mail_organizer"], tenant_id="default")
    c.cookies.set("admin_token", token)
    try:
        yield c
    finally:
        db_service.close()
        MailDatabaseService._instance = None


def test_accounts_actionable_dom_invariants(client: TestClient) -> None:
    """GET /accounts must render all required Actionable DOM Invariants."""
    res = client.get("/admin/apps/mail-organizer/accounts")
    assert res.status_code == 200
    html = res.text

    # 1. Actionable DOM Invariants: Workspace Master Poller Form & Button
    assert '<form method="post" action="/admin/apps/mail-organizer/accounts/workspace/toggle">' in html
    assert 'id="btn-toggle-workspace"' in html

    # 2. Actionable DOM Invariants: Workspace Default Settings Form & Input
    assert '<form method="post" action="/admin/apps/mail-organizer/accounts/settings"' in html
    assert 'name="sync_interval"' in html

    # 3. Actionable DOM Invariants: Personal Google Account Reauth Link
    assert 'href="/admin/apps/mail-organizer/accounts/reauth"' in html

    # 4. Actionable DOM Invariants: Descriptive Headers & Badges
    assert "Workspace Poller Master State" in html
    assert "Google Account" in html
    assert "Connection Status" in html


def test_clean_slate_round_trip_workspace_mutation(client: TestClient) -> None:
    """Day-1 Round-Trip Mutation Test for Workspace Master Poller: GET -> POST (Pause) -> GET -> POST (Resume) -> GET."""
    # Step 1: GET (Day-1 Default State)
    get_day1 = client.get("/admin/apps/mail-organizer/accounts")
    assert get_day1.status_code == 200
    assert "ACTIVE" in get_day1.text
    assert "Pause All Polling" in get_day1.text

    # Step 2: POST (Mutate: Pause Workspace)
    post_pause = client.post(
        "/admin/apps/mail-organizer/accounts/workspace/toggle",
        follow_redirects=False,
    )
    assert post_pause.status_code in (302, 303)
    assert "workspace_paused" in post_pause.headers["location"]

    # Step 3: GET (Verify Persisted Mutated State)
    get_paused = client.get("/admin/apps/mail-organizer/accounts")
    assert get_paused.status_code == 200
    assert "PAUSED" in get_paused.text
    assert "Resume All Polling" in get_paused.text

    # Step 4: POST (Mutate: Resume Workspace)
    post_resume = client.post(
        "/admin/apps/mail-organizer/accounts/workspace/toggle",
        follow_redirects=False,
    )
    assert post_resume.status_code in (302, 303)
    assert "workspace_resumed" in post_resume.headers["location"]

    # Step 5: GET (Verify Restored Active State)
    get_active = client.get("/admin/apps/mail-organizer/accounts")
    assert get_active.status_code == 200
    assert "ACTIVE" in get_active.text
    assert "Pause All Polling" in get_active.text


def test_clean_slate_round_trip_user_poller_mutation(client: TestClient) -> None:
    """Round-trip mutation test for per-user poller configuration and manual trigger."""
    mock_user = MagicMock()
    mock_user.id = 99
    mock_user.full_name = "Mahendra Gurav"
    mock_user.email = "mahendra@test.local"
    mock_user.phone_number = "+919800000001"
    mock_user.role = "USER"
    mock_user.status = "ACTIVE"
    mock_user.allowed_cartridges = ["mail_organizer"]
    mock_user.encrypted_oauth_tokens = "synthetic_tok"
    mock_user.tenant_id = "default"

    # Guarantee clean-slate initial state on the route's active database instance
    from apps.mail_organizer.ui.routes import _db_service as db
    db.set_workspace_poller_status(is_enabled=True, tenant_id="default")
    db.upsert_user_poller_config(user_id=99, email="mahendra@apex.local", is_enabled=True, tenant_id="default")

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis:
        mock_uis_inst = MagicMock()
        mock_uis_inst.list_users.return_value = [mock_user]
        mock_uis_inst.get_user_by_id.return_value = mock_user
        mock_uis.return_value = mock_uis_inst

        # 1. GET page with user present
        res_users = client.get("/admin/apps/mail-organizer/accounts")
        assert res_users.status_code == 200
        assert "Mahendra Gurav" in res_users.text
        assert 'action="/admin/apps/mail-organizer/accounts/users/99/config"' in res_users.text
        assert 'action="/admin/apps/mail-organizer/accounts/users/99/toggle"' in res_users.text
        assert 'action="/admin/apps/mail-organizer/accounts/users/99/poll-now"' in res_users.text

        # 2. Mutate: Update cadence config (15 min / 900s, work hours)
        post_cfg = client.post(
            "/admin/apps/mail-organizer/accounts/users/99/config",
            data={"poll_interval_seconds": "900", "active_window": "09:00-18:00"},
            follow_redirects=False,
        )
        assert post_cfg.status_code in (302, 303)

        # 3. Mutate: Pause user
        post_toggle = client.post(
            "/admin/apps/mail-organizer/accounts/users/99/toggle",
            follow_redirects=False,
        )
        assert post_toggle.status_code in (302, 303)

        # 4. Verify persisted state
        res_mutated = client.get("/admin/apps/mail-organizer/accounts")
        assert res_mutated.status_code == 200
        assert "PAUSED" in res_mutated.text

        # 5. On-Demand Manual Poll Now
        with patch("apps.mail_organizer.services.poller_manager.MailPollerManager.poll_user_now", new_callable=AsyncMock) as mock_poll:
            mock_poll.return_value = {"success": True, "emails_processed": 2}
            post_poll = client.post(
                "/admin/apps/mail-organizer/accounts/users/99/poll-now",
                headers={"Accept": "application/json"},
            )
            assert post_poll.status_code == 200
            assert post_poll.json()["success"] is True
            assert post_poll.json()["emails_processed"] == 2


def test_workspace_settings_sync_interval_mutation(client: TestClient) -> None:
    """POST /accounts/settings updates default sync interval."""
    res_post = client.post(
        "/admin/apps/mail-organizer/accounts/settings",
        data={"sync_interval": "600"},
        follow_redirects=False,
    )
    assert res_post.status_code in (302, 303)

    res_get = client.get("/admin/apps/mail-organizer/accounts")
    assert res_get.status_code == 200
    assert 'value="600"' in res_get.text
