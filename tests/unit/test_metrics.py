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
Unit Tests for Prometheus Metrics Registry & HTTP Exporter.

Adheres strictly to GEES v2.0 Dual-Engine Verification Regime (Engine A).
"""

from fastapi.testclient import TestClient
import pytest

from core_platform.app.telemetry.metrics import MetricsRegistry, metrics_registry
from core_platform.main import app


def test_metrics_registry_operations() -> None:
    """Verify counter, gauge, and histogram metric operations."""
    reg = MetricsRegistry()

    # Counter
    reg.increment_counter("custom_events_total", 1.0, {"env": "prod"})
    reg.increment_counter("custom_events_total", 2.0, {"env": "prod"})

    # Gauge
    reg.set_gauge("memory_usage_mb", 256.5, {"host": "kiosk-01"})

    # Histogram
    reg.observe_histogram("inference_latency", 0.045, {"model": "onnx"})
    reg.observe_histogram("inference_latency", 0.055, {"model": "onnx"})

    output = reg.format_prometheus()
    assert "# HELP custom_events_total" in output
    assert "# TYPE custom_events_total counter"
    assert 'custom_events_total{env="prod"} 3.0' in output

    assert "# HELP memory_usage_mb" in output
    assert 'memory_usage_mb{host="kiosk-01"} 256.5' in output

    assert "# HELP inference_latency" in output
    assert 'inference_latency_count{model="onnx"} 2' in output
    assert 'inference_latency_sum{model="onnx"} 0.1' in output


def test_standardized_telemetry_helpers() -> None:
    """Verify platform convenience recording methods."""
    reg = MetricsRegistry()

    reg.record_duty_checkin("tenant_foods", "K-04", "SUCCESS")
    reg.record_haccp_violation("tenant_foods", "K-04", "CRITICAL")
    reg.record_llm_request("gemini", "gemini-2.5-flash", latency_seconds=0.35, cost_usd=0.0004)
    reg.set_outbox_queue_depth("temperature_marker", 5)

    prom_text = reg.format_prometheus()
    assert "duty_checkins_total" in prom_text
    assert "haccp_violations_total" in prom_text
    assert "llm_latency_seconds_count" in prom_text
    assert "llm_cost_total_usd" in prom_text
    assert 'outbox_queue_depth{app_id="temperature_marker"} 5.0' in prom_text


def test_main_metrics_endpoint() -> None:
    """Verify GET /metrics returns HTTP 200 with Prometheus text format."""
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "platform_uptime_seconds" in response.text
