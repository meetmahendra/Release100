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
Customer HR/ERP Employee ID Resolver & Sequential Generator.

Implements flexible operator onboarding:
1. If customer external HR system is configured, queries service for employee ID.
2. If standalone, generates next internal sequence (EMP-XXXX).
"""

import logging
from typing import Optional

from apps.temperature_marker.database.db_service import DatabaseService
from core_platform.app.config import settings

logger = logging.getLogger("apps.temperature_marker.hr_connector")

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False


async def resolve_or_generate_employee_code(
    phone_number: str,
    full_name: str,
    explicit_code: Optional[str] = None,
) -> str:
    """Resolve employee ID from external HR service or auto-generate sequential internal ID.

    Args:
        phone_number: Normalized WhatsApp phone number.
        full_name: Operator name.
        explicit_code: Optional manual override provided by user/admin.

    Returns:
        Resolved or generated Employee Code.
    """
    if explicit_code and explicit_code.strip():
        return explicit_code.strip()

    # 1. If external HR/ERP URL is configured and active, attempt lookup
    hr_url = getattr(settings, "CUSTOMER_HR_SERVICE_URL", None)
    if hr_url and _HAS_HTTPX and httpx is not None:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(
                    f"{hr_url.rstrip('/')}/api/employees/resolve",
                    json={"phone": phone_number, "name": full_name},
                )
                if resp.is_success:
                    data = resp.json()
                    ext_id = data.get("employee_id") or data.get("emp_code")
                    if ext_id:
                        logger.info("[HRConnector] Resolved %s from customer external HR system: %s", full_name, ext_id)
                        return str(ext_id).strip()
        except Exception as exc:
            logger.warning("[HRConnector] External HR lookup failed (%s). Falling back to internal sequence.", exc)

    # 2. Standalone fallback: Auto-generate internal sequential ID
    db = DatabaseService.get_instance()
    generated = db.generate_next_emp_code(prefix="EMP")
    logger.info("[HRConnector] Auto-generated internal employee code for %s: %s", full_name, generated)
    return generated
