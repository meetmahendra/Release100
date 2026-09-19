# Plan 08 — Integration & Technical Defect Remediation
## `Release100` Platform — v1.0

**Author:** Engineering Review (Antigravity Audit, 16-Sep-2026)
**Scope:** Integration dead-code wiring gaps (INT-1 — INT-4) + Technical correctness bugs (TECH-1 — TECH-6)
**Out of Scope:** Security hardening (SEC-1 — SEC-8), missed architecture planning (MISS-1 — MISS-10) — deferred to future plans
**Depends On:** Plans 01–07 (fully implemented per walkthrough 16-Sep-2026)

---

## Background

The production readiness audit of 16-Sep-2026 identified two categories of defects that are **independent of security concerns** and can be resolved immediately without waiting for security architecture decisions:

1. **Integration defects** — fully implemented platform components (rate limiter, plugin loader, platform outbox, LLM gateway) that are dead code because they were never wired into the runtime bootstrap or calling code.
2. **Technical defects** — correctness bugs in implemented code: all four LLM providers block the async event loop, Ollama availability is never actually checked, and the MCP server breaks JSON-RPC protocol on tool errors.

These defects do not require new architectural decisions — the implementations already exist and are correct in isolation. The work is purely wiring and correctness.

---

## Defect Inventory

### Integration Defects (Dead Code — Built But Never Activated)

| ID | Severity | What is Dead | Runtime Impact |
|---|---|---|---|
| **INT-1** | 🔴 High | `core_platform/app/ingress/rate_limiter.py` — never called from `whatsapp_router.py` or `mcp_server/server.py` | Any WhatsApp number or MCP key can flood the system with unlimited requests |
| **INT-2** | 🔴 High | `core_platform/app/plugin_engine/loader.py` — never instantiated; `main.py` uses hardcoded if-blocks | Adding a 3rd cartridge requires modifying `main.py` manually; plugin architecture provides zero value |
| **INT-3** | 🔴 High | `core_platform/app/outbox/queue.py` + `synchronizer.py` — never started; `main.py` runs its own `_outbox_sync_worker` for TM only; mail organizer has zero outbox protection | Mail organizer Gmail API failures silently lose data; platform outbox architecture unused |
| **INT-4** | 🟠 Medium | `apps/mail_organizer/graph/nodes/classify_node.py`, `pm_extract_node.py`, `draft_node.py` — call Gemini REST directly, bypassing `get_platform_llm_gateway()` | No provider fallback, no future retry benefit, no vendor switching; `classify_node.py` has silent `except Exception: pass` — GEES audit trail violation |

### Technical Defects (Correctness Bugs in Existing Code)

| ID | Severity | What is Wrong | Runtime Impact |
|---|---|---|---|
| **TECH-1** | 🔴 Critical | All four LLM providers (`gemini_provider.py`, `claude_provider.py`, `openai_provider.py`, `ollama_provider.py`) — `async def generate()` calls synchronous `urllib.request.urlopen()` internally | LLM calls (1–30 seconds each) block the entire FastAPI event loop; no other request served during inference |
| **TECH-2** | 🟠 Medium | `llm/ollama_provider.py` — `is_available()` always returns `True` when `base_url` is non-empty; `self._available` is declared but never written | Gateway selects Ollama even when server is offline; fallback chain behaves incorrectly |
| **TECH-3** | 🟠 Medium | `mcp_server/server.py` — `_handle_tools_call` raises `HTTPException` for tool errors, producing HTTP 4xx/5xx instead of JSON-RPC 2.0 error envelopes | Cursor / Claude Desktop / any MCP client misparses tool failure responses; breaks MCP protocol compliance |

---

## Section 1: INT-1 — Wire Rate Limiter into Ingress

### Problem
`core_platform/app/ingress/rate_limiter.py` exports `get_platform_rate_limiter()` returning a `RateLimiter`
singleton with `TokenBucket` per sender. It is never called. Two ingress surfaces are unprotected:

1. `POST /webhook` in `whatsapp_router.py` — unlimited WhatsApp message flood
2. `POST /mcp/messages` in `mcp_server/server.py` — unlimited MCP tool calls

