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
Native MCP (Model Context Protocol) Server Host.

Adheres strictly to Plan 02 v1.3 Section 7.
Implements the JSON-RPC 2.0 over HTTP MCP protocol:
  GET  /mcp/sse      — SSE endpoint for Cursor / Claude Desktop connections
  POST /mcp/messages — JSON-RPC 2.0 method dispatch (initialize, tools/list, tools/call)

Security: All requests require a valid Bearer API key (Strategy D).
Encapsulation: External agents NEVER bypass the orchestrator — all tool calls
  route through full LangGraph pipelines with audit trail logging.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core_platform.app.entitlements.contracts import EntitlementDeniedError
from core_platform.app.entitlements.dependencies import authorize_mcp_tool
from core_platform.app.mcp_server.tool_aggregator import get_all_tools, get_tool_handler
from core_platform.app.rbac.permissions import get_api_security_context
from core_platform.app.auth.models import SecurityContext
from core_platform.app.ingress.rate_limiter import get_platform_rate_limiter

logger = logging.getLogger("core_platform.mcp_server")

router = APIRouter(prefix="/mcp", tags=["MCP Server"])

# Track connected SSE clients: session_id → asyncio.Queue
_sse_clients: Dict[str, asyncio.Queue[Dict[str, Any]]] = {}


# ── SSE Endpoint ─────────────────────────────────────────────────────────────

