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
BaseApplication Plugin Interface Contract.

Adheres strictly to Plan 02 v1.3 Section 11 and Plan 01 v1.4 Section 1.
All domain application cartridges must subclass BaseApplication to plug into
the Release100 Core Orchestrator via the dynamic plugin loader.

This interface enforces:
  1. Declarative metadata (app_id, name, version, roles, channels).
  2. Workflow graph accessor (LangGraph StateGraph).
  3. UI router accessor (FastAPI APIRouter).
  4. MCP tool manifest accessor.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel


class BaseApplication(ABC):
    """
    Abstract plugin interface that every domain application cartridge must implement.

    The Core Platform Plugin Engine calls these methods during dynamic
    registration, health reporting, and request routing.
    """

    # ── Declarative Metadata (override as class attributes) ───────────────────
    app_id: str = "undefined"
    """Unique snake_case identifier for this application. Must be unique per platform."""

    name: str = "Unnamed Application"
    """Human-readable display name shown in admin UI and tray menu."""

    version: str = "0.0.0"
    """Semantic version string (MAJOR.MINOR.PATCH)."""

    description: str = ""
    """Short description of what this application cartridge does."""

    required_roles: List[str] = []
    """RBAC role identifiers that are permitted to access this application."""

    supported_channels: List[str] = ["whatsapp"]
    """Ingress channels this application handles: 'whatsapp', 'email', 'web_kiosk', 'mcp_agent'."""

    config_schema: Optional[Type[BaseModel]] = None
    """Optional Pydantic model class for domain-specific configuration validation."""

    # ── Lifecycle Methods ─────────────────────────────────────────────────────

    def on_startup(self) -> None:
        """Called once when the application cartridge is mounted by the plugin engine.

        Override to initialize domain-specific resources (DB connections,
        background tasks, caches).
        """
        pass

    def on_shutdown(self) -> None:
        """Called once when the platform is shutting down cleanly.

        Override to flush queues, close DB sessions, stop background workers.
        """
        pass

    # ── Required Accessors ────────────────────────────────────────────────────

    @abstractmethod
    def get_workflow(self) -> Any:
        """Return the domain LangGraph workflow executor.

        Returns:
            Workflow executor instance with an async execute() method.
        """
        ...

    @abstractmethod
    def get_ui_router(self) -> Any:
        """Return the domain FastAPI APIRouter for admin web interface.

        Returns:
            FastAPI APIRouter with all /admin/apps/{app_id}/* routes.
        """
        ...

    def get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Return tool manifests to register in the Core MCP Server.

        Returns:
            List of tool descriptor dicts with 'name', 'description', 'handler' keys.
        """
        return []

    def get_health_status(self) -> Dict[str, Any]:
        """Return application health metadata for /health heartbeat endpoint.

        Returns:
            Dict with at minimum 'app_id', 'version', 'status' keys.
        """
        return {
            "app_id": self.app_id,
            "name": self.name,
            "version": self.version,
            "status": "operational",
        }