### Solution

**File: `core_platform/app/ingress/whatsapp_router.py`**

Import and invoke the rate limiter at the top of the inbound message handler, before any workflow
execution. Return HTTP 200 (required by Meta) with a `rate_limited` body:

```python
from core_platform.app.ingress.rate_limiter import get_platform_rate_limiter

# --- Rate limiting (Layer 0, per-sender token bucket) ---
_rate_limiter = get_platform_rate_limiter()
allowed, remaining = _rate_limiter.check_and_consume(sender_phone)
if not allowed:
    logger.warning(
        "[RateLimit] Sender %s exceeded rate limit. Remaining tokens: %d",
        sender_phone,
        remaining,
    )
    # Must return HTTP 200 to Meta — returning 4xx causes Meta to retry.
    return JSONResponse(
        status_code=200,
        content={"status": "rate_limited", "sender": sender_phone},
    )
```

> **Important:** WhatsApp Cloud API requires HTTP 200 on all webhook POSTs. The rate-limit
> response must always be HTTP 200 externally.

**File: `core_platform/app/mcp_server/server.py`**

Add rate-limit check in `handle_mcp_message()` using `principal_id` as the limiter key:

```python
from core_platform.app.ingress.rate_limiter import get_platform_rate_limiter

# Inside handle_mcp_message(), after ctx is resolved:
_limiter = get_platform_rate_limiter()
allowed, _ = _limiter.check_and_consume(ctx.principal_id)
if not allowed:
    raise HTTPException(
        status_code=429,
        detail="Rate limit exceeded. Reduce request frequency.",
    )
```

### Acceptance Criteria
- [ ] `get_platform_rate_limiter().check_and_consume()` called on every `POST /webhook` before workflow execution
- [ ] `get_platform_rate_limiter().check_and_consume()` called on every `POST /mcp/messages` before tool dispatch
- [ ] Over-limit WhatsApp messages return HTTP 200 with `{"status": "rate_limited"}` body
- [ ] Over-limit MCP requests return HTTP 429
- [ ] `test_rate_limiter.py` tests remain passing; add 2 new integration tests verifying rate limiting
  on `/webhook` and `/mcp/messages`

---

## Section 2: INT-2 — Activate PluginLoader in `main.py`

### Problem
`core_platform/app/plugin_engine/loader.py` contains a fully implemented `PluginLoader` class.
`main.py` ignores it and uses hardcoded `if "app_id" in settings.ENABLED_APPLICATIONS` blocks.
Plugin lifecycle hooks (`on_startup`, `on_shutdown`) are never called. A 3rd cartridge cannot be
added without modifying `main.py`.

### Solution

**Strategy: Hybrid activation** — use `PluginLoader` for lifecycle (startup/shutdown), keep current
explicit router mounts for this iteration. Safe incremental approach.

**File: `core_platform/main.py`**

```python
from core_platform.app.plugin_engine.loader import PluginLoader

_plugin_loader = PluginLoader(
    apps_root=Path(__file__).parent.parent / "apps",
    enabled_apps=list(settings.ENABLED_APPLICATIONS),
)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _plugin_loader.load_all()
    logger.info("[PluginLoader] Loaded: %s", _plugin_loader.get_loaded_app_ids())
    relay_client.start()
    outbox_stop = asyncio.Event()
    outbox_task = asyncio.create_task(_outbox_sync_worker(outbox_stop))
    yield
    await _plugin_loader.shutdown_all()
    outbox_stop.set()
    try:
        await asyncio.wait_for(outbox_task, timeout=2.0)
    except Exception:
        pass
    await relay_client.stop()
```

**File: `core_platform/app/plugin_engine/loader.py`**

Add three items:
1. `get_loaded_app_ids()` method — returns list of successfully loaded app IDs
2. Make `shutdown_all()` async (add `async def`)
3. Wire `register_app_tools()` inside `_mount_single()` for cartridges exposing `get_mcp_tools()`:

