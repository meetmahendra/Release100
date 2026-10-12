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
Unit Test Suite for Microkernel Substrate Gatekeeper & IETF Token Engine.

Asserts GEES v3.1 Plane 2 Invariants:
1. Ambient database read on tenant entity fails closed with TenantIsolationViolationError.
2. Injected AST criteria isolates queries strictly to current_tenant.
3. Ambient database write on tenant entity fails closed with TenantIsolationViolationError.
4. Cross-tenant database write fails closed with CrossTenantAccessViolationError.
5. NIST SP 800-63B §7.2: 1-hour sliding grace renewal and 7-day hard ceiling.
6. RFC 8693 Token Exchange & Assumed Identity execution.
"""

from pathlib import Path
import time
import pytest
from sqlalchemy import select
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, sessionmaker
from sqlalchemy import Integer, String

from core_platform.app.auth.session_vault import (
    ABSOLUTE_HARD_CAP_SECONDS,
    HardSessionExpiredError,
    SLIDING_IDLE_WINDOW_SECONDS,
    SessionVault,
    SlidingSessionExpiredError,
)
from core_platform.app.auth.token_exchange import (
    RFC8693TokenExchangeService,
    assumed_identity,
    sync_assumed_identity,
)
from core_platform.app.db.connection_factory import DatabaseConnectionFactory
from core_platform.app.db.gatekeeper import (
    CrossTenantAccessViolationError,
    TenantIsolationViolationError,
    system_context,
)
from core_platform.app.middleware.tenant_context import (
    sync_tenant_scope,
    tenant_scope,
    user_scope,
    UserContext,
)

Base = declarative_base()


class SampleTenantEntity(Base):
    __tablename__ = "sample_tenant_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(String(255), nullable=False)


@pytest.fixture
def gatekeeper_db(tmp_path: Path):
    """Provide isolated SQLite database with gatekeeper listeners attached."""
    db_file = tmp_path / "test_gatekeeper.db"
    db_url = f"sqlite:///{db_file}"

    factory = DatabaseConnectionFactory(db_url)
    Base.metadata.create_all(bind=factory.engine)

    # Seed initial rows under system context
    with system_context():
        with factory.session_factory() as session:
            session.add(SampleTenantEntity(tenant_id="tenant_alpha", payload="Alpha Secret 1"))
            session.add(SampleTenantEntity(tenant_id="tenant_alpha", payload="Alpha Secret 2"))
            session.add(SampleTenantEntity(tenant_id="tenant_beta", payload="Beta Secret 1"))
            session.commit()

    return factory


def test_ambient_read_fails_closed(gatekeeper_db: DatabaseConnectionFactory):
    """Ambient query without active tenant or security ticket must raise TenantIsolationViolationError."""
    with gatekeeper_db.session_factory() as session:
        with pytest.raises(TenantIsolationViolationError) as exc_info:
            session.scalars(select(SampleTenantEntity)).all()

        assert "Ambient query rejected" in str(exc_info.value)
        assert "SampleTenantEntity" in str(exc_info.value)


def test_ast_rewrite_isolates_tenant_queries(gatekeeper_db: DatabaseConnectionFactory):
    """Queries within tenant_scope must automatically inject AST criteria and see ONLY tenant rows."""
    with gatekeeper_db.session_factory() as session:
        # Tenant Alpha query
        with sync_tenant_scope("tenant_alpha"):
            alpha_records = session.scalars(select(SampleTenantEntity)).all()
            assert len(alpha_records) == 2
            assert all(r.tenant_id == "tenant_alpha" for r in alpha_records)

        # Tenant Beta query
        with sync_tenant_scope("tenant_beta"):
            beta_records = session.scalars(select(SampleTenantEntity)).all()
            assert len(beta_records) == 1
            assert beta_records[0].tenant_id == "tenant_beta"
            assert beta_records[0].payload == "Beta Secret 1"


def test_ambient_write_fails_closed(gatekeeper_db: DatabaseConnectionFactory):
    """Ambient write without tenant context must raise TenantIsolationViolationError."""
    with gatekeeper_db.session_factory() as session:
        new_record = SampleTenantEntity(tenant_id="tenant_alpha", payload="Unscoped Insertion")
        session.add(new_record)
        with pytest.raises(TenantIsolationViolationError) as exc_info:
            session.commit()

        assert "Ambient write rejected" in str(exc_info.value)


def test_cross_tenant_write_fails_closed(gatekeeper_db: DatabaseConnectionFactory):
    """Attempting to insert a row for tenant_beta while scoped to tenant_alpha must raise CrossTenantAccessViolationError."""
    with gatekeeper_db.session_factory() as session:
        with sync_tenant_scope("tenant_alpha"):
            tampered_record = SampleTenantEntity(tenant_id="tenant_beta", payload="Tampered Cross Tenant")
            session.add(tampered_record)
            with pytest.raises(CrossTenantAccessViolationError) as exc_info:
                session.commit()

            assert "Cross-tenant write rejected" in str(exc_info.value)
            assert "tenant_beta" in str(exc_info.value)
            assert "tenant_alpha" in str(exc_info.value)


def test_nist_session_sliding_and_7day_hard_cap():
    """Verify NIST SP 800-63B 1-hour sliding grace and 7-day hard absolute expiration."""
    vault = SessionVault()
    t0 = 1000000

    # 1. Issue ticket at T0
    ticket = vault.create_ticket("user_123", "tenant_alpha", now_ts=t0, auth_time=t0)
    assert ticket.sub == "user_123"
    assert ticket.tid == "tenant_alpha"
    assert ticket.exp == t0 + 1800  # 30 min sliding window
    assert ticket.hard_exp == t0 + ABSOLUTE_HARD_CAP_SECONDS

    # 2. Activity within 1 hour: Successfully slides forward
    t_active = t0 + 1200  # 20 min later
    renewed = vault.validate_and_renew_ticket(ticket.jti, now_ts=t_active)
    assert renewed.last_active == t_active
    assert renewed.exp == t_active + 1800

    # 3. Idle for > 1 hour (3601s): Fails with SlidingSessionExpiredError
    t_idle = t_active + SLIDING_IDLE_WINDOW_SECONDS + 1
    with pytest.raises(SlidingSessionExpiredError) as exc_info:
        vault.validate_and_renew_ticket(ticket.jti, now_ts=t_idle)
    assert "idle" in str(exc_info.value).lower()

    # 4. Mandatory 7-day Hard Cap: Fails with HardSessionExpiredError even with continuous activity
    ticket2 = vault.create_ticket("user_456", "tenant_beta", now_ts=t0, auth_time=t0)
    t_at_7days = t0 + ABSOLUTE_HARD_CAP_SECONDS + 1
    with pytest.raises(HardSessionExpiredError) as exc_info2:
        vault.validate_and_renew_ticket(ticket2.jti, now_ts=t_at_7days)
    assert "7-day" in str(exc_info2.value).lower() or "absolute" in str(exc_info2.value).lower()


@pytest.mark.asyncio
async def test_rfc8693_token_exchange_and_assumed_identity(gatekeeper_db: DatabaseConnectionFactory):
    """Verify background worker assumes delegated identity and queries correctly through gatekeeper."""
    service = RFC8693TokenExchangeService()
    t0 = int(time.time())

    # Issue delegated ticket for poller
    ticket = service.exchange_worker_ticket(
        user_id="user_john",
        tenant_id="tenant_alpha",
        actor="worker:mail_poll_worker",
        auth_time=t0,
    )
    assert ticket.act == {"sub": "worker:mail_poll_worker"}

    # Worker executes inside assumed_identity
    async with assumed_identity(ticket):
        with gatekeeper_db.session_factory() as session:
            # Should automatically see only tenant_alpha rows without any WHERE filter in query!
            records = session.scalars(select(SampleTenantEntity)).all()
            assert len(records) == 2
            assert all(r.tenant_id == "tenant_alpha" for r in records)

    # Worker ticket rejected if user's initial auth exceeds 7 days
    with pytest.raises(HardSessionExpiredError):
        service.exchange_worker_ticket(
            user_id="user_old",
            tenant_id="tenant_alpha",
            actor="worker:mail_poll_worker",
            auth_time=t0 - (ABSOLUTE_HARD_CAP_SECONDS + 100),
            now_ts=t0,
        )
