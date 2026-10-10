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
Platform Configuration Subsystem.

Uses pydantic-settings to load typed configurations from environment
variables with safe defaults. Adheres to GEES v1.0 fail-safe defaults (DRY_RUN=True).
"""

import os
from pathlib import Path
from typing import List, Literal, Optional
import re
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    """Global configuration settings for the Release100 platform."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Operational Identity & Node Defaults (Domain-neutral core defaults)
    ORGANIZATION_NAME: str = Field(default="Release100 Organization", description="Client organization name")
    STATION_NAME: str = Field(default="Release100 Node #01", description="Friendly station or facility display name")
    NODE_ID: str = Field(default="NODE-01", description="Unique physical or logical host node identifier")
    KIOSK_ID: str = Field(default="NODE-01", description="Alias for NODE_ID (backward-compatible host identifier)")
    TENANT_ID: str = Field(default="default_tenant", description="Multi-tenant identifier")

    # Safety & Execution Modes (GEES v1.0 Section 2.3)
    # Starts in Shadow Mode (DRY_RUN=True) by default for fail-safe verification
    DRY_RUN: bool = Field(default=True, description="When True, prevents destructive actions and simulates commits")
    EXECUTION_MODE: str = Field(default="shadow", description="Operating mode: shadow | assistive | autonomous")
    CONFIDENCE_THRESHOLD: float = Field(default=0.85, description="Confidence threshold below which actions divert to review")

    # Pluggable LLM Gateway Defaults (Vendor-neutral)
    DEFAULT_LLM_PROVIDER: str = Field(default="gemini", description="Default provider: gemini | claude | openai | ollama")
    DEFAULT_DECISION_PROVIDER: str = Field(default="typesafe", description="Default System 1 decision provider: typesafe | gemini | heuristic")
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API Key")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash", description="Default Gemini model")
    GEMINI_ROUTING_MODEL: str = Field(default="gemini-2.5-flash", description="Configurable routing model")
    GEMINI_VISION_MODEL: str = Field(default="gemini-2.5-flash", description="Configurable vision OCR model")

    # TypeSafe AI / Jev System 1 Decision Engine Settings
    TYPESAFE_API_KEY: str = Field(default="", description="TypeSafe AI API key for fast decision & routing models")
    TYPESAFE_BASE_URL: str = Field(default="https://api.typesafe.ai/v1", description="TypeSafe AI API base URL")
    TYPESAFE_MODEL: str = Field(default="jev-latest", description="Default TypeSafe decision model (e.g. jev-latest, jev-1)")

    # Server Ports
    ORCHESTRATOR_PORT: int = Field(default=8002, description="Main FastAPI host and admin shell port")
    MCP_SERVER_PORT: int = Field(default=8001, description="Native SSE MCP server port")

    # Pluggable Database Configuration (GEES v2.0 Deployment-Time Database Selection)
    DATABASE_URL: str = Field(
        default="sqlite:///logs/platform_data.db",
        description="Universal database connection URL (sqlite, postgresql, mysql, timescaledb, etc.)",
    )
    DB_POOL_SIZE: int = Field(default=20, description="Connection pool size for client-server SQL engines")
    DB_MAX_OVERFLOW: int = Field(default=10, description="Max overflow connections beyond pool size")

    # Active Cartridges Whitelist (GEES v2.0 Rule 4: zero hardcoded domain cartridges)
    ENABLED_APPLICATIONS: Optional[List[str]] = Field(
        default=None,
        description="Optional list of active application cartridges. If None, all discovered cartridges are loaded.",
    )

    # Audit & Telemetry Directories
    BASE_DIR: Path = Field(
        default_factory=lambda: Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        description="Platform base directory",
    )
    AUDIT_DIR: Path = Field(
        default_factory=lambda: Path("logs/audit_partitions"),
        description="Directory storing partitioned audit files",
    )

    # Biometrics & Security (ISSUE-001 Commercial Compliance & SEC-2)
    JWT_SECRET_KEY: str = Field(
        default="release100_dev_secret_change_in_prod",
        description="HMAC secret key for HS256 JWT tokens",
    )
    FACE_MODEL_SOURCE: str = Field(
        default="mobilefacenet_open",
        description="Face recognition model: mobilefacenet_open | custom_trained | cloud_vision",
    )
    BIOMETRIC_ENCRYPTION_KEY: str = Field(
        default="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        description="256-bit hex key for AES-256-GCM biometric vector encryption",
    )

    # WhatsApp Cloud API & Ingress
    WHATSAPP_VERIFY_TOKEN: str = Field(
        default="apex_verify_token_2026",
        description="Meta webhook verify token",
    )
    WHATSAPP_APP_SECRET: str = Field(
        default="",
        description="Meta app secret for HMAC-SHA256 verification",
    )
    WHATSAPP_ACCESS_TOKEN: str = Field(
        default="",
        description="Meta Cloud API System User access token",
    )
    WHATSAPP_PHONE_NUMBER_ID: str = Field(
        default="",
        description="Meta Cloud API Phone Number ID",
    )
    SUPERVISOR_PHONE: str = Field(
        default="+919800000000",
        description="Default supervisor phone for escalated operator alerts",
    )

    # Cloud Relay Settings (Outbound Zero-Inbound WebSocket Bridge)
    RELAY_WS_URL: str = Field(
        default="",
        description="Outbound WebSocket URL to Cloudflare/Render edge relay (e.g. wss://relay.example.com/ws/NODE-01)",
    )
    RELAY_RECONNECT_INTERVAL_SECONDS: int = Field(
        default=5,
        description="Base interval in seconds between relay reconnection attempts",
    )
    # Downstream Enterprise Telemetry Endpoint
    DOWNSTREAM_REST_URL: str = Field(
        default="",
        description="Enterprise downstream ingest endpoint for operational telemetry",
    )
    OUTBOX_DRAIN_INTERVAL_SECONDS: int = Field(
        default=30,
        description="Interval in seconds for draining offline outbox records",
    )
    # Distributed Messaging & Task Queue (Phase 2)
    REDIS_URL: str = Field(
        default="",
        description="Redis connection URL for distributed streams and task queue (e.g. redis://localhost:6379/0)",
    )

    # Enterprise Observability & OpenTelemetry (Phase 3)
    OTEL_ENABLED: bool = Field(
        default=False,
        description="Enable OpenTelemetry distributed tracing across all ingress and pipeline components",
    )
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="",
        description="OTLP collector endpoint (e.g. http://localhost:4317 or http://localhost:4318/v1/traces)",
    )
    OTEL_SERVICE_NAME: str = Field(
        default="release100-platform",
        description="Service name reported in distributed trace spans",
    )

    # Public-facing base URL for reverse-proxy deployments (used by MCP SSE endpoint URL construction)
    # Leave empty for direct / LAN deployments — endpoint URL will be derived from the request.
    ORCHESTRATOR_BASE_URL: str = Field(
        default="",
        description="Public base URL (e.g. 'https://node.example.com') for reverse-proxy deployments",
    )

    # Multi-Tenant Zero-Trust Identity & Magic Links (GEES v2.0)
    WHATSAPP_REQUIRE_REGISTRATION: bool = Field(
        default=False,
        description="Strictly require pre-registered user record for inbound WhatsApp messages",
    )
    USER_ENCRYPTION_MASTER_KEY: str = Field(
        default="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        description="Master secret for deriving per-user payload encryption keys",
    )
    MAGIC_LINK_EXPIRY_MINUTES: int = Field(
        default=15,
        description="Expiry time in minutes for WhatsApp Google OAuth Magic Links",
    )
    GOOGLE_CREDENTIALS_PATH: str = Field(
        default="credentials.json",
        description="Path to Google OAuth client credentials JSON file",
    )

    # Decentralized Entitlement Architecture (Plan 10)
    ENTITLEMENT_ENFORCEMENT_MODE: Literal["off", "shadow", "enforce"] = Field(
        default="shadow",
        description="Entitlement enforcement: off (legacy only) | shadow (log DEA diffs, legacy decides) | enforce",
    )
    ENTITLEMENT_MAX_UNIT_DEPTH: int = Field(
        default=32,
        ge=1,
        le=128,
        description="Maximum organizational unit tree depth traversed during scope checks",
    )
    ENTITLEMENT_MANIFEST_FILENAME: str = Field(
        default="entitlements.json",
        description="File name of the entitlement manifest shipped inside each cartridge package",
    )

    # Unified UI, content SSOT and NLS (Plan 11)
    UI_DEFAULT_LOCALE: str = Field(
        default="en_US",
        description="Locale used when no explicit, cookie or Accept-Language match is found",
    )
    UI_SUPPORTED_LOCALES: List[str] = Field(
        default_factory=lambda: ["en_US"],
        description="Locales the UI may serve, for example [\"en_US\", \"hi_IN\"]",
    )
    UI_LOCALE_COOKIE_NAME: str = Field(
        default="ui_locale",
        description="Name of the cookie that stores the user's chosen UI locale",
    )
    UI_MISSING_KEY_POLICY: Literal["marker", "key"] = Field(
        default="marker",
        description="Missing translation key rendering: marker -> [[key]] | key -> the key itself",
    )

    @field_validator("UI_DEFAULT_LOCALE")
    @classmethod
    def _validate_default_locale(cls, value: str) -> str:
        if re.fullmatch(r"[a-z]{2,3}_[A-Z]{2}", value) is None:
            raise ValueError("UI_DEFAULT_LOCALE must look like en_US")
        return value

    @field_validator("UI_SUPPORTED_LOCALES")
    @classmethod
    def _validate_supported_locales(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("UI_SUPPORTED_LOCALES must not be empty")
        for item in value:
            if re.fullmatch(r"[a-z]{2,3}_[A-Z]{2}", item) is None:
                raise ValueError(f"Invalid locale code: {item}")
        return value

    @model_validator(mode="after")
    def _default_locale_is_supported(self) -> "PlatformSettings":
        if self.UI_DEFAULT_LOCALE not in self.UI_SUPPORTED_LOCALES:
            raise ValueError("UI_DEFAULT_LOCALE must be listed in UI_SUPPORTED_LOCALES")
        return self


# Singleton settings instance
settings = PlatformSettings()