```python
from core_platform.app.mcp_server.tool_aggregator import register_app_tools

def _mount_single(self, instance: BaseApplication, fastapi_app: FastAPI) -> None:
    # ... existing router mounting code ...
    tools = instance.get_mcp_tools()
    if tools:
        register_app_tools(tools)
        logger.debug("[PluginLoader] Registered %d MCP tools for %s", len(tools), instance.app_id)
```

### Acceptance Criteria
- [ ] `PluginLoader.load_all()` called during `lifespan` startup; logs loaded cartridge IDs
- [ ] `PluginLoader.shutdown_all()` called during `lifespan` shutdown
- [ ] `PluginLoader._mount_single()` calls `register_app_tools()` for cartridges with MCP tools
- [ ] Existing temperature_marker and mail_organizer functionality unaffected
- [ ] `test_plugin_engine.py` tests remain passing; add lifecycle test for `load_all()` + `shutdown_all()`
- [ ] A future 3rd cartridge with valid `plugin.py` can be discovered without modifying `main.py`

---

## Section 3: INT-3 — Consolidate Outbox: Activate PlatformOutboxQueue for Mail Organizer

### Problem
Two outbox systems coexist with no connection:
1. **App-level (active):** `apps/temperature_marker/downstream/outbox_manager.py` — used by `main.py`'s `_outbox_sync_worker()`
2. **Platform-level (dead):** `core_platform/app/outbox/queue.py` + `synchronizer.py` — never started

Mail organizer has **zero downstream failure protection** — Gmail API failures silently lose data.

Additionally, `synchronizer.py`'s generic fallback silently marks unknown-app items as `SYNCED` (data loss bug).

### Solution

**Strategy:** Keep TM app-level `OutboxManager` as-is (well-tested). Activate `PlatformOutboxQueue` +
`OutboxSynchronizer` as the backstop for mail organizer failures.

**File: `core_platform/app/outbox/synchronizer.py`**

Fix data-loss bug in generic fallback:
```python
# BEFORE (silent data loss):
return True, "Acknowledged"

# AFTER:
logger.error(
    "[OutboxSynchronizer] No dispatcher for app_id=%s — item stays PENDING for manual review.",
    app_id,
)
return False, f"No dispatcher registered for app_id={app_id}"
```

Add mail organizer dispatch case in `_dispatch_item()`:
```python
elif app_id == "mail_organizer":
    from apps.mail_organizer.connectors.gmail_connector import GmailConnector
    connector = GmailConnector()
    operation = payload.get("operation")
    if operation == "apply_label":
        success = await connector.apply_label(
            gmail_id=payload["gmail_id"],
            label=payload["label"],
        )
        return success, "label_applied" if success else "gmail_api_error"
    return False, f"Unknown mail_organizer operation: {operation}"
```

**File: `core_platform/main.py`**

Start `OutboxSynchronizer` in lifespan:
```python
from core_platform.app.outbox.synchronizer import OutboxSynchronizer

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ... existing startup ...
    _platform_sync = OutboxSynchronizer(drain_interval_seconds=30)
    platform_sync_task = asyncio.create_task(_platform_sync.run())
    yield
    # ... existing shutdown ...
    await _platform_sync.stop()
    try:
        await asyncio.wait_for(platform_sync_task, timeout=5.0)
    except Exception:
        pass
```

**File: `apps/mail_organizer/graph/nodes/execution_node.py`**

Enqueue into `PlatformOutboxQueue` on Gmail API failure:
```python
from core_platform.app.outbox.queue import get_platform_outbox

# In execution_node(), on Gmail API failure:
except Exception as exc:
    logger.warning(
        "[ExecutionNode] Gmail API failure for gmail_id=%s: %s — queuing for retry",
        gmail_id, exc,
    )
    outbox = get_platform_outbox()
    await outbox.enqueue(
        app_id="mail_organizer",
        payload={
            "operation": "apply_label",
            "gmail_id": gmail_id,
            "label": label,
            "correlation_id": state.get("correlation_id", ""),
        },
    )
    state["sync_status"] = "queued_for_retry"
```

