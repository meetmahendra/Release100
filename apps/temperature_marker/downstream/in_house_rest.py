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
In-House REST Webhook Downstream Connector.

Posts verified operational telemetry to internal enterprise endpoints via JSON HTTP POST.
"""

from typing import Any, Dict, Optional, Tuple
from apps.temperature_marker.downstream.base_connector import BaseDownstreamConnector

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False


class InHouseRESTConnector(BaseDownstreamConnector):
    """Dispatches attendance and temperature readings to an in-house REST API."""

    def __init__(self, endpoint_url: Optional[str] = None, mock_mode: Optional[bool] = None) -> None:
        """Initialize InHouseRESTConnector.

        Args:
            endpoint_url: Target REST URL, defaults to apex endpoint if None.
            mock_mode: If explicitly set, controls mock mode. If None, auto-detects from endpoint URL.
        """
        super().__init__(connector_name="in_house_rest")
        self.endpoint_url = endpoint_url or "mock://internal-erp.local/api/attendance"
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = self.endpoint_url.startswith("mock://")

    async def dispatch(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Dispatch payload via HTTP POST.

        Args:
            payload: Structured operational data dictionary.

        Returns:
            Tuple of (success: bool, status_message: str).
        """
        # If simulated endpoint or testing mode
        if "mock_offline" in payload and payload["mock_offline"]:
            return False, "Simulated network failure: endpoint unreachable"

        if self.mock_mode or self.endpoint_url.startswith("mock://") or not _HAS_HTTPX or httpx is None:
            # Fallback / mock simulated success
            return True, "Simulated HTTP 200: Payload accepted (mock mode)"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self.endpoint_url, json=payload)
                if resp.status_code in [200, 201, 202]:
                    return True, f"HTTP {resp.status_code}: Dispatched successfully"
                return False, f"HTTP {resp.status_code}: Downstream server rejected payload"
        except Exception as e:
            return False, f"Network timeout/error dispatching to {self.endpoint_url}: {e}"
