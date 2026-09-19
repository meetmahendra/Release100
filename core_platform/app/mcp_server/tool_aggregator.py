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
MCP Tool Aggregator — @register_tool Decorator & Tool Registry.

Adheres strictly to Plan 02 v1.3 Section 7 (MCP Server Host).
Provides:
- @register_tool decorator for app cartridges to self-register their tools.
- Tool manifest registry consulted by the MCP server for tools/list and tools/call.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_platform.mcp_server.tool_aggregator")

# Global tool registry: tool_name → tool descriptor dict.
_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_tool(
    app_id: str,
    name: str,
    description: str,
    input_schema: Optional[Dict[str, Any]] = None,
) -> Callable[..., Any]:
    """Decorator to register an async function as an MCP tool.

    Usage in app cartridges:
        from core_platform.app.mcp_server.tool_aggregator import register_tool

        @register_tool(
            app_id="mail_organizer",
            name="mail_search_threads",
            description="Search Gmail threads matching a query.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        )
        async def mail_search_threads(query: str, max_results: int = 10): ...

    Args:
        app_id: Owning cartridge identifier.
        name: Tool name exposed to MCP clients (e.g. "mail_search_threads").
        description: Human-readable description for tool selection.
        input_schema: JSON Schema dict for tool parameters.

    Returns:
        Decorator that registers the function and returns it unchanged.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if name in _TOOL_REGISTRY:
            logger.warning("[ToolAggregator] Overwriting existing tool registration: %s", name)

        _TOOL_REGISTRY[name] = {
            "name": name,
            "app_id": app_id,
            "description": description,
            "inputSchema": input_schema or {
                "type": "object",
                "properties": {},
            },
            "handler": func,
        }
        logger.debug("[ToolAggregator] Registered tool: %s (app=%s)", name, app_id)
        return func

    return decorator


def get_all_tools() -> List[Dict[str, Any]]:
    """Return tool manifests for MCP tools/list response.

    Returns:
        List of tool descriptor dicts (without handler callable).
    """
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["inputSchema"],
        }
        for t in _TOOL_REGISTRY.values()
    ]


def get_tool_handler(name: str) -> Optional[Callable[..., Any]]:
    """Look up the callable handler for a named tool.

    Args:
        name: Tool name as provided in a tools/call request.

    Returns:
        Async callable, or None if tool not registered.
    """
    entry = _TOOL_REGISTRY.get(name)
    return entry["handler"] if entry else None


def register_app_tools(app_tools: List[Dict[str, Any]]) -> None:
    """Bulk-register tools from a plugin cartridge's get_mcp_tools() manifest.

    Called by the plugin loader during app mounting.

    Args:
        app_tools: List of tool descriptor dicts with 'name', 'description',
                   'handler', and optional 'inputSchema' keys.
    """
    for tool in app_tools:
        name = tool.get("name", "")
        if not name:
            continue
        _TOOL_REGISTRY[name] = {
            "name": name,
            "app_id": tool.get("app_id", "unknown"),
            "description": tool.get("description", ""),
            "inputSchema": tool.get("inputSchema", {"type": "object", "properties": {}}),
            "handler": tool.get("handler"),
        }
        logger.debug("[ToolAggregator] Bulk-registered tool: %s", name)