### Acceptance Criteria
- [ ] `OutboxSynchronizer` started as `asyncio.Task` in `lifespan`; gracefully stopped during shutdown
- [ ] Generic `app_id` fallback in `synchronizer._dispatch_item()` returns `(False, ...)` not `(True, "Acknowledged")`
- [ ] `execution_node.py` enqueues to `PlatformOutboxQueue` on Gmail API failure (not silent loss)
- [ ] `synchronizer.py` dispatches `mail_organizer/apply_label` outbox items
- [ ] `test_platform_outbox.py` tests remain passing
- [ ] New test: Gmail failure → item queued → synchronizer drains successfully

---

## Section 4: INT-4 — Migrate Mail Organizer LLM Nodes to Platform Gateway

### Problem
Three mail organizer nodes call Gemini REST API directly via `urllib.request.urlopen()`:
- `apps/mail_organizer/graph/nodes/classify_node.py` (lines 98–145)
- `apps/mail_organizer/graph/nodes/pm_extract_node.py`
- `apps/mail_organizer/graph/nodes/draft_node.py`

These nodes never benefit from provider fallback, retry logic, or vendor switching.
`classify_node.py` line 144 has `except Exception: pass` — GEES audit trail violation.

### Solution

Replace the direct REST block with a gateway call in all three nodes. Example for `classify_node.py`:

```python
# BEFORE:
try:
    import urllib.request
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
    # ... direct REST call ...
except Exception:
    pass  # ← GEES violation

# AFTER:
try:
    from core_platform.app.llm.gateway import get_platform_llm_gateway
    gateway = get_platform_llm_gateway()
    raw = await gateway.generate(
        task="text_generation",
        prompt=prompt,
        temperature=0.0,
        response_mime_type="application/json",
    )
    if raw:
        llm_result = EmailClassificationOutput(**raw)
except Exception as exc:
    logger.warning(
        "[ClassifyNode] LLM gateway failed for correlation_id=%s: %s — using deterministic fallback",
        state.get("correlation_id", "unknown"),
        exc,
    )
    # llm_result remains None → deterministic keyword fallback below
```

Apply the same pattern to `pm_extract_node.py` and `draft_node.py`.

### Acceptance Criteria
- [ ] All three nodes use `get_platform_llm_gateway().generate()` — no `urllib.request` import
- [ ] All three nodes have `logger.warning(...)` in except clause (never silent `pass`)
- [ ] Deterministic offline fallback still triggers when gateway returns `None`
- [ ] `test_mail_organizer_workflow.py` passes with gateway mocked at `core_platform.app.llm.gateway`
- [ ] Grep check: `grep -r "urllib.request" apps/mail_organizer/graph/nodes/` returns empty

---

## Section 5: TECH-1 — Fix Async/Sync Mismatch in All LLM Providers

### Problem
All four LLM providers are declared `async` but call synchronous `urllib.request.urlopen()` internally.
Under load, a 1–30 second LLM call blocks the entire FastAPI event loop. Two sequential blocking
calls can exceed WhatsApp's 20-second webhook timeout.

### Solution

Wrap the synchronous `_post_json()` call in `asyncio.to_thread()` in all four providers:

```python
import asyncio

async def generate(self, prompt: str, ...) -> Optional[Dict[str, Any]]:
    # Run blocking HTTP call in the default thread pool executor
    return await asyncio.to_thread(self._post_json, url, payload)
```

The `_post_json` method itself does not change — only the call site is wrapped.

**Files to modify:**
- `core_platform/app/llm/gemini_provider.py`
- `core_platform/app/llm/claude_provider.py`
- `core_platform/app/llm/openai_provider.py`
- `core_platform/app/llm/ollama_provider.py`

**Also fix:** `gemini_provider.generate_multimodal()` hardcodes `"mime_type": "image/jpeg"`.
Add `mime_type: str = "image/jpeg"` parameter and thread it to the payload.

### Acceptance Criteria
- [ ] All four `generate()` / `generate_multimodal()` use `await asyncio.to_thread(...)` for HTTP calls
- [ ] No `urllib.request.urlopen()` called directly inside any `async def` in the LLM module
- [ ] Concurrent `/health` request during active LLM call is served without blocking
- [ ] `test_llm_providers_full.py` tests remain passing (urllib mock still works from thread)
- [ ] `gemini_provider.generate_multimodal()` accepts `mime_type` parameter

