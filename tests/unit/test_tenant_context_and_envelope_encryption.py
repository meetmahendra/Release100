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
Unit Test Suite for UserContext, ContextVar Scoping, and Zero-Knowledge AES-256-GCM Envelope Encryption.
"""

from pathlib import Path
import shutil
import tempfile
from typing import Generator
import pytest
from sqlalchemy import text

from apps.mail_organizer.database.db_service import MailDatabaseService
from core_platform.app.middleware.tenant_context import (
    UserContext,
    async_user_scope,
    get_current_user_context,
    reset_user_context,
    set_current_user_context,
    user_scope,
)
from core_platform.app.security.user_cipher import (
    BLINDED_PLACEHOLDER,
    CIPHER_PREFIX,
    UserPayloadCipher,
    derive_user_payload_key,
)


@pytest.fixture
def temp_mail_db() -> Generator[MailDatabaseService, None, None]:
    """Provide isolated SQLite database for mail service tests."""
    temp_dir = tempfile.mkdtemp()
    db_file = Path(temp_dir) / "test_mail_isolated.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    service = MailDatabaseService(db_url=db_url)
    yield service
    service.close()
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestUserContextAndScoping:
    """Test UserContext immutable structure and thread-safe ContextVar management."""

    def test_user_context_set_get_reset(self) -> None:
        ctx = UserContext(
            user_id=101,
            phone_number="+15551234567",
            tenant_id="tenant_x",
            full_name="Alice Context",
            role="operator",
            user_secret_salt="salt_1234567890abcdef",
            allowed_cartridges=("mail_organizer",),
        )

        assert get_current_user_context() is None

        token = set_current_user_context(ctx)
        current = get_current_user_context()
        assert current is not None
        assert current.user_id == 101
        assert current.phone_number == "+15551234567"
        assert current.tenant_id == "tenant_x"
        assert current.user_secret_salt == "salt_1234567890abcdef"

        reset_user_context(token)
        assert get_current_user_context() is None

    def test_user_scope_context_manager(self) -> None:
        ctx = UserContext(
            user_id=202,
            phone_number="+15559876543",
            tenant_id="tenant_y",
            user_secret_salt="salt_y_secret_999",
        )

        assert get_current_user_context() is None
        with user_scope(ctx) as bound_ctx:
            assert bound_ctx.user_id == 202
            assert get_current_user_context() == ctx

        assert get_current_user_context() is None

    @pytest.mark.asyncio
    async def test_async_user_scope(self) -> None:
        ctx = UserContext(
            user_id=303,
            phone_number="+15550009999",
            tenant_id="tenant_z",
            user_secret_salt="salt_z_async",
        )

        assert get_current_user_context() is None
        async with async_user_scope(ctx) as bound_ctx:
            assert bound_ctx.user_id == 303
            assert get_current_user_context() == ctx

        assert get_current_user_context() is None


class TestUserPayloadCipher:
    """Test AES-256-GCM envelope encryption, key derivation, and zero-knowledge blinding."""

    def test_encryption_and_decryption_success(self) -> None:
        user_salt = "user_salt_abc_123"
        secret_body = "Confidential financial results: Q3 Revenue reached $45M."

        encrypted = UserPayloadCipher.encrypt_payload(secret_body, user_salt)
        assert encrypted.startswith(CIPHER_PREFIX)
        assert secret_body not in encrypted

        decrypted = UserPayloadCipher.decrypt_payload(encrypted, user_salt)
        assert decrypted == secret_body

    def test_cross_user_isolation_prevent_decryption(self) -> None:
        user_salt_alice = "user_salt_alice_secret_1"
        user_salt_bob = "user_salt_bob_secret_2"
        secret_payload = "Strictly private executive memo from Alice."

        encrypted_alice = UserPayloadCipher.encrypt_payload(secret_payload, user_salt_alice)

        # Bob attempts to decrypt Alice's payload
        bob_attempt = UserPayloadCipher.decrypt_payload(encrypted_alice, user_salt_bob)
        # Decryption must fail and safely return blinded placeholder (ZERO leakage)
        assert bob_attempt == BLINDED_PLACEHOLDER
        assert secret_payload not in bob_attempt

    def test_legacy_unencrypted_passthrough(self) -> None:
        legacy_text = "Standard unencrypted legacy message"
        decrypted = UserPayloadCipher.decrypt_payload(legacy_text, "any_salt")
        assert decrypted == legacy_text

    def test_blinding_utility(self) -> None:
        assert UserPayloadCipher.blind_payload("sensitive") == BLINDED_PLACEHOLDER
        assert UserPayloadCipher.blind_payload("") == ""


class TestMailDatabaseEnvelopeEncryption:
    """Test database persistence of envelope-encrypted emails and drafts."""

    def test_email_encrypted_at_rest(self, temp_mail_db: MailDatabaseService) -> None:
        user_salt = "tenant_alpha_salt_777"
        plain_body = "Project Falcon launch date is confirmed for Friday."
        plain_snippet = "Project Falcon launch..."

        # Store email with user salt
        email = temp_mail_db.store_email(
            gmail_id="gmail_msg_enc_01",
            thread_id="thread_01",
            subject="Project Falcon Update",
            sender="sarah@example.com",
            snippet=plain_snippet,
            body=plain_body,
            user_salt=user_salt,
        )

        assert email.gmail_id == "gmail_msg_enc_01"
        assert email.body.startswith(CIPHER_PREFIX)
        assert email.snippet.startswith(CIPHER_PREFIX)
        assert plain_body not in email.body

        # Verify raw SQL query directly against database has zero plaintext
        with temp_mail_db.get_session() as session:
            raw_row = session.execute(
                text("SELECT body, snippet FROM mail_emails WHERE gmail_id = 'gmail_msg_enc_01';")
            ).fetchone()
            assert raw_row is not None
            raw_body, raw_snippet = raw_row[0], raw_row[1]
            assert raw_body.startswith(CIPHER_PREFIX)
            assert plain_body not in raw_body
            assert plain_snippet not in raw_snippet


        # Query without user context / salt -> Blinded for zero-knowledge admin view
        admin_emails = temp_mail_db.get_recent_emails(limit=10, decrypt_salt=None)
        assert len(admin_emails) == 1
        assert admin_emails[0]["body"] == BLINDED_PLACEHOLDER
        assert admin_emails[0]["snippet"] == BLINDED_PLACEHOLDER

        # Query with user context salt -> Decrypted plaintext
        user_emails = temp_mail_db.get_recent_emails(limit=10, decrypt_salt=user_salt)
        assert len(user_emails) == 1
        assert user_emails[0]["body"] == plain_body
        assert user_emails[0]["snippet"] == plain_snippet

    def test_draft_encrypted_at_rest(self, temp_mail_db: MailDatabaseService) -> None:
        user_salt = "tenant_draft_salt_888"
        plain_draft = "Hi Sarah, thank you for the update. I will prepare the slides."

        draft = temp_mail_db.store_draft(
            gmail_id="gmail_msg_enc_02",
            thread_id="thread_02",
            recipient="sarah@example.com",
            subject="Re: Project Falcon Update",
            body=plain_draft,
            user_salt=user_salt,
        )

        assert draft.body.startswith(CIPHER_PREFIX)
        assert plain_draft not in draft.body
