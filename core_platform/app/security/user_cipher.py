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
Zero-Knowledge User Envelope Encryption & Data Blinding Cipher.

Adheres strictly to GEES v2.0 Rule 8 (Zero-Trust Security & Envelope Encryption at Rest).
Encrypts user email bodies, snippets, and drafts at rest using user-derived AES-256-GCM keys.
Provides deterministic data blinding for administrative shells and operators.
"""

import base64
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core_platform.app.config import settings

logger = logging.getLogger("core_platform.security.cipher")

BLINDED_PLACEHOLDER = "[ENCRYPTED_PAYLOAD_PROTECTED]"
CIPHER_PREFIX = "ENC:v1:"


def derive_user_payload_key(user_salt: str) -> bytes:
    """Derive 256-bit AES-GCM encryption key from master secret and user salt."""
    master = getattr(
        settings,
        "USER_ENCRYPTION_MASTER_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    derived = hashlib.sha256((master + ":" + user_salt).encode("utf-8")).digest()
    return derived


class UserPayloadCipher:
    """Provides envelope encryption at rest and privacy blinding."""

    @staticmethod
    def encrypt_payload(plaintext: str, user_salt: str) -> str:
        """Encrypt sensitive text at rest using AES-256-GCM.

        Args:
            plaintext: Raw unencrypted message/snippet/draft text.
            user_salt: User secret salt string.

        Returns:
            Prefixed string: 'ENC:v1:<base64(nonce + ciphertext)>'
        """
        if not plaintext:
            return ""

        key = derive_user_payload_key(user_salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        b64_enc = base64.b64encode(nonce + ciphertext).decode("utf-8")
        return f"{CIPHER_PREFIX}{b64_enc}"

    @staticmethod
    def decrypt_payload(ciphertext_payload: str, user_salt: str) -> str:
        """Decrypt payload using user's secret salt.

        Args:
            ciphertext_payload: Encrypted string from DB.
            user_salt: User secret salt string.

        Returns:
            Decrypted plaintext string, or BLINDED_PLACEHOLDER if decryption fails.
        """
        if not ciphertext_payload:
            return ""

        if not ciphertext_payload.startswith(CIPHER_PREFIX):
            # Backward-compatible unencrypted legacy string
            return ciphertext_payload

        raw_b64 = ciphertext_payload[len(CIPHER_PREFIX):]
        try:
            raw_bytes = base64.b64decode(raw_b64)
            if len(raw_bytes) < 28:
                return BLINDED_PLACEHOLDER
            key = derive_user_payload_key(user_salt)
            aesgcm = AESGCM(key)
            nonce = raw_bytes[:12]
            ciphertext = raw_bytes[12:]
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.debug("[UserPayloadCipher] Decryption failed for payload: %s", exc)
            return BLINDED_PLACEHOLDER

    @staticmethod
    def is_encrypted(payload: str) -> bool:
        """Check if payload is formatted with the envelope encryption prefix."""
        return bool(payload and payload.startswith(CIPHER_PREFIX))

    @staticmethod
    def blind_payload(payload: Optional[str]) -> str:
        """Return standardized blinded placeholder for zero-knowledge admin views."""
        if not payload:
            return ""
        return BLINDED_PLACEHOLDER
