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
Unit Tests for OpenTelemetry (OTel) Distributed Tracing Engine.

Adheres strictly to GEES v2.0 Dual-Engine Verification Regime (Engine A).
"""

import asyncio
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from core_platform.app.telemetry.otel_tracer import PlatformTracer, SpanContext, tracer


def test_w3c_traceparent_parsing() -> None:
    """Verify standard W3C traceparent header regex parsing."""
    valid = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    trace_id, parent_id = PlatformTracer.parse_traceparent(valid)
    assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert parent_id == "00f067aa0ba902b7"

    invalid = "invalid-header-format"
    t_id, p_id = PlatformTracer.parse_traceparent(invalid)
    assert t_id is None
    assert p_id is None

    empty_t_id, empty_p_id = PlatformTracer.parse_traceparent(None)
    assert empty_t_id is None
    assert empty_p_id is None


def test_sync_trace_span_lifecycle() -> None:
    """Verify synchronous trace span lifecycle, attributes, and duration."""
    tracer.clear_spans()

    with tracer.trace_span("db.select_employees", {"table": "employees"}) as span:
        assert isinstance(span, SpanContext)
        assert span.name == "db.select_employees"
        assert span.attributes["table"] == "employees"
        assert span.attributes["service.name"] == tracer.service_name
        span.set_attribute("row_count", 42)

    completed = tracer.get_completed_spans(limit=10)
    assert len(completed) >= 1
    last_span = completed[0]
    assert last_span["name"] == "db.select_employees"
    assert last_span["status"] == "OK"
    assert last_span["attributes"]["row_count"] == 42
    assert last_span["duration_ms"] >= 0.0


def test_trace_span_exception_recording() -> None:
    """Verify exceptions in spans are captured with error metadata."""
    tracer.clear_spans()

    with pytest.raises(RuntimeError, match="Simulated DB timeout"):
        with tracer.trace_span("db.connect") as span:
            raise RuntimeError("Simulated DB timeout")

    completed = tracer.get_completed_spans(limit=10)
    assert len(completed) >= 1
    span_dict = completed[0]
    assert span_dict["status"] == "ERROR"
    assert "Simulated DB timeout" in str(span_dict["error_message"])
    assert span_dict["attributes"]["exception.type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_async_trace_span_hierarchy() -> None:
    """Verify parent-child trace_id inheritance across nested async spans."""
    tracer.clear_spans()

    async with tracer.async_trace_span("parent_ingress") as parent_span:
        assert tracer.get_active_traceparent() is not None
        await asyncio.sleep(0.01)

        async with tracer.async_trace_span("child_llm") as child_span:
            assert child_span.trace_id == parent_span.trace_id
            assert child_span.parent_span_id == parent_span.span_id

    completed = tracer.get_completed_spans(limit=10)
    assert len(completed) >= 2
    # completed is reversed (latest first): child then parent
    child = next(s for s in completed if s["name"] == "child_llm")
    parent = next(s for s in completed if s["name"] == "parent_ingress")
    assert child["trace_id"] == parent["trace_id"]
    assert child["parent_span_id"] == parent["span_id"]


def test_http_tracing_middleware() -> None:
    """Verify distributed tracing middleware propagates traceparent in HTTP responses."""
    test_app = FastAPI()

    @test_app.middleware("http")
    async def tracing_middleware(request: Request, call_next):
        traceparent = request.headers.get("traceparent")
        async with tracer.async_trace_span(f"{request.method} {request.url.path}", parent_traceparent=traceparent) as span:
            response = await call_next(request)
            response.headers["traceparent"] = span.traceparent
            return response

    @test_app.get("/test-trace")
    async def endpoint():
        return JSONResponse({"ok": True})

    client = TestClient(test_app)

    # 1. Without traceparent header -> generates new traceparent
    res1 = client.get("/test-trace")
    assert res1.status_code == 200
    assert "traceparent" in res1.headers
    tp1 = res1.headers["traceparent"]
    assert tp1.startswith("00-")

    # 2. With incoming traceparent header -> inherits trace_id
    incoming_tp = "00-1234567890abcdef1234567890abcdef-fedcba0987654321-01"
    res2 = client.get("/test-trace", headers={"traceparent": incoming_tp})
    assert res2.status_code == 200
    assert "traceparent" in res2.headers
    tp2 = res2.headers["traceparent"]
    trace_id, _ = PlatformTracer.parse_traceparent(tp2)
    assert trace_id == "1234567890abcdef1234567890abcdef"
