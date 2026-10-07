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

from core_platform.app.security.user_cipher import UserPayloadCipher


def find_client_credentials() -> Optional[Dict[str, Any]]:
    """Locate client credentials from standard candidate paths."""
    candidates = [
        Path("credentials.json"),
        Path("config/credentials.json"),
        Path("D:/mailOrganizer/credentials.json"),
        Path("D:/Release100/credentials.json"),
    ]
    for p in candidates:
        if p.exists():
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
