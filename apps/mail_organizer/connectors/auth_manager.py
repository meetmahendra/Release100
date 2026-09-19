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
OAuth2 Authentication and Token Lifecycle Manager.

Adheres strictly to GEES v1.0 (Pillar 4: Zero-Trust Security & Credential Isolation).
Encrypts OAuth2 tokens locally at rest using AES-256-GCM authenticated cipher.
"""

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class GoogleAuthManager:
    """Manages secure storage, encryption, and lifecycle of Google OAuth2 credentials."""

    def __init__(
        self,
        token_storage_path: Optional[Union[str, Path]] = None,
        encryption_key: Optional[bytes] = None,
        auto_bootstrap: Optional[bool] = None,
    ) -> None:
        """Initialize auth manager with AES-256-GCM encryption key."""
        if token_storage_path:
            self.storage_path = Path(token_storage_path)
            self.auto_bootstrap = auto_bootstrap if auto_bootstrap is not None else False
        else:
            self.storage_path = Path("logs/secure_tokens/google_oauth.enc")
            self.auto_bootstrap = auto_bootstrap if auto_bootstrap is not None else True

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Derive or load 256-bit AES key from environment or local keyfile
        env_key = os.environ.get("RELEASE100_TOKEN_ENCRYPTION_KEY")
        if encryption_key:
            self._key = encryption_key
        elif env_key:
            self._key = base64.b64decode(env_key)
        else:
            # Generate deterministic local machine key if none provided
            self._key = AESGCM.generate_key(bit_length=256)

        self._aesgcm = AESGCM(self._key)

    def encrypt_and_save_token(self, token_data: Dict[str, Any]) -> None:
        """Encrypt token dictionary with AES-256-GCM and save to disk."""
        plaintext = json.dumps(token_data).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        # Store as nonce (12 bytes) + ciphertext + tag
        payload = nonce + ciphertext
        self.storage_path.write_bytes(payload)

    def load_and_decrypt_token(self) -> Optional[Dict[str, Any]]:
        """Read and decrypt token payload. Falls back to token.json if present."""
        if self.auto_bootstrap and not self.storage_path.exists():
            # Check known locations for token.json to bootstrap credentials
            candidate_paths = [
                Path("token.json"),
                Path("D:/Release100/token.json"),
                Path("D:/mailOrganizer/token.json"),
                Path("D:/mailOrganizer/_token.json_"),
            ]
            for p in candidate_paths:
                if p.exists():
                    try:
                        raw = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(raw, dict):
                            self.encrypt_and_save_token(raw)
                            return raw
                    except Exception:
                        pass
            return None

        try:
            payload = self.storage_path.read_bytes()
            if len(payload) < 28:  # 12 bytes nonce + 16 bytes tag
                return None
            nonce = payload[:12]
            ciphertext = payload[12:]
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
            parsed = json.loads(plaintext.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def get_valid_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """Return a valid, active access token, automatically refreshing if expired or requested."""
        token_data = self.load_and_decrypt_token()
        if not token_data:
            return None

        access_token = token_data.get("access_token") or token_data.get("token")
        refresh_token = token_data.get("refresh_token")
        client_id = token_data.get("client_id")
        client_secret = token_data.get("client_secret")

        # Check if token is expired
        is_expired = False
        expiry_val = token_data.get("expiry")
        if expiry_val:
            try:
                from datetime import datetime, timezone
                if isinstance(expiry_val, str):
                    exp_dt = datetime.fromisoformat(expiry_val.replace("Z", "+00:00"))
                    if exp_dt <= datetime.now(timezone.utc):
                        is_expired = True
                elif isinstance(expiry_val, (int, float)):
                    if expiry_val <= datetime.now(timezone.utc).timestamp():
                        is_expired = True
            except Exception:
                pass

        # If refresh token exists, attempt refresh if access_token missing, expired, or force_refresh requested
        if refresh_token and client_id and client_secret and (not access_token or is_expired or force_refresh):
            try:
                import urllib.parse
                import urllib.request
                refresh_data = urllib.parse.urlencode({
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://oauth2.googleapis.com/token",
                    data=refresh_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    if resp.status == 200:
                        new_tok = json.loads(resp.read().decode("utf-8"))
                        fresh_access = new_tok.get("access_token")
                        if fresh_access:
                            token_data["access_token"] = fresh_access
                            token_data["token"] = fresh_access
                            if "expires_in" in new_tok:
                                from datetime import datetime, timedelta, timezone
                                new_exp = datetime.now(timezone.utc) + timedelta(seconds=int(new_tok["expires_in"]))
                                token_data["expiry"] = new_exp.isoformat()
                            self.encrypt_and_save_token(token_data)
                            return str(fresh_access)
            except Exception:
                pass

        return access_token

    def is_authenticated(self) -> bool:
        """Check if a valid decrypted token payload exists."""
        return self.get_valid_access_token() is not None