---

## Section 6: TECH-2 — Implement Real Ollama Availability Check

### Problem
`OllamaProvider.is_available()` returns `True` whenever `base_url` is set. `self._available` is
declared `Optional[bool] = None` but never written. Gateway selects Ollama even when the server
is off, resulting in a full-timeout connection error before fallback.

### Solution

**File: `core_platform/app/llm/ollama_provider.py`**

Implement lazy health check with 60-second cache:

```python
def is_available(self) -> bool:
    """Check if Ollama server is reachable (lazy, cached 60 seconds)."""
    import time
    now = time.monotonic()
    if self._available is not None and now - self._last_check < 60.0:
        return self._available

    try:
        import urllib.request
        req = urllib.request.Request(f"{self._base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            self._available = resp.status == 200
    except Exception:
        self._available = False

    self._last_check = now
    return bool(self._available)
```

Add `_last_check: float = 0.0` to `__init__`.

### Acceptance Criteria
- [ ] `is_available()` returns `False` when Ollama is unreachable (mock `ConnectionRefusedError`)
- [ ] `is_available()` returns `True` when `/api/tags` responds with HTTP 200
- [ ] Availability cached for 60 seconds to avoid per-request probes
- [ ] Gateway fallback skips Ollama when unavailable and falls through to next provider
- [ ] `test_llm_providers_full.py` covers the offline case

---

## Section 7: TECH-3 — Fix JSON-RPC 2.0 Error Envelopes in MCP Server

### Problem
`_handle_tools_call()` in `mcp_server/server.py` raises `HTTPException` on tool errors, producing
HTTP 4xx/5xx instead of JSON-RPC 2.0 error envelopes. MCP clients parse tool responses from the
JSON-RPC body, not HTTP status — HTTP 500 breaks protocol compliance.

Also: SSE endpoint constructs `messages_endpoint` URL via fragile string replacement
(`str(request.url).replace("/sse", "/messages")`) — breaks if query strings are present.

### Solution

**Fix 1 — Tool error envelopes (`mcp_server/server.py`):**

```python
# BEFORE:
except Exception as exc:
    raise HTTPException(status_code=500, detail=str(exc))

# AFTER (MCP spec §6 — isError format):
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
```

**Fix 2 — SSE URL construction (`mcp_server/server.py`):**

```python
from core_platform.app.config import settings

messages_endpoint = (
    f"{settings.ORCHESTRATOR_BASE_URL}/mcp/messages"
    if getattr(settings, "ORCHESTRATOR_BASE_URL", None)
    else str(request.url).replace("/sse", "/messages").split("?")[0]
)
```

**File: `core_platform/app/config.py`**

Add:
```python
ORCHESTRATOR_BASE_URL: str = ""  # e.g. "https://my-kiosk.example.com" for reverse-proxy deployments
```

### Acceptance Criteria
- [ ] `_handle_tools_call()` never raises `HTTPException` — all error paths return `{"isError": True, "content": [...]}`
- [ ] `logger.error(..., exc_info=True)` called on tool failure (GEES audit trail)
- [ ] `ORCHESTRATOR_BASE_URL` added to `config.py` and `config/platform.env.example`
- [ ] SSE URL strips query parameters in the string-replace fallback
- [ ] `test_mcp_server_full.py`: new test where registered tool raises exception; asserts HTTP 200 and `{"isError": True}` in response body

---

## Implementation Sequence

```
Phase A (parallel, no deps):    TECH-1 | INT-1 | TECH-3
Phase B (after Phase A):        TECH-2 | INT-4
Phase C (after Phase B):        INT-3 | INT-2
```

| Phase | Defects | Estimated Effort |
|---|---|---|
| **Phase A** | TECH-1, INT-1, TECH-3 | ~1 day |
| **Phase B** | TECH-2, INT-4 | ~1 day |
| **Phase C** | INT-3, INT-2 | ~1.5 days |

---

## Verification Plan

