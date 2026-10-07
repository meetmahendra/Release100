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

"""UI locale negotiation (Plan 11, T05).

Precedence: explicit ``?lang=`` query value, then the locale cookie, then the
``Accept-Language`` header, then the configured default. Only locales listed in
``UI_SUPPORTED_LOCALES`` are ever accepted. The result is stored on
``request.state.locale``.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable, List, Optional, Sequence, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_TAG_RE = re.compile(r"^([A-Za-z]{2,3})(?:[-_]([A-Za-z]{2}))?$")
_COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60


def _canonical(tag: str) -> Optional[Tuple[str, Optional[str]]]:
    """Return ``(language_lower, REGION_upper_or_None)`` for a language tag, or ``None``."""
    match = _TAG_RE.match(tag.strip())
    if match is None:
        return None
    region = match.group(2)
    return match.group(1).lower(), (region.upper() if region else None)


def _match_supported(tag: str, supported: Sequence[str]) -> Optional[str]:
    """Map a tag such as ``en-us`` or ``hi`` to a supported locale code, if any."""
    parsed = _canonical(tag)
    if parsed is None:
        return None
    language, region = parsed
    if region is not None:
        exact = f"{language}_{region}"
        if exact in supported:
            return exact
    for candidate in supported:
        if candidate.split("_", 1)[0] == language:
            return candidate
    return None


def parse_accept_language(header: str) -> List[str]:
    """Return language tags from an ``Accept-Language`` header ordered by quality.

    Malformed entries are skipped; the function never raises.
    """
    ranked: List[Tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                continue
        if tag.strip() == "*" or _canonical(tag) is None:
            continue
        ranked.append((-quality, index, tag.strip()))
    ranked.sort()
    return [tag for _, _, tag in ranked]


def negotiate_locale(
    query: Optional[str],
    cookie: Optional[str],
    accept_language: Optional[str],
    supported: Sequence[str],
    default: str,
) -> str:
    """Pick the UI locale following the documented precedence.

    Args:
        query: Value of the ``lang`` query parameter, if any.
        cookie: Value of the locale cookie, if any.
        accept_language: Raw ``Accept-Language`` header, if any.
        supported: Locales the platform may serve.
        default: Fallback locale.

    Returns:
        A locale code from ``supported`` (or ``default`` when nothing matches).
    """
    for explicit in (query, cookie):
        if explicit:
            matched = _match_supported(explicit, supported)
            if matched is not None:
                return matched
    if accept_language:
        for tag in parse_accept_language(accept_language):
            matched = _match_supported(tag, supported)
            if matched is not None:
                return matched
    return default


class LocaleMiddleware(BaseHTTPMiddleware):
    """Negotiate the locale per request and persist an explicit ``?lang=`` choice."""

    def __init__(self, app: ASGIApp, supported: Sequence[str], default: str, cookie_name: str) -> None:
        """Create the middleware.

        Args:
            app: Wrapped ASGI application.
            supported: Supported locale codes.
            default: Default locale code.
            cookie_name: Cookie that stores the chosen locale.
        """
        super().__init__(app)
        self._supported = list(supported)
        self._default = default
        self._cookie_name = cookie_name

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Set ``request.state.locale`` and, for a valid ``?lang=``, the locale cookie."""
        query = request.query_params.get("lang")
        locale = negotiate_locale(
            query,
            request.cookies.get(self._cookie_name),
            request.headers.get("accept-language"),
            self._supported,
            self._default,
        )
        request.state.locale = locale
        response = await call_next(request)
        if query and _match_supported(query, self._supported) == locale:
            response.set_cookie(
                self._cookie_name,
                locale,
                max_age=_COOKIE_MAX_AGE_SECONDS,
                samesite="lax",
                path="/",
            )
        return response
