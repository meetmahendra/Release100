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
Abstract Downstream Connector Interface.

Adheres to Plan 03 v1.3. Decouples business outcomes from external persistence.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple


class BaseDownstreamConnector(ABC):
    """Abstract connector for downstream persistence targets."""

    def __init__(self, connector_name: str) -> None:
        """Initialize BaseDownstreamConnector.

        Args:
            connector_name: Unique connector identifier.
        """
        self.connector_name = connector_name

    @abstractmethod
    async def dispatch(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Dispatch a verified transaction payload to the external system.

        Args:
            payload: Structured dictionary containing attendance and temperature data.

        Returns:
            Tuple of (success: bool, message_or_id: str).
        """
        pass


def create_downstream_connector(
    target_type: str = "in_house_rest",
    endpoint_url: str | None = None,
    api_token: str | None = None,
    connection_string: str | None = None,
    mock_mode: bool | None = None,
) -> BaseDownstreamConnector:
    """Factory helper creating the appropriate downstream connector instance.

    Args:
        target_type: 'in_house_rest', 'direct_database', 'erp_odoo', 'erp_sap'.
        endpoint_url: REST or ERP endpoint URL.
        api_token: Bearer token for ERP.
        connection_string: SQLAlchemy DB URL for direct DB.
        mock_mode: Explicit control over mock mode.

    Returns:
        Configured BaseDownstreamConnector instance.
    """
    if target_type == "direct_database":
        from apps.temperature_marker.downstream.direct_database import DirectDatabaseConnector
        return DirectDatabaseConnector(
            connection_string=connection_string,
            mock_mode=mock_mode,
        )

    if target_type.startswith("erp_"):
        erp_system = target_type.replace("erp_", "")
        from apps.temperature_marker.downstream.erp_connector import ERPGatewayConnector
        return ERPGatewayConnector(
            erp_type=erp_system,
            api_endpoint=endpoint_url,
            api_token=api_token,
            mock_mode=mock_mode,
        )

    if target_type == "google_sheets":
        from apps.temperature_marker.downstream.google_sheets import GoogleSheetsConnector
        return GoogleSheetsConnector()

    # Default: in_house_rest
    from apps.temperature_marker.downstream.in_house_rest import InHouseRESTConnector
    return InHouseRESTConnector(
        endpoint_url=endpoint_url,
        mock_mode=mock_mode,
    )
