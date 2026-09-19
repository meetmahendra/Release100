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
Enterprise ERP Downstream Gateway Connector (SAP / Odoo / Zoho).

Adheres to Plan 03 v1.3 Section 7.
Dispatches CaneBot duty check-ins and cold-chain temperature telemetry
into external ERP systems using Bearer token authenticated JSON REST requests.
"""

from typing import Any, Dict, Optional, Tuple

from apps.temperature_marker.downstream.base_connector import BaseDownstreamConnector

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False


class ERPGatewayConnector(BaseDownstreamConnector):
    """Dispatches attendance and chiller readings to enterprise ERP gateways (Odoo, SAP, Zoho)."""

    def __init__(
        self,
        erp_type: str = "odoo",
        api_endpoint: Optional[str] = None,
        api_token: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ) -> None:
        """Initialize ERPGatewayConnector.

        Args:
            erp_type: Target system ('odoo', 'sap', 'zoho').
            api_endpoint: External ERP webhook URL.
            api_token: Bearer auth token or API key.
            mock_mode: Explicit control over mock mode.
        """
        super().__init__(connector_name=f"erp_{erp_type}")
        self.erp_type = erp_type
        self.api_endpoint = api_endpoint or f"mock://{erp_type}-erp.canectar.internal/api/v1/attendance"
        self.api_token = api_token
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = self.api_endpoint.startswith("mock://") or not self.api_token

    async def dispatch(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Dispatch attendance and chiller reading to ERP.

        Args:
            payload: Structured operational data dictionary.

        Returns:
            Tuple of (success: bool, status_message: str).
        """
        if "mock_offline" in payload and payload["mock_offline"]:
            return False, f"Simulated {self.erp_type.upper()} gateway unreachable"

        if self.mock_mode or not _HAS_HTTPX or httpx is None:
            correlation_id = payload.get("correlation_id", "UNKNOWN")
            return True, f"Simulated {self.erp_type.upper()} 200 OK: Check-in '{correlation_id}' posted"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
            "X-Sensor-System": "CaneBot-Edge-V1",
        }

        # Map to canonical ERP payload format
        erp_payload = {
            "transaction_id": payload.get("correlation_id"),
            "employee_id": payload.get("emp_code"),
            "equipment_code": payload.get("kiosk_id"),
            "temperature_celsius": payload.get("chiller_temp_c"),
            "haccp_evaluation": payload.get("haccp_status"),
            "geofence_distance_m": payload.get("distance_meters"),
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(self.api_endpoint, json=erp_payload, headers=headers)
                if resp.status_code in [200, 201, 202]:
                    return True, f"{self.erp_type.upper()} HTTP {resp.status_code}: Record synced"
                return False, f"{self.erp_type.upper()} HTTP {resp.status_code}: Gateway rejected transaction"
        except Exception as exc:
            return False, f"{self.erp_type.upper()} dispatch network error: {exc}"
