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

"""Synthetic Unit Tests for InteractionEnvelope (Plan 02 v1.3)."""

from core_platform.app.ingress.envelope import (
    ChannelType,
    InteractionEnvelope,
    MediaAttachment,
)


def test_interaction_envelope_creation() -> None:
    """InteractionEnvelope must generate UUIDs and derive session_id automatically."""
    env = InteractionEnvelope(
        channel=ChannelType.WHATSAPP,
        sender_id="+919800011122",
        text_content="Duty check-in",
        kiosk_id="NODE-PUNE-04",
    )
    assert env.envelope_id != ""
    assert env.session_id == f"{env.tenant_id}:whatsapp:+919800011122"
    assert env.kiosk_id == "NODE-PUNE-04"
    assert len(env.attachments) == 0


def test_interaction_envelope_with_media() -> None:
    """InteractionEnvelope must carry attachments with media metadata."""
    attachment = MediaAttachment(
        media_id="wa_media_12345",
        media_type="image/jpeg",
        raw_bytes=b"\xff\xd8\xff\xe0",
        sha256_hash="dummy_hash",
    )
    env = InteractionEnvelope(
        channel=ChannelType.WHATSAPP,
        sender_id="+919800011122",
        attachments=[attachment],
    )
    assert len(env.attachments) == 1
    assert env.attachments[0].media_id == "wa_media_12345"
