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
Unit tests for Native MCP Server and Tool Aggregator.
Adheres strictly to GEES v1.0.
"""

from typing import Any, Dict
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core_platform.app.auth.api_keys import get_api_key_manager
from core_platform.app.mcp_server.server import router as mcp_router
from core_platform.app.mcp_server.tool_aggregator import (
    get_all_tools,
    get_tool_handler,
    register_app_tools,
    register_tool,
)


@pytest.fixture
def auth_api_key() -> str:
    """Create a temporary active API key for testing."""
    mgr = get_api_key_manager()
    raw_key, _ = mgr.create_key(
        label="MCP Test Key",
        principal_id="mcp_test_client",
        roles=["admin"],
        permitted_apps=["temperature_marker", "mail_organizer"],
    )
    return raw_key


def test_tool_aggregator() -> None:
    """Test @register_tool decorator and tool registry query functions."""
    @register_tool(
        app_id="test_app",
        name="test_echo_tool",
        description="Echo input text",
        input_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
    )
    async def echo_tool(msg: str = "hello") -> Dict[str, str]:
        return {"echo": msg}

    tools = get_all_tools()
    tool_names = [t["name"] for t in tools]
    assert "test_echo_tool" in tool_names

    handler = get_tool_handler("test_echo_tool")
    assert handler is not None

    assert get_tool_handler("nonexistent_tool") is None

    # Test register_app_tools bulk register
    register_app_tools([
        {
            "name": "bulk_tool",
            "app_id": "test_app",
            "description": "Bulk tool",
            "handler": lambda: "bulk_result",
        },
        {"name": ""},  # Test empty name continue branch
    ])
    assert get_tool_handler("bulk_tool") is not None

    # Test overwriting existing tool registration (bulk_tool)
    @register_tool(
        app_id="test_app",
        name="bulk_tool",
        description="Overwriting existing tool",
    )
    async def bulk_tool_overwritten() -> Dict[str, str]:
        return {"overwritten": "true"}




def test_mcp_server_json_rpc(auth_api_key: str) -> None:
    """Test MCP JSON-RPC 2.0 messages: initialize, tools/list, tools/call, ping."""
    app = FastAPI()
    app.include_router(mcp_router)
    client = TestClient(app)

    headers = {"Authorization": f"Bearer {auth_api_key}"}

    # 1. Unauthenticated request rejected
    res_unauth = client.post("/mcp/messages", json={"jsonrpc": "2.0", "method": "ping", "id": 1})
    assert res_unauth.status_code == 401

    # 2. Ping
    res_ping = client.post(
        "/mcp/messages",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "ping", "id": 1},
    )
    assert res_ping.status_code == 200
    assert res_ping.json()["result"] == {"pong": True}

    # 3. Initialize
    res_init = client.post(
        "/mcp/messages",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 2,
            "params": {"clientInfo": {"name": "cursor", "version": "1.0"}},
        },
    )
    assert res_init.status_code == 200
    data_init = res_init.json()["result"]
    assert data_init["protocolVersion"] == "2024-11-05"
    assert "tools" in data_init["capabilities"]

    # 4. Tools list
    res_list = client.post(
        "/mcp/messages",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 3},
    )
    assert res_list.status_code == 200
    assert "tools" in res_list.json()["result"]

    # 5. Tools call
    res_call = client.post(
        "/mcp/messages",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 4,
            "params": {"name": "test_echo_tool", "arguments": {"msg": "world"}},
        },
    )
    assert res_call.status_code == 200
    content = res_call.json()["result"]["content"]
    assert len(content) == 1
    assert "world" in content[0]["text"]

    # 6. Unknown method
    res_unknown = client.post(
        "/mcp/messages",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "unknown/method", "id": 5},
    )
    assert res_unknown.status_code == 200
    assert "error" in res_unknown.json()
    assert res_unknown.json()["error"]["code"] == -32601

    # 7. Non-json body
    res_bad = client.post("/mcp/messages", headers=headers, content="not-json")
    assert res_bad.status_code == 200
    assert res_bad.json()["error"]["code"] == -32700


@pytest.mark.anyio
async def test_mcp_sse_endpoint_direct() -> None:
    """Test mcp_sse_endpoint generator directly with disconnect mock."""
    from unittest.mock import AsyncMock, MagicMock
    from core_platform.app.mcp_server.server import mcp_sse_endpoint
    from core_platform.app.auth.models import SecurityContext

    req = MagicMock()
    req.url = "http://localhost/mcp/sse"
    req.is_disconnected = AsyncMock(side_effect=[False, True])
    ctx = SecurityContext.system()

    resp = await mcp_sse_endpoint(req, ctx=ctx)
    assert resp.status_code == 200
    gen = resp.body_iterator
    first_chunk = await anext(gen)
    assert "event: endpoint" in first_chunk


def test_mcp_tool_error_returns_is_error_envelope(auth_api_key: str) -> None:
    """TECH-3: Tool execution error must return HTTP 200 with isError=True in the
    JSON-RPC result body — never HTTP 4xx/5xx, which would break MCP clients."""

    @register_tool(
        app_id="test_app",
        name="always_fails_tool",
        description="A tool that always raises",
        input_schema={"type": "object", "properties": {}},
    )
    async def always_fails() -> None:
        raise RuntimeError("Simulated tool crash")

    app = FastAPI()
    app.include_router(mcp_router)
    client = TestClient(app)

    headers = {"Authorization": f"Bearer {auth_api_key}"}

    res = client.post(
        "/mcp/messages",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 99,
            "params": {"name": "always_fails_tool", "arguments": {}},
        },
    )

    # Must be HTTP 200 — not HTTP 500
    assert res.status_code == 200

    body = res.json()
    # JSON-RPC 2.0: error must be in result.isError, not at top level
    assert "result" in body
    result = body["result"]
    assert result.get("isError") is True
    assert len(result["content"]) > 0
    assert "always_fails_tool" in result["content"][0]["text"]


def test_mcp_unknown_tool_returns_is_error_envelope(auth_api_key: str) -> None:
    """TECH-3: Calling an unknown tool must return HTTP 200 with isError=True."""
    app = FastAPI()
    app.include_router(mcp_router)
    client = TestClient(app)

    headers = {"Authorization": f"Bearer {auth_api_key}"}

    res = client.post(
        "/mcp/messages",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 100,
            "params": {"name": "nonexistent_tool_xyz", "arguments": {}},
        },
    )

    assert res.status_code == 200
    result = res.json()["result"]
    assert result.get("isError") is True
    assert "nonexistent_tool_xyz" in result["content"][0]["text"]
