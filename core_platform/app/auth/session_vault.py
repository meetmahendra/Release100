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
NIST SP 800-63B §7.2 Session Lifecycle & Cryptographic Security Ticket Vault.

Governing Standards:
- IETF RFC 6749 / RFC 9068: Scoped Authorization and JWT Profile
- IETF RFC 8693: Token Exchange Actor Claim ('act')
- NIST SP 800-63B §7.2:
    1. Short-Lived Access Tickets (15-30 minutes).
    2. 1-Hour Sliding Inactivity Grace Window (Idle timeout).
    3. 7-Day Hard Absolute Session Cap (T0 + 604,800s) requiring physical re-authentication.
"""

from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

logger = logging.getLogger("core_platform.auth.session_vault")

# NIST SP 800-63B Invariant Constants
SLIDING_IDLE_WINDOW_SECONDS: int = 3600       # 1 Hour maximum inactivity
SHORT_LIVED_TICKET_SECONDS: int = 1800        # 30 Minutes active validity
ABSOLUTE_HARD_CAP_SECONDS: int = 7 * 86400    # 7 Days (604,800s)


class SessionExpiredError(PermissionError):
    """Base exception for session invalidation."""
    pass


class SlidingSessionExpiredError(SessionExpiredError):
    """Raised when inactivity exceeds the 1-hour sliding renewal grace window."""
    pass


class HardSessionExpiredError(SessionExpiredError):
    """Raised when session exceeds the mandatory 7-day hard absolute cap."""
    pass


class SecurityTicket(BaseModel):
    """Immutable Cryptographic Security Ticket complying with RFC 9068 & RFC 8693."""

    jti: str = Field(default_factory=lambda: str(uuid.uuid4()))
    iss: str = Field(default="release100-substrate-auth")
    sub: str = Field(..., description="Subject identity (User ID or Machine ID)")
    tid: str = Field(..., description="Immutable Tenant ID")
    aud: str = Field(default="release100-api")
    act: Optional[Dict[str, str]] = Field(default=None, description="RFC 8693 Actor context, e.g. {'sub': 'worker:poll'}")
    scope: List[str] = Field(default_factory=lambda: ["*"])
    auth_time: int = Field(..., description="Unix timestamp T0 of initial physical credential verification")
    iat: int = Field(..., description="Issued at Unix timestamp")
    last_active: int = Field(..., description="Unix timestamp of last observed operation")
    exp: int = Field(..., description="Sliding expiration timestamp")
    hard_exp: int = Field(..., description="Absolute 7-day cutoff timestamp")
    is_revoked: bool = Field(default=False)

    def is_active(self, now_ts: Optional[int] = None) -> bool:
        """Check if ticket is strictly valid right now without sliding extension."""
        now = now_ts or int(time.time())
        if self.is_revoked:
            return False
        if now > self.hard_exp:
            return False
        if now > self.exp:
            return False
        return True

    def is_eligible_for_sliding(self, now_ts: Optional[int] = None) -> bool:
        """Check if ticket can slide forward within the 1-hour inactivity grace window."""
        now = now_ts or int(time.time())
        if self.is_revoked:
            return False
        if now > self.hard_exp:
            return False
        if (now - self.last_active) > SLIDING_IDLE_WINDOW_SECONDS:
            return False
        return True


class SessionVault:
    """Thread-safe Substrate Session Vault managing ticket lifecycle & NIST enforcement."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tickets: Dict[str, SecurityTicket] = {}
        self._user_tickets: Dict[str, List[str]] = {}
        self._tenant_tickets: Dict[str, List[str]] = {}

    def create_ticket(
        self,
        sub: str,
        tid: str,
        *,
        act: Optional[Dict[str, str]] = None,
        scope: Optional[List[str]] = None,
        auth_time: Optional[int] = None,
        now_ts: Optional[int] = None,
        jti: Optional[str] = None,
    ) -> SecurityTicket:
        """Issue a new RFC 9068 / RFC 8693 SecurityTicket bound to (sub, tid)."""
        now = now_ts or int(time.time())
        t0 = auth_time if auth_time is not None else now
        hard_cutoff = t0 + ABSOLUTE_HARD_CAP_SECONDS
        sliding_cutoff = min(now + SHORT_LIVED_TICKET_SECONDS, hard_cutoff)

        ticket = SecurityTicket(
            jti=jti or str(uuid.uuid4()),
            iss="release100-substrate-auth",
            sub=str(sub),
            tid=str(tid),
            aud="release100-api",
            act=act,
            scope=scope or ["*"],
            auth_time=t0,
            iat=now,
            last_active=now,
            exp=sliding_cutoff,
            hard_exp=hard_cutoff,
            is_revoked=False,
        )

        with self._lock:
            self._tickets[ticket.jti] = ticket
            self._user_tickets.setdefault(ticket.sub, []).append(ticket.jti)
            self._tenant_tickets.setdefault(ticket.tid, []).append(ticket.jti)

        logger.info(
            "[SESSION-VAULT] Issued ticket %s for sub=%s tid=%s (act=%s, hard_exp=%s)",
            ticket.jti,
            ticket.sub,
            ticket.tid,
            ticket.act,
            datetime.fromtimestamp(ticket.hard_exp, tz=timezone.utc).isoformat(),
        )
        return ticket

    def validate_and_renew_ticket(
        self,
        jti: str,
        now_ts: Optional[int] = None,
    ) -> SecurityTicket:
        """Validate ticket and slide active window if within 1-hour grace; fail-closed if expired."""
        now = now_ts or int(time.time())

        with self._lock:
            ticket = self._tickets.get(jti)
            if not ticket or ticket.is_revoked:
                raise SessionExpiredError(f"Security ticket '{jti}' is invalid or revoked.")

            # Invariant 1: Mandatory 7-Day Hard Wall (NIST SP 800-63B)
            if now >= ticket.hard_exp:
                ticket.is_revoked = True
                logger.warning(
                    "[SESSION-VAULT] Ticket %s exceeded 7-day absolute cap (auth_time=%s, now=%s). Hard revoked.",
                    jti,
                    ticket.auth_time,
                    now,
                )
                raise HardSessionExpiredError(
                    f"Session for sub='{ticket.sub}' has exceeded the mandatory 7-day absolute limit. "
                    f"Physical re-authentication is required."
                )

            # Invariant 2: 1-Hour Sliding Idle Window (NIST SP 800-63B)
            idle_seconds = now - ticket.last_active
            if idle_seconds > SLIDING_IDLE_WINDOW_SECONDS:
                ticket.is_revoked = True
                logger.warning(
                    "[SESSION-VAULT] Ticket %s idle for %ss > 3600s. Sliding grace expired. Revoked.",
                    jti,
                    idle_seconds,
                )
                raise SlidingSessionExpiredError(
                    f"Session for sub='{ticket.sub}' was idle for {idle_seconds}s (limit: 3600s). "
                    f"Re-authentication required."
                )

            # Invariant 3: Sliding Extension
            ticket.last_active = now
            ticket.exp = min(now + SHORT_LIVED_TICKET_SECONDS, ticket.hard_exp)
            return ticket

    def get_ticket(self, jti: str) -> Optional[SecurityTicket]:
        """Lookup ticket without updating activity timestamp."""
        with self._lock:
            return self._tickets.get(jti)

    def revoke_ticket(self, jti: str) -> bool:
        """Explicitly revoke a single ticket."""
        with self._lock:
            ticket = self._tickets.get(jti)
            if ticket:
                ticket.is_revoked = True
                logger.info("[SESSION-VAULT] Revoked ticket %s for sub=%s tid=%s", jti, ticket.sub, ticket.tid)
                return True
            return False

    def revoke_user_sessions(self, sub: str) -> int:
        """Revoke all active tickets for a user upon credential change or logout."""
        count = 0
        with self._lock:
            jtis = self._user_tickets.get(sub, [])
            for jti in jtis:
                t = self._tickets.get(jti)
                if t and not t.is_revoked:
                    t.is_revoked = True
                    count += 1
        logger.info("[SESSION-VAULT] Revoked %d tickets for user sub=%s", count, sub)
        return count

    def revoke_tenant_sessions(self, tid: str) -> int:
        """Revoke all active tickets for a tenant upon tenant suspension."""
        count = 0
        with self._lock:
            jtis = self._tenant_tickets.get(tid, [])
            for jti in jtis:
                t = self._tickets.get(jti)
                if t and not t.is_revoked:
                    t.is_revoked = True
                    count += 1
        logger.info("[SESSION-VAULT] Revoked %d tickets for tenant tid=%s", count, tid)
        return count

    def clear(self) -> None:
        """Clear all tickets (used in tests)."""
        with self._lock:
            self._tickets.clear()
            self._user_tickets.clear()
            self._tenant_tickets.clear()


# Global Singleton SessionVault
_session_vault_instance: Optional[SessionVault] = None
_vault_lock = threading.Lock()


def get_session_vault() -> SessionVault:
    """Retrieve global SessionVault instance."""
    global _session_vault_instance
    if _session_vault_instance is None:
        with _vault_lock:
            if _session_vault_instance is None:
                _session_vault_instance = SessionVault()
    return _session_vault_instance
