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
Canonical Interaction Envelope Definition.

Provides channel-agnostic message normalization across WhatsApp, Email,
Web Kiosk, Background Pollers, and Model Context Protocol (MCP) agents.
Adheres to Plan 02 v1.3 with distributed correlation_id tracing.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    """Supported input transport channels."""

    WHATSAPP = "whatsapp"
    EMAIL = "email"
    WEB_KIOSK = "web_kiosk"
    MCP_AGENT = "mcp_agent"
    BACKGROUND_POLLER = "background_poller"


class MediaAttachment(BaseModel):
    """Represents a media attachment (photo, document, audio) in an interaction."""

    media_id: Optional[str] = Field(default=None, description="External provider media ID")
    media_type: str = Field(description="MIME type, e.g., 'image/jpeg', 'image/png'")
    raw_bytes: Optional[bytes] = Field(default=None, description="Raw binary content")
    media_url: Optional[str] = Field(default=None, description="Downloader URL or local path")
    sha256_hash: Optional[str] = Field(default=None, description="Cryptographic hash of media bytes")


class InteractionEnvelope(BaseModel):
    """
    Canonical normalized message envelope processed by the Release100 platform.

    Carries unified metadata, identity context, attachments, and a distributed
    correlation_id that connects ingress, LangGraph nodes, and audit entries.
    """

    envelope_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique UUID for this specific envelope instance",
    )
    correlation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Distributed tracing ID preserved across full transaction lifecycle",
    )
    tenant_id: str = Field(
        default="canectar_foods",
        description="Multi-tenant identifier for enterprise isolation",
    )
    kiosk_id: Optional[str] = Field(
        default=None,
        description="Physical kiosk/station identifier (e.g. 'CANEBOT-PUNE-04')",
    )
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of envelope creation",
    )
    channel: ChannelType = Field(
        description="Ingress transport channel",
    )
    sender_id: str = Field(
        description="Normalized sender identifier (E.164 phone number, email address, or API key ID)",
    )
    text_content: Optional[str] = Field(
        default=None,
        description="Normalized text body or prompt",
    )
    attachments: List[MediaAttachment] = Field(
        default_factory=list,
        description="List of attached media payloads",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Channel-specific or diagnostic metadata dictionary",
    )
    session_id: str = Field(
        default="",
        description="Concurrency lock key, defaults to 'tenant_id:channel:sender_id'",
    )

    def model_post_init(self, __context: Any) -> None:
        """Derive session_id automatically if not explicitly provided."""
        if not self.session_id:
            self.session_id = f"{self.tenant_id}:{self.channel.value}:{self.sender_id}"
