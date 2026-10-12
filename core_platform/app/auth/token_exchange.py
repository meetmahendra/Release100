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
RFC 8693 OAuth 2.0 Token Exchange & Assumed Identity Engine.

Enforces delegated worker context and actor binding for background actors:
- Mail Poller Worker
- Transactional Outbox Dispatcher
- Kernel Event Bus Consumers
- MCP AI Agent Tools
"""

from contextlib import asynccontextmanager, contextmanager
import logging
import time
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional
from core_platform.app.auth.session_vault import (
    ABSOLUTE_HARD_CAP_SECONDS,
    HardSessionExpiredError,
    SecurityTicket,
    get_session_vault,
)
from core_platform.app.middleware.tenant_context import (
    UserContext,
    reset_security_ticket,
    reset_tenant_context,
    reset_user_context,
    set_current_security_ticket,
    set_current_tenant_id,
    set_current_user_context,
)

logger = logging.getLogger("core_platform.auth.token_exchange")


class RFC8693TokenExchangeService:
    """Provides RFC 8693 Token Exchange for delegating user context to autonomous workers."""

    def __init__(self) -> None:
        self.vault = get_session_vault()

    def exchange_worker_ticket(
        self,
        user_id: str,
        tenant_id: str,
        *,
        actor: str,
        auth_time: Optional[int] = None,
        scope: Optional[List[str]] = None,
        now_ts: Optional[int] = None,
    ) -> SecurityTicket:
        """Issue an RFC 8693 delegated ticket for a worker acting on behalf of a user.

        Args:
            user_id: The resource owner subject ID.
            tenant_id: The resource owner tenant ID.
            actor: The executing actor ID, e.g. "worker:mail_poll_worker".
            auth_time: Timestamp of user's original physical/OAuth authentication.
            scope: Permitted operation scopes.
            now_ts: Optional explicit current timestamp.

        Returns:
            Delegated SecurityTicket bound to (sub, tid, act).

        Raises:
            HardSessionExpiredError: When the user's initial auth exceeds 7 days.
        """
        now = now_ts or int(time.time())
        t0 = auth_time if auth_time is not None else now

        if now - t0 >= ABSOLUTE_HARD_CAP_SECONDS:
            logger.warning(
                "[TOKEN-EXCHANGE] User %s delegation expired: auth_time=%s, now=%s (>7d). Halting worker %s",
                user_id,
                t0,
                now,
                actor,
            )
            raise HardSessionExpiredError(
                f"Delegated authority for user '{user_id}' has expired (>7 days since auth). "
                f"User must re-authenticate to restore background processing."
            )

        act_claim = {"sub": actor}
        ticket = self.vault.create_ticket(
            sub=str(user_id),
            tid=str(tenant_id),
            act=act_claim,
            scope=scope or ["*"],
            auth_time=t0,
            now_ts=now,
        )
        return ticket


@asynccontextmanager
async def assumed_identity(ticket: SecurityTicket) -> AsyncGenerator[SecurityTicket, None]:
    """Async context manager binding an RFC 8693 SecurityTicket to all execution contextvars."""
    vault = get_session_vault()
    valid_ticket = vault.validate_and_renew_ticket(ticket.jti)

    t_token = set_current_tenant_id(valid_ticket.tid)
    s_token = set_current_security_ticket(valid_ticket)
    u_token = set_current_user_context(
        UserContext(
            user_id=valid_ticket.sub,
            phone_number="",
            tenant_id=valid_ticket.tid,
            role="worker" if valid_ticket.act else "user",
            metadata={"ticket_id": valid_ticket.jti, "actor": valid_ticket.act},
        )
    )
    try:
        yield valid_ticket
    finally:
        reset_user_context(u_token)
        reset_security_ticket(s_token)
        reset_tenant_context(t_token)


@contextmanager
def sync_assumed_identity(ticket: SecurityTicket) -> Generator[SecurityTicket, None, None]:
    """Synchronous context manager binding an RFC 8693 SecurityTicket to execution contextvars."""
    vault = get_session_vault()
    valid_ticket = vault.validate_and_renew_ticket(ticket.jti)

    t_token = set_current_tenant_id(valid_ticket.tid)
    s_token = set_current_security_ticket(valid_ticket)
    u_token = set_current_user_context(
        UserContext(
            user_id=valid_ticket.sub,
            phone_number="",
            tenant_id=valid_ticket.tid,
            role="worker" if valid_ticket.act else "user",
            metadata={"ticket_id": valid_ticket.jti, "actor": valid_ticket.act},
        )
    )
    try:
        yield valid_ticket
    finally:
        reset_user_context(u_token)
        reset_security_ticket(s_token)
        reset_tenant_context(t_token)


# Global Singleton Service
_exchange_service_instance: Optional[RFC8693TokenExchangeService] = None


def get_token_exchange_service() -> RFC8693TokenExchangeService:
    """Retrieve global RFC8693TokenExchangeService instance."""
    global _exchange_service_instance
    if _exchange_service_instance is None:
        _exchange_service_instance = RFC8693TokenExchangeService()
    return _exchange_service_instance
