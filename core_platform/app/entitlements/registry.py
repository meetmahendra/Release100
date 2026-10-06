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

"""In-memory catalog of validated cartridge entitlement manifests (Plan 10, T04)."""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Mapping, Optional

from pydantic import ValidationError

from core_platform.app.entitlements.models import ActionDef, BundleDef, EntitlementManifest

logger = logging.getLogger("core_platform.entitlements.registry")


class EntitlementRegistry:
    """Thread-safe catalog of manifests keyed by cartridge ``app_id``.

    Enforces that action namespaces and MCP tool names are globally unique so
    one cartridge can never squat on another cartridge's identifiers.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._lock = threading.Lock()
        self._manifests: Dict[str, EntitlementManifest] = {}
        self.rejected: Dict[str, List[str]] = {}

    def register(self, app_id: str, manifest: EntitlementManifest) -> None:
        """Register (or replace) the manifest of ``app_id``.

        Raises:
            ValueError: If the namespace or an MCP tool name is owned by another cartridge,
                or if two actions in the manifest claim the same MCP tool.
        """
        with self._lock:
            for other_id, other in self._manifests.items():
                if other_id != app_id and other.namespace == manifest.namespace:
                    raise ValueError(f"namespace '{manifest.namespace}' already owned by '{other_id}'")
            claimed: Dict[str, str] = {}
            for action in manifest.actions:
                for tool in action.mcp_tools:
                    if tool in claimed:
                        raise ValueError(f"mcp tool '{tool}' claimed by '{claimed[tool]}' and '{action.action_id}'")
                    claimed[tool] = action.action_id
            for other_id, other in self._manifests.items():
                if other_id == app_id:
                    continue
                for action in other.actions:
                    for tool in action.mcp_tools:
                        if tool in claimed:
                            raise ValueError(f"mcp tool '{tool}' already owned by '{other_id}'")
            self._manifests[app_id] = manifest
            self.rejected.pop(app_id, None)

    def register_raw(self, app_id: str, payload: Mapping[str, Any]) -> bool:
        """Validate and register a raw manifest payload.

        Never raises: failures are recorded in ``rejected`` and the registry is left unchanged.

        Returns:
            True when registered, False when rejected.
        """
        try:
            manifest = EntitlementManifest.model_validate(dict(payload))
            self.register(app_id, manifest)
            return True
        except (ValidationError, ValueError) as err:
            with self._lock:
                self.rejected.setdefault(app_id, []).append(str(err))
            logger.error("[EntitlementRegistry] Rejected manifest for '%s': %s", app_id, err)
            return False

    def get_manifest(self, app_id: str) -> Optional[EntitlementManifest]:
        """Return the manifest of ``app_id`` or None."""
        with self._lock:
            return self._manifests.get(app_id)

    def list_apps(self) -> List[str]:
        """Return registered cartridge ids in sorted order."""
        with self._lock:
            return sorted(self._manifests)

    def get_action(self, action_id: str) -> Optional[ActionDef]:
        """Return the action definition for ``action_id`` from any cartridge, or None."""
        with self._lock:
            for manifest in self._manifests.values():
                action = manifest.action_map().get(action_id)
                if action is not None:
                    return action
        return None

    def action_for_mcp_tool(self, tool_name: str) -> Optional[str]:
        """Return the action id that authorizes the MCP tool, or None when unmapped."""
        with self._lock:
            for manifest in self._manifests.values():
                for action in manifest.actions:
                    if tool_name in action.mcp_tools:
                        return action.action_id
        return None

    def get_bundle(self, app_id: str, bundle_id: str) -> Optional[BundleDef]:
        """Return a bundle definition or None."""
        manifest = self.get_manifest(app_id)
        if manifest is None:
            return None
        return next((b for b in manifest.bundles if b.bundle_id == bundle_id), None)

    def bundle_contains(self, app_id: str, bundle_id: str, action_id: str) -> bool:
        """Return True only if the bundle exists and currently includes ``action_id``."""
        bundle = self.get_bundle(app_id, bundle_id)
        return bundle is not None and action_id in bundle.actions
