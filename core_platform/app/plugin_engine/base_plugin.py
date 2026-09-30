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
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
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

    keywords: List[str] = []
    """Keyword hints for SemanticRouter offline fallback routing.

    The router scores each candidate app by counting how many of its keywords
    appear in the inbound message text and dispatches to the highest scorer.
    Override with domain-specific vocabulary in each cartridge.
    """

    dashboard_url: str = ""
    """Primary web UI entry point for this domain cartridge (e.g. '/admin/apps/mail-organizer/dashboard')."""

    has_poller: bool = False
    """True if this application runs an active background worker or email/message poller."""

    # ── Lifecycle & Poller Methods ────────────────────────────────────────────

    def get_poller_status(self) -> Optional[str]:
        """Return the current runtime status of the cartridge's background poller.

        Returns:
            'RUNNING', 'STOPPED', 'UNAVAILABLE', or None if has_poller is False.
        """
        if not self.has_poller:
            return None
        return "STOPPED"

    def toggle_poller(self) -> Tuple[bool, str]:
        """Start or stop the background poller worker for this cartridge.

        Returns:
            Tuple of (is_running: bool, message: str).
        """
        return False, "Background poller not implemented for this cartridge."

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

    def get_whatsapp_handler(self) -> Optional[Any]:
        """Return the domain-specific WhatsApp message handler for this cartridge.

        The returned object must expose an async ``dispatch(msg, context) -> str``
        method that accepts the parsed WhatsApp message dict and a handler context
        dict (sender_phone, kiosk_id, emp, correlation_id, etc.) and returns the
        reply text string.

        The platform ``whatsapp_router.py`` calls this via the loaded plugin instance,
        making it a pure transport multiplexer with zero domain knowledge.

        Returns:
            Handler object with an async ``dispatch()`` method, or None if this
            cartridge does not handle inbound WhatsApp messages directly.
        """
        return None

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

    def get_metadata(self) -> Optional[Any]:
        """Return the SQLAlchemy MetaData object for Alembic migration discovery.

        Override in cartridges that manage their own DB tables so that the
        platform Alembic env.py can collect metadata dynamically without
        importing app-specific symbols.

        Returns:
            SQLAlchemy MetaData instance, or None if no DB tables are managed.
        """
        return None

    def get_outbox_transmitter(self) -> Optional[Callable[..., Any]]:
        """Return the async coroutine that flushes this app's outbox to downstream.

        Called by the platform OutboxSynchronizer._dispatch_item() to dispatch
        pending records without any hardcoded app-specific knowledge.

        Returns:
            An async callable ``transmitter(target, payload) -> (bool, str)``,
            or None if this app has no outbox integration.
        """
        return None

    def get_pending_outbox_count(self) -> int:
        """Return the count of pending (unsynced) outbox records for /health reporting.

        Override in cartridges that maintain an outbox to surface pending record
        counts in the platform heartbeat without importing app-specific DB services.

        Returns:
            Integer count of pending outbox items (0 when not applicable).
        """
        return 0

    def get_convenience_routes(self) -> List[Tuple[str, str, Any]]:
        """Return shortcut URL routes to register at the platform root level.

        Each entry is a tuple of (http_method, path, handler_callable).
        The platform main.py iterates these at startup and registers them
        on the root FastAPI app — eliminating hardcoded per-app route blocks.

        Example::

            return [
                ("GET", "/loc", view_verify_location),
                ("POST", "/api/verify-location", verify_location_api),
            ]

        Returns:
            List of (method, path, handler) tuples; empty list by default.
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
            "pending_outbox": self.get_pending_outbox_count(),
        }