@router.get("/sse")
async def mcp_sse_endpoint(
    request: Request,
    ctx: SecurityContext = Depends(get_api_security_context),
) -> StreamingResponse:
    """SSE endpoint for MCP client connection (Cursor, Claude Desktop).

    Sends the MCP endpoint discovery event immediately on connect,
    then holds the connection open for server-initiated pushes.

    Args:
        request: FastAPI request.
        ctx: Authenticated SecurityContext.

    Returns:
        SSE StreamingResponse.
    """
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    _sse_clients[session_id] = queue

    # Build messages endpoint URL — prefer ORCHESTRATOR_BASE_URL for reverse-proxy deployments.
    from core_platform.app.config import settings as _settings
    base = getattr(_settings, "ORCHESTRATOR_BASE_URL", "").rstrip("/")
    if base:
        messages_url = f"{base}/mcp/messages?session_id={session_id}"
    else:
        # Fallback: derive from current request URL, stripping any query string first.
        raw_url = str(request.url).split("?")[0]
        messages_url = raw_url.replace("/sse", f"/messages?session_id={session_id}")

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            # Initial endpoint discovery event (required by MCP protocol).
            yield f"event: endpoint\ndata: {messages_url}\n\n"

            logger.info("[MCPServer] SSE client connected: session=%s principal=%s", session_id, ctx.principal_id)

            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat keep-alive.
                    yield ": heartbeat\n\n"
        finally:
            _sse_clients.pop(session_id, None)
            logger.info("[MCPServer] SSE client disconnected: session=%s", session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── JSON-RPC 2.0 Message Endpoint ────────────────────────────────────────────

@router.post("/messages")
async def mcp_messages_endpoint(
    request: Request,
    session_id: Optional[str] = None,
    ctx: SecurityContext = Depends(get_api_security_context),
) -> JSONResponse:
    """JSON-RPC 2.0 dispatcher for MCP protocol messages.

    Handles: initialize, tools/list, tools/call.

    Args:
        request: FastAPI request containing the JSON-RPC payload.
        session_id: Optional SSE session ID for response routing.
        ctx: Authenticated SecurityContext.

    Returns:
        JSON-RPC 2.0 response object.
    """
    # --- Layer 0: Per-principal rate limiting ---
    _limiter = get_platform_rate_limiter()
    allowed, _ = _limiter.check_and_consume(ctx.principal_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Reduce request frequency.")

    try:
        body = await request.json()
    except Exception:
        return _error_response(None, -32700, "Parse error: invalid JSON")

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    if method == "initialize":
        result = _handle_initialize(params, ctx)
    elif method == "tools/list":
        result = _handle_tools_list()
    elif method == "tools/call":
        result = await _handle_tools_call(params, ctx)
    elif method == "ping":
        result = {"pong": True}
    else:
        return _error_response(rpc_id, -32601, f"Method not found: {method}")

    response = {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    # If caller provided a session_id, also push to SSE queue.
    if session_id and session_id in _sse_clients:
        try:
            _sse_clients[session_id].put_nowait(response)
        except asyncio.QueueFull:
            pass

    return JSONResponse(content=response)


# ── Method Handlers ───────────────────────────────────────────────────────────

def _handle_initialize(params: Dict[str, Any], ctx: SecurityContext) -> Dict[str, Any]:
    """Handle MCP initialize handshake.

    Args:
        params: Client capabilities dict.
        ctx: Authenticated context.

    Returns:
        Server capabilities and info dict.
    """
    logger.info(
        "[MCPServer] initialize from principal=%s client=%s",
        ctx.principal_id,
        params.get("clientInfo", {}).get("name", "unknown"),
    )
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": "Release100 MCP Server",
            "version": "1.3.0",
        },
    }


def _handle_tools_list() -> Dict[str, Any]:
    """Handle tools/list request.

    Returns:
        Dict with 'tools' key containing all registered tool manifests.
    """
    return {"tools": get_all_tools()}


async def _handle_tools_call(params: Dict[str, Any], ctx: SecurityContext) -> Dict[str, Any]:
    """Handle tools/call request — executes a registered tool handler.

    All tool calls are routed through this single choke point:
    no external agent can bypass the orchestrator or directly access the DB.

    Args:
        params: Dict with 'name' and 'arguments' keys.
        ctx: Authenticated SecurityContext used for RBAC checks.

    Returns:
        Tool execution result dict (JSON-RPC 2.0 content envelope or isError envelope).
    """
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    handler = get_tool_handler(tool_name)
    if handler is None:
        # Return MCP isError envelope — do NOT raise HTTPException inside a JSON-RPC handler.
        logger.warning("[MCPServer] Tool not found: %s (principal=%s)", tool_name, ctx.principal_id)
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Tool '{tool_name}' not found."}],
        }

    # Entitlement gate (Plan 10): API-key callers are SERVICE principals. Under off/shadow this
    # never changes the outcome; under enforce a missing grant (or unmapped tool) is forbidden.
    try:
        authorize_mcp_tool(ctx, tool_name)
    except EntitlementDeniedError:
        logger.warning("[MCPServer] Forbidden by entitlements: tool=%s principal=%s", tool_name, ctx.principal_id)
        return {"isError": True, "content": [{"type": "text", "text": "Forbidden"}]}
    logger.info(
        "[MCPServer] tools/call: tool=%s principal=%s args=%s",
        tool_name,
        ctx.principal_id,
        list(arguments.keys()),
    )

    try:
        result = await handler(**arguments)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
    except TypeError as exc:
        logger.error("[MCPServer] Tool %s invalid arguments: %s", tool_name, exc, exc_info=True)
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Invalid tool arguments for '{tool_name}': {exc}"}],
        }
    except Exception as exc:
        logger.error("[MCPServer] Tool %s raised exception: %s", tool_name, exc, exc_info=True)
        return {
            "isError": True,
            "content": [
                {
                    "type": "text",
                    "text": f"Tool '{tool_name}' execution failed: {type(exc).__name__}: {exc}",
                }
            ],
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _error_response(rpc_id: Any, code: int, message: str) -> JSONResponse:
    """Build a JSON-RPC 2.0 error response.

    Args:
        rpc_id: Request ID.
        code: Error code.
        message: Human-readable error message.

    Returns:
        JSONResponse with error body.
    """
    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": code, "message": message},
        },
        status_code=200,  # JSON-RPC always returns HTTP 200; error in body.
    )
