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
Anti-CSRF Double-Submit Token Engine (SEC-3).

Adheres strictly to GEES v1.0 (Zero-Trust Security & Multi-Layered Safety).
Provides:
1. Cryptographically secure random CSRF token generation.
2. Timing-safe double-submit validation for state-mutating requests (POST, PUT, DELETE).
3. FastAPI dependency for declarative route protection.
"""

import hmac
import logging
import secrets
from typing import Optional
from fastapi import Cookie, Form, Header, HTTPException, Request, status

logger = logging.getLogger("core_platform.auth.csrf")

_CSRF_COOKIE_NAME = "csrf_token"
_CSRF_HEADER_NAME = "X-CSRF-Token"


def generate_csrf_token() -> str:
    """Generate a high-entropy 32-byte hexadecimal CSRF token."""
    return secrets.token_hex(32)


def verify_csrf_token(
    request: Request,
    submitted_token: Optional[str] = None,
    cookie_token: Optional[str] = None,
) -> bool:
    """Validate submitted CSRF token against request cookie in constant time.

    Args:
        request: Active FastAPI request.
        submitted_token: Token from Form field or Header.
        cookie_token: Token from cookie; resolved from request if None.

    Returns:
        True if valid matching token, False otherwise.
    """
    expected = cookie_token or request.cookies.get(_CSRF_COOKIE_NAME)
    actual = submitted_token or request.headers.get(_CSRF_HEADER_NAME)

    if not expected:
        return True

    if not actual:
        return False

    return hmac.compare_digest(expected.encode("utf-8"), actual.encode("utf-8"))


async def require_csrf_protection(
    request: Request,
    csrf_token_form: Optional[str] = Form(default=None, alias="csrf_token"),
    csrf_token_header: Optional[str] = Header(default=None, alias="X-CSRF-Token"),
    csrf_token_cookie: Optional[str] = Cookie(default=None, alias="csrf_token"),
) -> None:
    """FastAPI dependency: Enforce valid anti-CSRF token on mutating endpoints.

    Bypasses GET, HEAD, OPTIONS. For POST/PUT/DELETE, requires matching token.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # Extract actual strings (ignoring FastAPI parameter default descriptors when called directly)
    header_val: Optional[str] = None
    if isinstance(csrf_token_header, str):
        header_val = csrf_token_header
    elif hasattr(request, "headers") and hasattr(request.headers, "get"):
        val = request.headers.get(_CSRF_HEADER_NAME)
        if isinstance(val, str):
            header_val = val

    form_val: Optional[str] = csrf_token_form if isinstance(csrf_token_form, str) else None

    cookie_val: Optional[str] = None
    if isinstance(csrf_token_cookie, str):
        cookie_val = csrf_token_cookie
    elif hasattr(request, "cookies") and hasattr(request.cookies, "get"):
        cval = request.cookies.get(_CSRF_COOKIE_NAME)
        if isinstance(cval, str):
            cookie_val = cval

    submitted = header_val or form_val
    if not submitted or not cookie_val or not hmac.compare_digest(cookie_val.encode("utf-8"), submitted.encode("utf-8")):
        logger.warning(
            "[CSRF] Blocked request from %s method=%s path=%s (CSRF token missing or mismatch)",
            request.client.host if request.client else "unknown",
            request.method,
            request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token. Please refresh the page and try again.",
        )
