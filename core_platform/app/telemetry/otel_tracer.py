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
OpenTelemetry (OTel) Distributed Tracing Engine.

Adheres strictly to Plan 09 / GEES v2.0 Enterprise Cloud Scale:
- W3C traceparent standard compliance (version 00).
- Zero-overhead in-memory span recording with OTLP exporter integration hooks.
- Thread-safe and async-safe context propagation across Ingress, LangGraph, and LLMGateway.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Tuple
import uuid

from core_platform.app.config import settings

logger = logging.getLogger("core_platform.telemetry.tracer")

# W3C Traceparent Regex: 00-{32 hex trace_id}-{16 hex parent_id}-{02 hex flags}
_TRACEPARENT_REGEX = re.compile(r"^00-([0-9a-fA-F]{32})-([0-9a-fA-F]{16})-([0-9a-fA-F]{2})$")


@dataclass
class SpanContext:
    """Represents a single distributed trace span."""
    trace_id: str
    span_id: str
    name: str
    parent_span_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "OK"
    error_message: Optional[str] = None

    @property
    def traceparent(self) -> str:
        """Format as standard W3C Traceparent header string."""
        return f"00-{self.trace_id}-{self.span_id}-01"

    @property
    def duration_ms(self) -> float:
        """Calculate span duration in milliseconds."""
        if self.end_time is not None:
            return round((self.end_time - self.start_time) * 1000.0, 2)
        return round((time.time() - self.start_time) * 1000.0, 2)

    def set_attribute(self, key: str, value: Any) -> None:
        """Attach an attribute to the span."""
        self.attributes[key] = value

    def record_exception(self, exc: Exception) -> None:
        """Mark span status as ERROR and capture exception details."""
        self.status = "ERROR"
        self.error_message = str(exc)
        self.attributes["exception.type"] = type(exc).__name__
        self.attributes["exception.message"] = str(exc)

    def to_dict(self) -> Dict[str, Any]:
        """Convert span context to serializable dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_message": self.error_message,
            "attributes": dict(self.attributes),
            "traceparent": self.traceparent,
        }


_current_span_var: ContextVar[Optional[SpanContext]] = ContextVar("current_span_var", default=None)


class PlatformTracer:
    """Platform-wide distributed tracer managing span lifecycles and W3C propagation."""

    _instance: Optional["PlatformTracer"] = None

    @classmethod
    def get_instance(cls) -> "PlatformTracer":
        """Get or initialize singleton PlatformTracer instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.service_name = getattr(settings, "OTEL_SERVICE_NAME", "release100-platform")
        self.enabled = getattr(settings, "OTEL_ENABLED", False)
        self._completed_spans: List[SpanContext] = []
        self._max_stored_spans: int = 1000

    @staticmethod
    def parse_traceparent(traceparent: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse incoming W3C traceparent header.
        Returns (trace_id, parent_span_id) if valid, or (None, None).
        """
        if not traceparent:
            return None, None
        match = _TRACEPARENT_REGEX.match(traceparent.strip())
        if match:
            return match.group(1).lower(), match.group(2).lower()
        return None, None

    @staticmethod
    def generate_trace_id() -> str:
        """Generate a 32-hex character trace ID."""
        return uuid.uuid4().hex

    @staticmethod
    def generate_span_id() -> str:
        """Generate a 16-hex character span ID."""
        return uuid.uuid4().hex[:16]

    def get_active_span(self) -> Optional[SpanContext]:
        """Return the currently active SpanContext from the execution context."""
        return _current_span_var.get()

    def get_active_traceparent(self) -> Optional[str]:
        """Return the active W3C traceparent header string, if any."""
        span = self.get_active_span()
        return span.traceparent if span else None

    @contextmanager
    def trace_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        parent_traceparent: Optional[str] = None,
    ) -> Generator[SpanContext, None, None]:
        """
        Deterministic synchronous context manager for creating a trace span.

        Usage:
            with tracer.trace_span("db.query", {"query.type": "SELECT"}) as span:
                execute_db_call()
        """
        parent_span = self.get_active_span()
        parent_trace_id, parent_span_id = self.parse_traceparent(parent_traceparent)

        if parent_span is not None:
            trace_id = parent_span.trace_id
            p_span_id = parent_span.span_id
        elif parent_trace_id is not None:
            trace_id = parent_trace_id
            p_span_id = parent_span_id
        else:
            trace_id = self.generate_trace_id()
            p_span_id = None

        span = SpanContext(
            trace_id=trace_id,
            span_id=self.generate_span_id(),
            name=name,
            parent_span_id=p_span_id,
            attributes=dict(attributes or {}),
        )
        span.set_attribute("service.name", self.service_name)

        token = _current_span_var.set(span)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end_time = time.time()
            self._record_completed_span(span)
            _current_span_var.reset(token)

    @asynccontextmanager
    async def async_trace_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        parent_traceparent: Optional[str] = None,
    ) -> AsyncGenerator[SpanContext, None]:
        """
        Deterministic asynchronous context manager for creating a trace span.

        Usage:
            async with tracer.async_trace_span("llm.generate", {"provider": "gemini"}) as span:
                result = await llm_call()
        """
        parent_span = self.get_active_span()
        parent_trace_id, parent_span_id = self.parse_traceparent(parent_traceparent)

        if parent_span is not None:
            trace_id = parent_span.trace_id
            p_span_id = parent_span.span_id
        elif parent_trace_id is not None:
            trace_id = parent_trace_id
            p_span_id = parent_span_id
        else:
            trace_id = self.generate_trace_id()
            p_span_id = None

        span = SpanContext(
            trace_id=trace_id,
            span_id=self.generate_span_id(),
            name=name,
            parent_span_id=p_span_id,
            attributes=dict(attributes or {}),
        )
        span.set_attribute("service.name", self.service_name)

        token = _current_span_var.set(span)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end_time = time.time()
            self._record_completed_span(span)
            _current_span_var.reset(token)

    def _record_completed_span(self, span: SpanContext) -> None:
        """Internal ring-buffer persistence for span telemetry."""
        self._completed_spans.append(span)
        if len(self._completed_spans) > self._max_stored_spans:
            self._completed_spans.pop(0)

    def get_completed_spans(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent completed trace spans."""
        spans = self._completed_spans[-limit:]
        return [s.to_dict() for s in reversed(spans)]

    def clear_spans(self) -> None:
        """Clear recorded spans (primarily used in test suites)."""
        self._completed_spans.clear()


# Global helper instances
tracer = PlatformTracer.get_instance()
