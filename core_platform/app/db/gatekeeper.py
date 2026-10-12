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
SQLAlchemy Microkernel Substrate Gatekeeper (Plane 2).

Enforces GEES v3.1 Data Sovereignty, Tenant Isolation, and Fail-Closed Storage:
1. Intercepts all ORM execution statements via `do_orm_execute`.
2. Fails closed on ambient queries targeting tenant-scoped entities without an active context.
3. Injects AST filter `with_loader_criteria(Entity, Entity.tenant_id == current_tenant)` recursively.
4. Intercepts `before_flush` mutations to detect and abort cross-tenant tampering.
"""

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
import logging
from typing import Any, AsyncGenerator, Callable, Dict, Generator, List, Optional, Set
from sqlalchemy import event, select
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker, with_loader_criteria

logger = logging.getLogger("core_platform.db.gatekeeper")

# System context flag allowing administrative migrations and internal substrate jobs
_system_context_active: ContextVar[bool] = ContextVar("system_context_active", default=False)

# Tables excluded from tenant isolation rules (global / infrastructure tables)
SYSTEM_EXCLUDED_TABLES: Set[str] = {
    "tenants",
    "system_sessions",
    "system_security_tickets",
    "system_worker_delegations",
    "alembic_version",
}


class TenantIsolationViolationError(PermissionError):
    """Raised when an ambient query touches a tenant-scoped entity without an active tenant context."""
    pass


class CrossTenantAccessViolationError(PermissionError):
    """Raised when a query or write operation violates tenant boundary isolation."""
    pass


def is_system_context() -> bool:
    """Return True if the current execution context is an authorized system substrate job."""
    return _system_context_active.get()


@contextmanager
def system_context() -> Generator[None, None, None]:
    """Context manager granting bypass for internal database bootstrap, migrations, or cross-tenant ops."""
    token: Token[bool] = _system_context_active.set(True)
    try:
        yield
    finally:
        _system_context_active.reset(token)


@asynccontextmanager
async def async_system_context() -> AsyncGenerator[None, None]:
    """Async context manager granting bypass for internal database bootstrap or substrate ops."""
    token: Token[bool] = _system_context_active.set(True)
    try:
        yield
    finally:
        _system_context_active.reset(token)


def get_active_tenant_id() -> Optional[str]:
    """Return active tenant ID from contextvars, or None if ambient unauthenticated."""
    try:
        from core_platform.app.middleware.tenant_context import _current_tenant_ctx, _current_security_ticket
        t_ctx = _current_tenant_ctx.get()
        if t_ctx is not None and t_ctx.tenant_id and t_ctx.tenant_id.strip():
            return t_ctx.tenant_id.strip()

        ticket = _current_security_ticket.get()
        if ticket is not None and getattr(ticket, "tid", None):
            return str(ticket.tid).strip()
    except Exception:
        pass
    return None


def is_super_admin_context() -> bool:
    """Check if current active user is a verified super admin or devops admin."""
    try:
        from core_platform.app.middleware.tenant_context import _current_user_ctx
        u_ctx = _current_user_ctx.get()
        if u_ctx is not None:
            if u_ctx.role in ("super_admin", "devops_admin", "system"):
                return True
            if u_ctx.metadata.get("is_super_admin") or u_ctx.metadata.get("is_system"):
                return True
    except Exception:
        pass
    return False


def gatekeeper_do_orm_execute(orm_execute_state: ORMExecuteState) -> None:
    """Intercept ORM executions to enforce AST tenant filtering and fail-closed isolation."""
    if is_system_context() or orm_execute_state.execution_options.get("allow_ambient_system", False):
        return

    if not orm_execute_state.is_select:
        return

    # Check for tenant-scoped mappers in the statement
    tenant_mappers: List[Any] = []
    for mapper in orm_execute_state.all_mappers:
        if mapper and hasattr(mapper.class_, "tenant_id"):
            tbl_name = getattr(mapper.class_, "__tablename__", "")
            if tbl_name not in SYSTEM_EXCLUDED_TABLES:
                tenant_mappers.append(mapper)

    if not tenant_mappers:
        return

    current_tenant = get_active_tenant_id()
    is_super = is_super_admin_context()

    # Fail closed on ambient queries touching tenant entities without context
    if not current_tenant and not is_super:
        entity_name = tenant_mappers[0].class_.__name__
        logger.error(
            "[GATEKEEPER-VIOLATION] Ambient read rejected: Entity '%s' requires active tenant context",
            entity_name,
        )
        raise TenantIsolationViolationError(
            f"Ambient query rejected: Entity '{entity_name}' is tenant-scoped but no authenticated "
            f"tenant context is active. Call within tenant_scope(...) or assumed_identity(...)."
        )

    # Allow super admin to inspect across tenants if specifically authorized or unscoped
    if is_super and (not current_tenant or current_tenant in ("platform", "*")):
        return

    # Apply AST criteria injection across all tenant-scoped mappers
    for mapper in tenant_mappers:
        target_cls = mapper.class_
        active_t = current_tenant
        orm_execute_state.statement = orm_execute_state.statement.options(
            with_loader_criteria(
                target_cls,
                lambda target: target.tenant_id == active_t,
                include_aliases=True,
                propagate_to_loaders=True,
            )
        )



def gatekeeper_before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    """Intercept before_flush to detect and reject cross-tenant tampering or ambient writes."""
    if is_system_context():
        return

    current_tenant = get_active_tenant_id()
    is_super = is_super_admin_context()

    for instance in list(session.new) + list(session.dirty):
        if hasattr(instance, "tenant_id"):
            tbl_name = getattr(instance, "__tablename__", "")
            if tbl_name in SYSTEM_EXCLUDED_TABLES:
                continue

            target_tenant = getattr(instance, "tenant_id", None)
            if not current_tenant and not is_super:
                logger.error(
                    "[GATEKEEPER-VIOLATION] Ambient write rejected: Cannot mutate '%s' without tenant context",
                    instance.__class__.__name__,
                )
                raise TenantIsolationViolationError(
                    f"Ambient write rejected: Cannot mutate tenant-scoped entity '{instance.__class__.__name__}' "
                    f"without an active authenticated tenant context."
                )

            if current_tenant and target_tenant and target_tenant != current_tenant and not is_super:
                logger.error(
                    "[GATEKEEPER-VIOLATION] Cross-tenant write rejected: Entity '%s' (tenant=%s) vs context=%s",
                    instance.__class__.__name__,
                    target_tenant,
                    current_tenant,
                )
                raise CrossTenantAccessViolationError(
                    f"Cross-tenant write rejected: Entity '{instance.__class__.__name__}' belongs to tenant "
                    f"'{target_tenant}', but active execution context is scoped to '{current_tenant}'."
                )


def attach_gatekeeper_listeners(factory: sessionmaker[Session]) -> None:
    """Attach gatekeeper event listeners to a SQLAlchemy session factory."""
    event.listen(factory, "do_orm_execute", gatekeeper_do_orm_execute)
    event.listen(factory, "before_flush", gatekeeper_before_flush)
    logger.debug("[GATEKEEPER] Substrate tenant isolation listeners successfully attached to sessionmaker.")
