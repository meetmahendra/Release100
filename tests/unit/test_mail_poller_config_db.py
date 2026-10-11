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
Unit tests for Customer Admin Mail Poller database models and service methods.

Verifies:
- Clean-slate bootstrapping (tables created dynamically)
- Workspace master poller default and toggle mutations
- Per-user poller configuration upsert, retrieve, and list
- Telemetry recording (last_polled_at, total_cycles, total_emails_fetched)
- Strict multi-tenant isolation (Tenant A config does not bleed into Tenant B)
- Email deduplication lookup helper (get_email)
"""

from typing import Generator
import pytest
from sqlalchemy import create_engine

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.database.models import Base


@pytest.fixture
def db_service() -> Generator[MailDatabaseService, None, None]:
    """Provide an isolated in-memory MailDatabaseService instance for each test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    service = MailDatabaseService(engine=engine)
    yield service
    service.close()


def test_clean_slate_workspace_poller_default(db_service: MailDatabaseService) -> None:
    """A new tenant on Day 1 initializes with active master poller and default 300s cadence."""
    config = db_service.get_workspace_poller_config(tenant_id="tenant_alpha")
    assert config is not None
    assert config.tenant_id == "tenant_alpha"
    assert config.is_master_enabled is True
    assert config.default_poll_interval_seconds == 300


def test_workspace_poller_toggle_mutation(db_service: MailDatabaseService) -> None:
    """Customer admin can pause and resume workspace-level polling."""
    # Day 1: default active
    cfg1 = db_service.get_workspace_poller_config(tenant_id="tenant_beta")
    assert cfg1.is_master_enabled is True

    # Mutate: Pause master poller
    cfg_paused = db_service.set_workspace_poller_status(is_enabled=False, tenant_id="tenant_beta")
    assert cfg_paused.is_master_enabled is False

    # Verify persisted state
    cfg_verify = db_service.get_workspace_poller_config(tenant_id="tenant_beta")
    assert cfg_verify.is_master_enabled is False

    # Mutate: Resume master poller
    cfg_resumed = db_service.set_workspace_poller_status(is_enabled=True, tenant_id="tenant_beta")
    assert cfg_resumed.is_master_enabled is True


def test_user_poller_config_lifecycle(db_service: MailDatabaseService) -> None:
    """Customer admin can configure, update, and track per-user poller settings."""
    tenant = "gurav_family"

    # 1. Non-existent user returns None
    assert db_service.get_user_poller_config(user_id=101, tenant_id=tenant) is None

    # 2. Upsert high-criticality user (5 min, 24x7)
    u_mahendra = db_service.upsert_user_poller_config(
        user_id=101,
        email="mahendra@gurav.com",
        is_enabled=True,
        poll_interval_seconds=300,
        active_window="24x7",
        tenant_id=tenant,
    )
    assert u_mahendra.user_id == 101
    assert u_mahendra.email == "mahendra@gurav.com"
    assert u_mahendra.poll_interval_seconds == 300
    assert u_mahendra.active_window == "24x7"
    assert u_mahendra.is_poller_enabled is True
    assert u_mahendra.last_polled_at is None
    assert u_mahendra.total_cycles == 0

    # 3. Upsert standard-criticality user (30 min, working hours)
    u_aarya = db_service.upsert_user_poller_config(
        user_id=102,
        email="aarya@gurav.com",
        is_enabled=True,
        poll_interval_seconds=1800,
        active_window="09:00-18:00",
        tenant_id=tenant,
    )
    assert u_aarya.poll_interval_seconds == 1800
    assert u_aarya.active_window == "09:00-18:00"

    # 4. List configs for tenant
    configs = db_service.list_user_poller_configs(tenant_id=tenant)
    assert len(configs) == 2
    user_ids = {c.user_id for c in configs}
    assert user_ids == {101, 102}

    # 5. Record poll run telemetry
    recorded = db_service.record_user_poll_run(
        user_id=101,
        emails_fetched=3,
        tenant_id=tenant,
    )
    assert recorded is not None
    assert recorded.last_polled_at is not None
    assert recorded.total_cycles == 1
    assert recorded.total_emails_fetched == 3
    assert recorded.last_error is None

    # 6. Mutate: Pause user polling
    u_paused = db_service.upsert_user_poller_config(
        user_id=102,
        email="aarya@gurav.com",
        is_enabled=False,
        poll_interval_seconds=1800,
        active_window="09:00-18:00",
        tenant_id=tenant,
    )
    assert u_paused.is_poller_enabled is False

    # 7. Verify persisted state
    fetched_aarya = db_service.get_user_poller_config(user_id=102, tenant_id=tenant)
    assert fetched_aarya is not None
    assert fetched_aarya.is_poller_enabled is False


def test_tenant_data_isolation(db_service: MailDatabaseService) -> None:
    """Poller configurations for Tenant Alpha must NEVER bleed into Tenant Beta."""
    # Tenant Alpha configuration
    db_service.set_workspace_poller_status(is_enabled=False, tenant_id="tenant_alpha")
    db_service.upsert_user_poller_config(
        user_id=1,
        email="alpha_user@alpha.com",
        is_enabled=True,
        poll_interval_seconds=600,
        tenant_id="tenant_alpha",
    )

    # Tenant Beta configuration
    db_service.set_workspace_poller_status(is_enabled=True, tenant_id="tenant_beta")
    db_service.upsert_user_poller_config(
        user_id=2,
        email="beta_user@beta.com",
        is_enabled=True,
        poll_interval_seconds=120,
        tenant_id="tenant_beta",
    )

    # Assertions for Tenant Alpha
    alpha_master = db_service.get_workspace_poller_config(tenant_id="tenant_alpha")
    assert alpha_master.is_master_enabled is False
    alpha_users = db_service.list_user_poller_configs(tenant_id="tenant_alpha")
    assert len(alpha_users) == 1
    assert alpha_users[0].email == "alpha_user@alpha.com"
    assert db_service.get_user_poller_config(user_id=2, tenant_id="tenant_alpha") is None

    # Assertions for Tenant Beta
    beta_master = db_service.get_workspace_poller_config(tenant_id="tenant_beta")
    assert beta_master.is_master_enabled is True
    beta_users = db_service.list_user_poller_configs(tenant_id="tenant_beta")
    assert len(beta_users) == 1
    assert beta_users[0].email == "beta_user@beta.com"
    assert db_service.get_user_poller_config(user_id=1, tenant_id="tenant_beta") is None


def test_get_email_deduplication_helper(db_service: MailDatabaseService) -> None:
    """get_email correctly returns existing record for deduplication checks."""
    assert db_service.get_email(gmail_id="msg_nonexistent", tenant_id="tenant_alpha") is None

    # Store email
    db_service.store_email(
        gmail_id="msg_test_001",
        thread_id="thread_001",
        subject="Project Alpha Launch",
        sender="alice@company.com",
        tenant_id="tenant_alpha",
    )

    # Query within tenant
    rec = db_service.get_email(gmail_id="msg_test_001", tenant_id="tenant_alpha")
    assert rec is not None
    assert rec.gmail_id == "msg_test_001"
    assert rec.subject == "Project Alpha Launch"

    # Query from another tenant should return None
    assert db_service.get_email(gmail_id="msg_test_001", tenant_id="tenant_beta") is None
