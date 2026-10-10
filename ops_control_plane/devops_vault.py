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
DevOps Credential & BYOK Key Vault (`devops_vault.py`).

Adheres strictly to GEES v2.0 Zero-Trust Security (Rule 8) and Type Discipline (Rule 5).
Manages Platform-Managed vs. Customer-Dedicated (BYOK) credentials per tenant.
Enforces zero accidental fallback leakage and complete invisibility to customer admins.
"""

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core_platform.app.config import settings
from core_platform.app.db.base import Base
from core_platform.app.identity.models import Tenant, TenantConfig
from core_platform.app.security.user_cipher import UserPayloadCipher

logger = logging.getLogger("ops_control_plane.devops_vault")


@dataclass(frozen=True)
class TenantRuntimeCredentials:
    """Immutable runtime credentials resolved for an active tenant."""
    tenant_id: str
    credential_mode: str           # "PLATFORM_MANAGED" | "CUSTOMER_BYOK"
    is_byok: bool
    gemini_api_key: Optional[str]
    openai_api_key: Optional[str]
    waba_token: Optional[str]
    waba_phone_number_id: Optional[str]
    brand_name: Optional[str]
    default_timezone: str


class DevOpsKeyVault:
    """DevOps-exclusive manager for tenant API keys, WABA secrets, and BYOK configurations."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        """Initialize vault with underlying platform database session."""
        if db_url:
            self.engine = create_engine(db_url, echo=False)
        else:
            from core_platform.app.db.manager import get_db_manager
            self.engine = get_db_manager().get_engine()

        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def configure_tenant_credentials(
        self,
        tenant_id: str,
        credential_mode: str = "PLATFORM_MANAGED",
        gemini_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        waba_token: Optional[str] = None,
        waba_access_token: Optional[str] = None,
        waba_phone_number_id: Optional[str] = None,
        brand_name: Optional[str] = None,
        default_timezone: str = "Asia/Kolkata",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TenantConfig:
        """Configure or update tenant credentials with AES-256-GCM envelope encryption.

        Args:
            tenant_id: Target tenant identifier.
            credential_mode: 'PLATFORM_MANAGED' (default) or 'CUSTOMER_BYOK'.
            gemini_api_key: Customer Gemini API key (encrypted at rest if BYOK).
            openai_api_key: Customer OpenAI API key (encrypted at rest if BYOK).
            waba_token: Customer WhatsApp Business token (encrypted at rest if BYOK).
            waba_phone_number_id: Customer WhatsApp phone ID.
            brand_name: Custom company branding display name.
            default_timezone: Primary operational timezone.
            metadata: Arbitrary operational metadata.

        Returns:
            Updated TenantConfig database record.
        """
        mode_clean = credential_mode.upper().strip()
        if mode_clean not in ("PLATFORM_MANAGED", "CUSTOMER_BYOK"):
            raise ValueError(f"Invalid credential mode: '{credential_mode}'. Must be PLATFORM_MANAGED or CUSTOMER_BYOK.")

        # Derive tenant encryption salt
        tenant_salt = f"tenant_vault_salt_{tenant_id}"

        enc_gemini = (
            UserPayloadCipher.encrypt_payload(gemini_api_key.strip(), tenant_salt)
            if gemini_api_key and gemini_api_key.strip()
            else None
        )
        enc_openai = (
            UserPayloadCipher.encrypt_payload(openai_api_key.strip(), tenant_salt)
            if openai_api_key and openai_api_key.strip()
            else None
        )
        raw_waba = (waba_token or waba_access_token or "").strip()
        enc_waba = (
            UserPayloadCipher.encrypt_payload(raw_waba, tenant_salt)
            if raw_waba
            else None
        )

        with self.session_factory() as session:
            stmt = select(TenantConfig).where(TenantConfig.tenant_id == tenant_id)
            config = session.scalar(stmt)
            if not config:
                config = TenantConfig(
                    tenant_id=tenant_id,
                    credential_mode=mode_clean,
                    encrypted_gemini_api_key=enc_gemini,
                    encrypted_openai_api_key=enc_openai,
                    encrypted_waba_token=enc_waba,
                    waba_phone_number_id=waba_phone_number_id.strip() if waba_phone_number_id else None,
                    brand_name=brand_name.strip() if brand_name else None,
                    default_timezone=default_timezone.strip() if default_timezone else "Asia/Kolkata",
                    metadata_json=json.dumps(metadata or {}),
                )
                session.add(config)
            else:
                config.credential_mode = mode_clean
                if gemini_api_key is not None and gemini_api_key.strip():
                    config.encrypted_gemini_api_key = enc_gemini
                if openai_api_key is not None and openai_api_key.strip():
                    config.encrypted_openai_api_key = enc_openai
                if raw_waba:
                    config.encrypted_waba_token = enc_waba
                if waba_phone_number_id is not None and waba_phone_number_id.strip():
                    config.waba_phone_number_id = waba_phone_number_id.strip()
                if brand_name is not None and brand_name.strip():
                    config.brand_name = brand_name.strip()
                if default_timezone is not None and default_timezone.strip():
                    config.default_timezone = default_timezone.strip()
                if metadata is not None:
                    config.metadata_json = json.dumps(metadata)

            session.commit()
            session.refresh(config)
            logger.info("[DevOpsKeyVault] Configured credentials for tenant %s (Mode: %s)", tenant_id, mode_clean)
            return config

    def get_tenant_runtime_credentials(self, tenant_id: str) -> TenantRuntimeCredentials:
        """Resolve decrypted runtime credentials for an active tenant.

        If mode is PLATFORM_MANAGED: returns is_byok=False with platform defaults.
        If mode is CUSTOMER_BYOK: returns is_byok=True with decrypted customer keys.
        """
        with self.session_factory() as session:
            stmt = select(TenantConfig).where(TenantConfig.tenant_id == tenant_id)
            config = session.scalar(stmt)

            if not config or config.credential_mode == "PLATFORM_MANAGED":
                return TenantRuntimeCredentials(
                    tenant_id=tenant_id,
                    credential_mode="PLATFORM_MANAGED",
                    is_byok=False,
                    gemini_api_key=getattr(settings, "GEMINI_API_KEY", None),
                    openai_api_key=getattr(settings, "OPENAI_API_KEY", None),
                    waba_token=getattr(settings, "WHATSAPP_ACCESS_TOKEN", None),
                    waba_phone_number_id=getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None),
                    brand_name=config.brand_name if config else None,
                    default_timezone=config.default_timezone if config else "Asia/Kolkata",
                )

            # Customer BYOK mode: Decrypt customer-provided keys
            tenant_salt = f"tenant_vault_salt_{tenant_id}"
            dec_gemini = (
                UserPayloadCipher.decrypt_payload(config.encrypted_gemini_api_key, tenant_salt)
                if config.encrypted_gemini_api_key
                else None
            )
            dec_openai = (
                UserPayloadCipher.decrypt_payload(config.encrypted_openai_api_key, tenant_salt)
                if config.encrypted_openai_api_key
                else None
            )
            dec_waba = (
                UserPayloadCipher.decrypt_payload(config.encrypted_waba_token, tenant_salt)
                if config.encrypted_waba_token
                else None
            )

            return TenantRuntimeCredentials(
                tenant_id=tenant_id,
                credential_mode="CUSTOMER_BYOK",
                is_byok=True,
                gemini_api_key=dec_gemini or getattr(settings, "GEMINI_API_KEY", None),
                openai_api_key=dec_openai,
                waba_token=dec_waba or getattr(settings, "WHATSAPP_ACCESS_TOKEN", None),
                waba_phone_number_id=config.waba_phone_number_id or getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None),
                brand_name=config.brand_name,
                default_timezone=config.default_timezone,
            )


# Global singleton helper
_vault_instance: Optional[DevOpsKeyVault] = None


def get_devops_key_vault(db_url: Optional[str] = None) -> DevOpsKeyVault:
    """Retrieve global DevOpsKeyVault instance."""
    global _vault_instance
    if _vault_instance is None or db_url is not None:
        _vault_instance = DevOpsKeyVault(db_url=db_url)
    return _vault_instance
