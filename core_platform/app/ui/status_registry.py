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

"""Canonical status and badge registry, the SSOT for status presentation (Plan 11, T07).

Core registers generic, domain-free statuses. A cartridge adds its own through
``BaseApplication.get_ui_statuses()``; those live in a separate per-app namespace so
they can never override a core status. Unknown codes fall back to a neutral badge.
"""

from __future__ import annotations

import re
import threading
from typing import Dict, FrozenSet, Mapping, Optional

from core_platform.app.ui.contracts import StatusInfo

__all__ = ["StatusInfo", "StatusRegistry", "get_status_registry", "reset_status_registry"]

_CODE_RE = re.compile(r"[a-z0-9_]+")
_UNKNOWN_LABEL_KEY = "core.status.unknown"

_GENERIC: Mapping[str, StatusInfo] = {
    info.code: info
    for info in (
        StatusInfo(code="active", tone="success", icon="check", label_key="core.status.active"),
        StatusInfo(code="inactive", tone="neutral", icon="minus", label_key="core.status.inactive"),
        StatusInfo(code="pending", tone="warning", icon="clock", label_key="core.status.pending"),
        StatusInfo(code="approved", tone="success", icon="check", label_key="core.status.approved"),
        StatusInfo(code="rejected", tone="danger", icon="x", label_key="core.status.rejected"),
        StatusInfo(code="success", tone="success", icon="check", label_key="core.status.success"),
        StatusInfo(code="warning", tone="warning", icon="alert", label_key="core.status.warning"),
        StatusInfo(code="failed", tone="danger", icon="x", label_key="core.status.failed"),
        StatusInfo(code="off", tone="neutral", icon="minus", label_key="core.status.off"),
        StatusInfo(code="shadow", tone="info", icon="eye", label_key="core.status.shadow"),
        StatusInfo(code="enforce", tone="info", icon="shield", label_key="core.status.enforce"),
    )
}


def normalize_code(code: str) -> str:
    """Lower-case a status code and turn spaces and hyphens into underscores."""
    return re.sub(r"[\s\-]+", "_", code.strip().lower())


class StatusRegistry:
    """Thread-safe registry of status presentation data."""

    def __init__(self) -> None:
        """Create a registry pre-loaded with the generic core statuses."""
        self._apps: Dict[str, Dict[str, StatusInfo]] = {}
        self._lock = threading.RLock()

    def register_app(self, app_id: str, statuses: Mapping[str, StatusInfo]) -> None:
        """Register cartridge statuses; label keys must live under ``apps.<app_id>.status.``.

        Raises:
            ValueError: On an invalid code, a mismatched code/key pair or a foreign label key.
        """
        prefix = f"apps.{app_id}.status."
        validated: Dict[str, StatusInfo] = {}
        for code, info in statuses.items():
            if _CODE_RE.fullmatch(code) is None or info.code != code:
                raise ValueError(f"invalid status code '{code}' for app '{app_id}'")
            if not info.label_key.startswith(prefix):
                raise ValueError(f"status label key '{info.label_key}' must start with '{prefix}'")
            validated[code] = info
        with self._lock:
            self._apps.setdefault(app_id, {}).update(validated)

    def get(self, code: str, app_id: Optional[str] = None) -> StatusInfo:
        """Return presentation data for ``code``; cartridge statuses win only inside their app.

        Unknown codes return a neutral fallback (never raises).
        """
        normalized = normalize_code(code)
        with self._lock:
            if app_id is not None:
                scoped = self._apps.get(app_id, {}).get(normalized)
                if scoped is not None:
                    return scoped
        generic = _GENERIC.get(normalized)
        if generic is not None:
            return generic
        return StatusInfo(code=normalized or "unknown", tone="neutral", icon="dot", label_key=_UNKNOWN_LABEL_KEY)

    def codes(self, app_id: Optional[str] = None) -> FrozenSet[str]:
        """Return the known codes: generic ones, plus the app's own when ``app_id`` is given."""
        with self._lock:
            own = frozenset(self._apps.get(app_id, {})) if app_id is not None else frozenset()
        return frozenset(_GENERIC) | own

    def label_keys(self) -> FrozenSet[str]:
        """Return every label key the registry can emit (used by catalog parity guards)."""
        with self._lock:
            keys = {info.label_key for info in _GENERIC.values()}
            keys.add(_UNKNOWN_LABEL_KEY)
            for statuses in self._apps.values():
                keys.update(info.label_key for info in statuses.values())
        return frozenset(keys)


_registry: Optional[StatusRegistry] = None
_registry_lock = threading.Lock()


def get_status_registry() -> StatusRegistry:
    """Return the process-wide status registry."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = StatusRegistry()
        return _registry


def reset_status_registry() -> None:
    """Drop the process-wide registry (tests and reload)."""
    global _registry
    with _registry_lock:
        _registry = None
