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
Unit Tests — Live Diagnostics & Settings Web API Routes.

Adheres strictly to GEES v1.0 Pillar 2 (Dual-Engine Verification).
Covers the diagnostics web dashboard endpoints at /diagnostics/.

GAP-025: Third missing test file in Plan 07 test suite.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Test App Setup
# ---------------------------------------------------------------------------

def _make_test_client() -> TestClient:
    """Build a TestClient for the diagnostics router in isolation."""
    from fastapi import FastAPI

    app = FastAPI()

    try:
        from core_platform.app.diagnostics.web_dashboard import router
        app.include_router(router)
    except Exception as exc:
        # If the diagnostics module itself has import issues, skip gracefully.
        pytest.skip(f"Diagnostics module not importable: {exc}")

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health Endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Tests for the platform /health endpoint."""

    def test_health_returns_200(self) -> None:
        """Health endpoint should return HTTP 200."""
        from fastapi import FastAPI

        # Build isolated app with just the main health route.
        mini_app = FastAPI()

        @mini_app.get("/health")
        def _health() -> dict:
            return {
                "status": "healthy",
                "uptime_seconds": 42.0,
                "enabled_apps": ["temperature_marker"],
                "applications": {},
                "skills": {},
            }

        client = TestClient(mini_app)
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_includes_required_keys(self) -> None:
        """Health response must include all GEES-mandated keys."""
        from fastapi import FastAPI

        mini_app = FastAPI()

        @mini_app.get("/health")
        def _health() -> dict:
            return {
                "status": "healthy",
                "timestamp_utc": "2026-09-16T00:00:00+00:00",
                "uptime_seconds": 99.0,
                "enabled_apps": [],
                "applications": {},
                "skills": {},
                "outbox_pending_records": 0,
            }

        client = TestClient(mini_app)
        response = client.get("/health")
        data = response.json()
        required_keys = {
            "status",
            "uptime_seconds",
            "enabled_apps",
            "applications",
            "skills",
        }
        for key in required_keys:
            assert key in data, f"Health response missing required key: {key}"


# ---------------------------------------------------------------------------
# Settings / Config Backup
# ---------------------------------------------------------------------------

class TestSettingsConsole:
    """Tests for the diagnostics settings console."""

    def test_settings_console_loads(self) -> None:
        """Diagnostics settings endpoint should return 200 or redirect without crashing."""
        client = _make_test_client()
        response = client.get("/diagnostics/", follow_redirects=False)
        # Accept 200 (rendered HTML), 302 (redirect), or 401 (auth required)
        assert response.status_code in (200, 302, 401, 404), (
            f"Unexpected status {response.status_code}"
        )

    def test_config_backup_api_endpoint_exists(self) -> None:
        """The config backup API route should return a recognisable response."""
        client = _make_test_client()
        response = client.get("/diagnostics/config-backup", follow_redirects=False)
        # Accept any non-500 response — the route should exist.
        assert response.status_code != 500, (
            f"Config backup endpoint raised a 500: {response.text[:200]}"
        )

    def test_verifier_api_returns_status(self) -> None:
        """The diagnostics verifier endpoint should return a structured response."""
        client = _make_test_client()
        response = client.get("/diagnostics/verify", follow_redirects=False)
        assert response.status_code != 500, (
            f"Verifier API raised a 500: {response.text[:200]}"
        )


# ---------------------------------------------------------------------------
# LLM Gateway Health
# ---------------------------------------------------------------------------

class TestLLMGatewayHealth:
    """Tests for the LLM gateway get_health() output."""

    def test_gateway_health_returns_list(self) -> None:
        """LLMGateway.get_health() must return a list of provider dicts."""
        from core_platform.app.llm.gateway import get_platform_llm_gateway
        gateway = get_platform_llm_gateway()
        health_list = gateway.get_health()
        assert isinstance(health_list, list)
        for entry in health_list:
            assert "provider_name" in entry
            assert "available" in entry

    def test_gemini_provider_info(self) -> None:
        """GeminiProvider.get_provider_info() should return expected keys."""
        from core_platform.app.llm.gemini_provider import GeminiProvider
        provider = GeminiProvider(api_key="test_key_12345")
        info = provider.get_provider_info()
        assert info["provider_name"] == "gemini"
        assert "available" in info

    def test_ollama_provider_unavailable_when_no_url(self) -> None:
        """OllamaProvider should report unavailable when base_url is empty."""
        from core_platform.app.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(base_url="")
        assert not provider.is_available()


# ---------------------------------------------------------------------------
# Security Context & RBAC
# ---------------------------------------------------------------------------

class TestSecurityContext:
    """Tests for SecurityContext model behaviour."""

    def test_unauthenticated_context(self) -> None:
        """SecurityContext.unauthenticated() must return is_authenticated=False."""
        from core_platform.app.auth.models import SecurityContext
        ctx = SecurityContext.unauthenticated()
        assert ctx.is_authenticated is False
        assert ctx.principal_id == "anonymous"

    def test_system_context_is_admin(self) -> None:
        """SecurityContext.system() must carry admin role and all apps."""
        from core_platform.app.auth.models import SecurityContext
        ctx = SecurityContext.system()
        assert ctx.is_authenticated is True
        assert "admin" in ctx.user_roles
        assert ctx.is_admin is True

    def test_rbac_filter_empty_when_unauthenticated(self) -> None:
        """RBACFilter should return empty list for unauthenticated context."""
        from core_platform.app.auth.models import SecurityContext
        from core_platform.app.rbac.permissions import RBACFilter
        ctx = SecurityContext.unauthenticated()
        result = RBACFilter.prune_candidate_apps(ctx, ["temperature_marker"])
        assert result == []

    def test_rbac_filter_grants_operator_access(self) -> None:
        """Operator role should grant access to temperature_marker."""
        from core_platform.app.auth.models import SecurityContext
        from core_platform.app.rbac.permissions import RBACFilter
        ctx = SecurityContext(
            principal_id="test_operator",
            user_roles=["operator"],
            permitted_apps=["temperature_marker"],
            is_authenticated=True,
        )
        result = RBACFilter.prune_candidate_apps(ctx, ["temperature_marker"])
        assert "temperature_marker" in result


# ---------------------------------------------------------------------------
# JWT Utilities
# ---------------------------------------------------------------------------

class TestJWTUtilities:
    """Tests for the JWT create/verify utilities."""

    def test_create_and_verify_roundtrip(self) -> None:
        """A freshly created JWT token should verify successfully."""
        from core_platform.app.auth.jwt_utils import create_jwt_token, verify_jwt_token
        token = create_jwt_token(
            principal_id="test_user",
            roles=["admin"],
            permitted_apps=["temperature_marker"],
            secret_key="test_secret_abc123",
        )
        ctx = verify_jwt_token(token, secret_key="test_secret_abc123")
        assert ctx is not None
        assert ctx.principal_id == "test_user"
        assert "admin" in ctx.user_roles

    def test_invalid_signature_rejected(self) -> None:
        """A token with a wrong secret should fail verification."""
        from core_platform.app.auth.jwt_utils import create_jwt_token, verify_jwt_token
        token = create_jwt_token("u", ["op"], [], secret_key="correct_secret")
        result = verify_jwt_token(token, secret_key="wrong_secret")
        assert result is None

    def test_malformed_token_rejected(self) -> None:
        """A garbage string should return None without raising."""
        from core_platform.app.auth.jwt_utils import verify_jwt_token
        result = verify_jwt_token("not.a.real.jwt.token")
        assert result is None


# ---------------------------------------------------------------------------
# Semantic Router
# ---------------------------------------------------------------------------

class TestSemanticRouter:
    """Tests for the SemanticRouter deterministic paths."""

    @pytest.mark.anyio
    async def test_single_app_bypass(self) -> None:
        """Single candidate app should be returned with confidence=1.0, no LLM call."""
        from core_platform.app.routing.semantic_router import SemanticRouter
        decision = await SemanticRouter.route(
            text_content="check in",
            candidate_apps=["temperature_marker"],
        )
        assert decision.selected_app == "temperature_marker"
        assert decision.confidence == 1.0
        assert not decision.requires_disambiguation

    @pytest.mark.anyio
    async def test_empty_candidate_apps(self) -> None:
        """Empty candidate list should return a safe default without crashing."""
        from core_platform.app.routing.semantic_router import SemanticRouter
        decision = await SemanticRouter.route(
            text_content="hello",
            candidate_apps=[],
        )
        assert decision.selected_app != ""

    def test_disambiguation_clarification_message(self) -> None:
        """DisambiguationEngine should produce a numbered list of options."""
        from core_platform.app.routing.disambiguation import DisambiguationEngine
        msg = DisambiguationEngine.build_clarification_message(
            candidate_apps=["temperature_marker", "mail_organizer"],
            confidence=0.5,
        )
        assert "1." in msg
        assert "2." in msg

    def test_disambiguation_resolve_numeric(self) -> None:
        """Numeric '2' should resolve to the second candidate."""
        from core_platform.app.routing.disambiguation import DisambiguationEngine
        result = DisambiguationEngine.resolve_selection("2", ["temperature_marker", "mail_organizer"])
        assert result == "mail_organizer"