```bash
# Full regression after all changes:
.venv\Scripts\python.exe -m pytest tests/unit --tb=short -q --cov=core_platform --cov=apps --cov-fail-under=80

# INT-4 verification — must return empty:
.venv\Scripts\python.exe -c "import subprocess; r = subprocess.run(['grep', '-r', 'urllib.request', 'apps/mail_organizer/graph/nodes/'], capture_output=True); print(r.stdout or 'CLEAN')"

# INT-1 verification — must return results:
.venv\Scripts\python.exe -c "import subprocess; r = subprocess.run(['grep', '-r', 'get_platform_rate_limiter', 'core_platform/app/ingress/'], capture_output=True); print(r.stdout)"
```

---

## Files Changed Summary

| File | Change | Section |
|---|---|---|
| `core_platform/app/ingress/whatsapp_router.py` | Add rate limiter call before workflow dispatch | INT-1 |
| `core_platform/app/mcp_server/server.py` | Rate limiter call; JSON-RPC error envelope fix; SSE URL fix | INT-1, TECH-3 |
| `core_platform/app/config.py` | Add `ORCHESTRATOR_BASE_URL` setting | TECH-3 |
| `config/platform.env.example` | Document `ORCHESTRATOR_BASE_URL` | TECH-3 |
| `core_platform/main.py` | Activate `PluginLoader` in lifespan; start `OutboxSynchronizer` | INT-2, INT-3 |
| `core_platform/app/plugin_engine/loader.py` | Add `get_loaded_app_ids()`; wire `register_app_tools()` in `_mount_single()` | INT-2 |
| `core_platform/app/outbox/synchronizer.py` | Fix silent data-loss fallback; add `mail_organizer` dispatch case | INT-3 |
| `apps/mail_organizer/graph/nodes/execution_node.py` | Enqueue to `PlatformOutboxQueue` on Gmail API failure | INT-3 |
| `apps/mail_organizer/graph/nodes/classify_node.py` | Replace direct REST with `gateway.generate()`; fix silent except | INT-4 |
| `apps/mail_organizer/graph/nodes/pm_extract_node.py` | Replace direct REST with `gateway.generate()`; fix silent except | INT-4 |
| `apps/mail_organizer/graph/nodes/draft_node.py` | Replace direct REST with `gateway.generate()`; fix silent except | INT-4 |
| `core_platform/app/llm/gemini_provider.py` | Wrap `_post_json` in `asyncio.to_thread()`; add `mime_type` param | TECH-1 |
| `core_platform/app/llm/claude_provider.py` | Wrap `_post_json` in `asyncio.to_thread()` | TECH-1 |
| `core_platform/app/llm/openai_provider.py` | Wrap `_post_json` in `asyncio.to_thread()` | TECH-1 |
| `core_platform/app/llm/ollama_provider.py` | Wrap `_post_json` in `asyncio.to_thread()`; implement real `is_available()` | TECH-1, TECH-2 |
| `tests/unit/test_llm_providers_full.py` | Add async/concurrent tests; Ollama offline test | TECH-1, TECH-2 |
| `tests/unit/test_mcp_server_full.py` | Add tool-error JSON-RPC envelope test | TECH-3 |
| `tests/unit/test_whatsapp_ingress.py` | Add rate-limit enforcement integration test | INT-1 |
| `tests/unit/test_plugin_engine.py` | Add `load_all()` + `shutdown_all()` lifecycle test | INT-2 |
| `tests/unit/test_platform_outbox.py` | Add mail organizer failure -> queue -> drain test | INT-3 |
| `tests/unit/test_mail_organizer_workflow.py` | Update to mock gateway instead of urllib | INT-4 |

**Total: ~20 file changes | Estimated: 3–4 days implementation**

---

## What This Plan Does NOT Cover

The following are deferred to future plans and must not be mixed into this implementation:

- **Security hardening (SEC-1 through SEC-8):** bcrypt, JWT revocation, CSRF, brute-force protection
- **Missed architecture planning (MISS-1 through MISS-10):** observability, multi-tenancy, API versioning, disaster recovery
- **ONNX face recognition (GAP-012/013):** commercial licensing decision pending
- **Location pipeline suspension (GAP-015):** requires dedicated webhook resume architecture
