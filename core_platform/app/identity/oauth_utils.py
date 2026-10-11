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
Platform OAuth Utilities & Credential Introspection.

Adheres strictly to GEES v2.0 Microkernel Architecture (Core contains zero app dependencies).
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from core_platform.app.config import settings
from core_platform.app.security.user_cipher import UserPayloadCipher


import logging

logger = logging.getLogger("core_platform.identity.oauth")


def find_client_credentials(tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Locate client credentials using hierarchical resolution:
    1. Tenant-specific Customer BYOK credentials (if tenant_id provided and configured).
    2. Platform-level environment variables (GOOGLE_CLIENT_ID & GOOGLE_CLIENT_SECRET).
    3. Host-level credentials.json (GOOGLE_CREDENTIALS_PATH or candidate paths).
    """
    # 1. Tenant BYOK Check
    if tenant_id:
        try:
            from ops_control_plane.devops_vault import DevOpsKeyVault
            vault = DevOpsKeyVault()
            tenant_creds = vault.get_tenant_runtime_credentials(tenant_id)
            if tenant_creds and tenant_creds.is_byok and tenant_creds.google_client_id and tenant_creds.google_client_secret:
                return {
                    "client_id": tenant_creds.google_client_id,
                    "client_secret": tenant_creds.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "is_byok": True,
                    "tenant_id": tenant_id,
                }
        except Exception as exc:
            logger.debug("[OAuthUtils] Could not resolve tenant BYOK credentials: %s", exc)

    # 2. Platform Environment Variables Check
    env_client_id = getattr(settings, "GOOGLE_CLIENT_ID", None)
    env_client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", None)
    if env_client_id and env_client_secret and env_client_id.strip() and env_client_secret.strip():
        return {
            "client_id": env_client_id.strip(),
            "client_secret": env_client_secret.strip(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "is_byok": False,
            "source": "environment",
        }

    # 3. Host Credentials JSON Disk Check
    candidates = []
    if settings.GOOGLE_CREDENTIALS_PATH:
        candidates.append(Path(settings.GOOGLE_CREDENTIALS_PATH))
    candidates.extend([
        Path("credentials.json"),
        Path("config/credentials.json"),
        Path("secrets/credentials.json"),
    ])
    for p in candidates:
        if p.exists() and p.is_file():
            try:
                data: Any = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    res = data.get("installed") or data.get("web") or data
                    if isinstance(res, dict):
                        return dict(res)
            except Exception:
                pass
    return None


def encrypt_user_tokens(token_dict: Dict[str, Any], user_salt: str) -> str:
    """Serialize and envelope-encrypt OAuth tokens using user secret salt."""
    raw_json = json.dumps(token_dict)
    return UserPayloadCipher.encrypt_payload(raw_json, user_salt)


def decrypt_user_tokens(encrypted_str: str, user_salt: str) -> Optional[Dict[str, Any]]:
    """Decrypt and deserialize OAuth tokens using user secret salt."""
    decrypted = UserPayloadCipher.decrypt_payload(encrypted_str, user_salt)
    if not decrypted:
        return None
    try:
        data = json.loads(decrypted)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
