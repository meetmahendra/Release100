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
Unit tests for TokenBucket and RateLimiter.
Adheres strictly to GEES v1.0.
"""

import time
from core_platform.app.ingress.rate_limiter import (
    RateLimiter,
    TokenBucket,
    get_platform_rate_limiter,
)


def test_token_bucket() -> None:
    """Test token bucket initialization, consumption, and refill."""
    bucket = TokenBucket(capacity=2.0, refill_rate_per_second=10.0)
    assert bucket.available == 2.0

    # Consume 1
    assert bucket.consume(1.0) is True
    assert bucket.available < 2.0

    # Consume 1 more
    assert bucket.consume(1.0) is True

    # Empty
    assert bucket.consume(1.0) is False

    # Wait 0.1s for refill (at 10 tokens/sec, 0.1s = 1.0 token)
    time.sleep(0.12)
    assert bucket.consume(1.0) is True


def test_rate_limiter_multisender() -> None:
    """Test RateLimiter per-sender isolation, consumption, and eviction."""
    limiter = RateLimiter(max_tokens=3.0, refill_rate_per_second=1.0, cleanup_after_seconds=0.05)

    # Sender 1 consumes all 3 tokens
    allowed1, rem1 = limiter.check_and_consume("sender_1")
    assert allowed1 is True
    allowed2, rem2 = limiter.check_and_consume("sender_1")
    assert allowed2 is True
    allowed3, rem3 = limiter.check_and_consume("sender_1")
    assert allowed3 is True

    # 4th request from sender 1 is rejected
    allowed4, rem4 = limiter.check_and_consume("sender_1")
    assert allowed4 is False

    # Sender 2 is independent and has full capacity
    allowed_s2, rem_s2 = limiter.check_and_consume("sender_2")
    assert allowed_s2 is True
    assert limiter.active_sender_count == 2

    # Test remaining tokens inspect
    rem_inspect = limiter.get_remaining_tokens("sender_2")
    assert rem_inspect > 1.5

    # Test reset
    limiter.reset_sender("sender_1")
    assert limiter.active_sender_count == 1

    # Test idle eviction
    limiter.check_and_consume("idle_user")
    assert limiter.active_sender_count == 2
    time.sleep(0.06)
    limiter.check_and_consume("active_user")
    # idle_user should be evicted
    assert limiter.get_remaining_tokens("idle_user") == limiter.max_tokens


def test_global_rate_limiter() -> None:
    """Test global singleton accessor."""
    rl = get_platform_rate_limiter()
    assert isinstance(rl, RateLimiter)
    allowed, _ = rl.check_and_consume("test_probe")
    assert allowed is True
