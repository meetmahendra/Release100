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

"""Universal Downstream Gateway and Edge Outbox Package."""

from apps.temperature_marker.downstream.base_connector import (
    BaseDownstreamConnector,
    create_downstream_connector,
)
from apps.temperature_marker.downstream.direct_database import DirectDatabaseConnector
from apps.temperature_marker.downstream.erp_connector import ERPGatewayConnector
from apps.temperature_marker.downstream.in_house_rest import InHouseRESTConnector
from apps.temperature_marker.downstream.mcp_tools import (
    TemperatureMarkerMCPTools,
    get_temperature_marker_mcp_tools,
)
from apps.temperature_marker.downstream.outbox_manager import OutboxManager

__all__ = [
    "BaseDownstreamConnector",
    "create_downstream_connector",
    "DirectDatabaseConnector",
    "ERPGatewayConnector",
    "InHouseRESTConnector",
    "TemperatureMarkerMCPTools",
    "get_temperature_marker_mcp_tools",
    "OutboxManager",
]

