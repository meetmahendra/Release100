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
Prometheus Metrics Registry & Exposition Engine.

Adheres strictly to Plan 09 / GEES v2.0 Enterprise Cloud Scale:
- Prometheus text exposition format (v0.0.4).
- Standardized industrial and platform operational metrics.
- Thread-safe in-memory counters, gauges, and latency histograms.
"""

from collections import defaultdict
import threading
import time
from typing import Dict, List, Optional, Tuple


class MetricsRegistry:
    """Thread-safe registry for Prometheus operational metrics."""

    _instance: Optional["MetricsRegistry"] = None

    @classmethod
    def get_instance(cls) -> "MetricsRegistry":
        """Get or initialize singleton MetricsRegistry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        self._histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], List[float]] = defaultdict(list)
        self._start_time: float = time.time()

    def _normalize_labels(self, labels: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
        """Convert labels dict to a sorted immutable tuple of (key, value) pairs."""
        if not labels:
            return ()
        return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

    def increment_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """Increment a monotonic counter metric."""
        lbls = self._normalize_labels(labels)
        with self._lock:
            self._counters[(name, lbls)] += value

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """Set an instantaneous gauge metric value."""
        lbls = self._normalize_labels(labels)
        with self._lock:
            self._gauges[(name, lbls)] = value

    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record an observation in a histogram metric."""
        lbls = self._normalize_labels(labels)
        with self._lock:
            self._histograms[(name, lbls)].append(value)
            # Limit stored histogram observations per label set
            if len(self._histograms[(name, lbls)]) > 500:
                self._histograms[(name, lbls)].pop(0)

    # Standardized Enterprise Convenience Helpers
    def record_duty_checkin(self, tenant: str, kiosk_id: str, status: str) -> None:
        """Record an employee duty check-in event."""
        self.increment_counter(
            "duty_checkins_total",
            1.0,
            {"tenant": tenant, "kiosk_id": kiosk_id, "status": status},
        )

    def record_haccp_violation(self, tenant: str, kiosk_id: str, severity: str) -> None:
        """Record a food safety HACCP temperature excursion event."""
        self.increment_counter(
            "haccp_violations_total",
            1.0,
            {"tenant": tenant, "kiosk_id": kiosk_id, "severity": severity},
        )

    def record_llm_request(
        self,
        provider: str,
        model: str,
        latency_seconds: float,
        cost_usd: float = 0.0,
        status: str = "success",
    ) -> None:
        """Record LLMGateway latency and financial token expenditure."""
        self.observe_histogram(
            "llm_latency_seconds",
            latency_seconds,
            {"provider": provider, "model": model, "status": status},
        )
        if cost_usd > 0:
            self.increment_counter(
                "llm_cost_total_usd",
                cost_usd,
                {"provider": provider, "model": model},
            )

    def set_outbox_queue_depth(self, app_id: str, depth: int) -> None:
        """Update the pending outbox queue depth gauge."""
        self.set_gauge("outbox_queue_depth", float(depth), {"app_id": app_id})

    def format_prometheus(self) -> str:
        """
        Generate Prometheus text exposition formatted payload (v0.0.4).
        """
        lines: List[str] = []
        now_sec = time.time()
        uptime = round(now_sec - self._start_time, 2)
        self.set_gauge("platform_uptime_seconds", uptime)

        with self._lock:
            # Format Gauges
            lines.append("# HELP platform_uptime_seconds Total runtime seconds of the platform host.")
            lines.append("# TYPE platform_uptime_seconds gauge")

            seen_help: set[str] = set()

            for (name, lbls), val in sorted(self._gauges.items()):
                if name not in seen_help:
                    lines.append(f"# HELP {name} Instantaneous gauge value.")
                    lines.append(f"# TYPE {name} gauge")
                    seen_help.add(name)
                lbl_str = ",".join(f'{k}="{v}"' for k, v in lbls)
                line = f"{name}{{{lbl_str}}} {val}" if lbl_str else f"{name} {val}"
                lines.append(line)

            # Format Counters
            for (name, lbls), val in sorted(self._counters.items()):
                if name not in seen_help:
                    lines.append(f"# HELP {name} Monotonically increasing counter value.")
                    lines.append(f"# TYPE {name} counter")
                    seen_help.add(name)
                lbl_str = ",".join(f'{k}="{v}"' for k, v in lbls)
                line = f"{name}{{{lbl_str}}} {val}" if lbl_str else f"{name} {val}"
                lines.append(line)

            # Format Histograms (count and sum)
            for (name, lbls), observations in sorted(self._histograms.items()):
                count_name = f"{name}_count"
                sum_name = f"{name}_sum"
                if name not in seen_help:
                    lines.append(f"# HELP {name} Latency or duration histogram observations.")
                    lines.append(f"# TYPE {name} histogram")
                    seen_help.add(name)
                lbl_str = ",".join(f'{k}="{v}"' for k, v in lbls)
                h_count = len(observations)
                h_sum = round(sum(observations), 4)
                line_count = f"{count_name}{{{lbl_str}}} {h_count}" if lbl_str else f"{count_name} {h_count}"
                line_sum = f"{sum_name}{{{lbl_str}}} {h_sum}" if lbl_str else f"{sum_name} {h_sum}"
                lines.append(line_count)
                lines.append(line_sum)

        return "\n".join(lines) + "\n"

    def clear(self) -> None:
        """Clear all stored metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# Global helper instance
metrics_registry = MetricsRegistry.get_instance()
