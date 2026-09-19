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
Per-Sender Token Bucket Rate Limiter.

Adheres strictly to GEES v1.0 (Pillar 1 - Layer 0) and Plan 02 v1.3 Section 2.
Provides deterministic, pre-execution rate limiting for all ingress channels
(WhatsApp, Web, MCP) before any AI model invocation.

Algorithm: Token Bucket
  - Each sender starts with a full bucket of `max_tokens` capacity.
  - Tokens are consumed one per request.
  - Tokens refill at a constant `refill_rate_per_second` rate.
  - If the bucket is empty, the request is rejected immediately.
"""

import threading
import time
from typing import Dict, Optional, Tuple


class TokenBucket:
    """Single per-sender token bucket for rate limiting."""

    def __init__(
        self,
        capacity: float,
        refill_rate_per_second: float,
    ) -> None:
        """Initialize a TokenBucket.

        Args:
            capacity: Maximum number of tokens (burst limit).
            refill_rate_per_second: Tokens added per second continuously.
        """
        self.capacity = capacity
        self.refill_rate = refill_rate_per_second
        self.tokens: float = capacity
        self.last_refill_time: float = time.monotonic()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self.last_refill_time
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill_time = now

    def consume(self, tokens: float = 1.0) -> bool:
        """Attempt to consume tokens.

        Args:
            tokens: Number of tokens to consume (default 1).

        Returns:
            True if tokens were available and consumed, False if rate limit exceeded.
        """
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def available(self) -> float:
        """Current available token count after refill."""
        self._refill()
        return self.tokens


class RateLimiter:
    """
    Thread-safe per-sender rate limiter for all Release100 ingress channels.

    Maintains one TokenBucket per unique sender_id.
    Senders that have been idle beyond `cleanup_after_seconds` are evicted
    from memory to prevent unbounded growth.
    """

    def __init__(
        self,
        max_tokens: float = 10.0,
        refill_rate_per_second: float = 1.0,
        cleanup_after_seconds: float = 3600.0,
    ) -> None:
        """Initialize the RateLimiter.

        Args:
            max_tokens: Burst capacity per sender (default 10 requests).
            refill_rate_per_second: Token refill speed (default 1 req/sec = 60 req/min).
            cleanup_after_seconds: Evict idle senders after this duration (default 1 hour).
        """
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate_per_second
        self.cleanup_after = cleanup_after_seconds

        self._buckets: Dict[str, TokenBucket] = {}
        self._last_seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_consume(
        self,
        sender_id: str,
        tokens: float = 1.0,
    ) -> Tuple[bool, float]:
        """Check rate limit and consume a token if allowed.

        Args:
            sender_id: Unique sender identifier (E.164 phone, email, API key).
            tokens: Tokens to consume (default 1).

        Returns:
            Tuple of (is_allowed: bool, remaining_tokens: float).
        """
        with self._lock:
            now = time.monotonic()

            # Lazy eviction of idle senders
            self._evict_idle_senders(now)

            if sender_id not in self._buckets:
                self._buckets[sender_id] = TokenBucket(
                    capacity=self.max_tokens,
                    refill_rate_per_second=self.refill_rate,
                )

            self._last_seen[sender_id] = now
            bucket = self._buckets[sender_id]
            allowed = bucket.consume(tokens)
            return allowed, bucket.available

    def _evict_idle_senders(self, now: float) -> None:
        """Remove senders that have been idle beyond cleanup threshold."""
        idle_senders = [
            sid
            for sid, last in self._last_seen.items()
            if now - last > self.cleanup_after
        ]
        for sid in idle_senders:
            self._buckets.pop(sid, None)
            self._last_seen.pop(sid, None)

    def get_remaining_tokens(self, sender_id: str) -> float:
        """Get the current remaining token count for a sender without consuming.

        Args:
            sender_id: Unique sender identifier.

        Returns:
            Number of available tokens (0.0 if sender not tracked).
        """
        with self._lock:
            bucket = self._buckets.get(sender_id)
            if bucket is None:
                return self.max_tokens
            return bucket.available

    def reset_sender(self, sender_id: str) -> None:
        """Reset a sender's bucket to full capacity (admin override).

        Args:
            sender_id: Unique sender identifier.
        """
        with self._lock:
            self._buckets.pop(sender_id, None)
            self._last_seen.pop(sender_id, None)

    @property
    def active_sender_count(self) -> int:
        """Number of senders currently tracked."""
        with self._lock:
            return len(self._buckets)


# Platform-level singleton with WhatsApp-appropriate defaults:
# 10 burst messages, 1 message/second sustained refill (60/min max).
_platform_rate_limiter: Optional[RateLimiter] = None
_rl_lock = threading.Lock()


def get_platform_rate_limiter() -> RateLimiter:
    """Return the singleton platform rate limiter instance.

    Returns:
        RateLimiter configured with platform defaults.
    """
    global _platform_rate_limiter
    with _rl_lock:
        if _platform_rate_limiter is None:
            _platform_rate_limiter = RateLimiter(
                max_tokens=10.0,
                refill_rate_per_second=1.0,
                cleanup_after_seconds=3600.0,
            )
        return _platform_rate_limiter
