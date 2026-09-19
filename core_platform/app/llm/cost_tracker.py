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
Platform LLM Cost and Token Usage Tracker.

Provides granular, thread-safe telemetry for LLM calls:
  - Per-interaction records: prompt/completion tokens, model, provider, latency, estimated cost.
  - Per-trigger/operation aggregations: grouped by correlation ID / operation name.
  - Multi-provider pricing catalog (Gemini, Claude, OpenAI, Ollama).
  - In-memory ring buffer with optional JSONL persistence for SIEM/auditing.
"""

from __future__ import annotations

import collections
import datetime
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("core_platform.llm.cost_tracker")

# Pricing catalog: USD per 1M tokens (input_price_per_m, output_price_per_m)
# Based on standard published enterprise rates (2025/2026)
PROVIDER_PRICING_PER_1M: Dict[str, tuple[float, float]] = {
    # Gemini
    "gemini-2.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    # Claude
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    # Ollama / Local
    "ollama": (0.0, 0.0),
    "deepseek-r1:14b": (0.0, 0.0),
}

DEFAULT_FALLBACK_PRICE: tuple[float, float] = (0.10, 0.40)


@dataclass
class LLMInteractionRecord:
    """Telemetry record for a single LLM API request/response."""
    interaction_id: str
    operation_id: str  # Correlation ID / Trigger name (e.g. "whatsapp_inbound_corr123")
    task: str  # e.g. "intent_routing", "vision_processing", "text_generation"
    provider: str  # "gemini", "claude", "openai", "ollama"
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    success: bool
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LLMCostTracker:
    """Singleton tracking store for all LLM calls across the platform."""

    def __init__(self, max_records: int = 5000, jsonl_log_path: Optional[Path] = None) -> None:
        self._max_records = max_records
        self._records: collections.deque[LLMInteractionRecord] = collections.deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._jsonl_path = jsonl_log_path or Path("logs/llm_cost_audit.jsonl")

    @staticmethod
    def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost in USD based on model pricing."""
        rates = PROVIDER_PRICING_PER_1M.get(model, DEFAULT_FALLBACK_PRICE)
        cost_prompt = (prompt_tokens / 1_000_000.0) * rates[0]
        cost_completion = (completion_tokens / 1_000_000.0) * rates[1]
        return round(cost_prompt + cost_completion, 6)

    def record_interaction(
        self,
        *,
        interaction_id: str,
        operation_id: str,
        task: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> LLMInteractionRecord:
        """Record an LLM call interaction and append to memory buffer and disk audit log."""
        cost = self.calculate_cost(model, prompt_tokens, completion_tokens)
        record = LLMInteractionRecord(
            interaction_id=interaction_id,
            operation_id=operation_id,
            task=task,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=cost,
            latency_ms=round(latency_ms, 2),
            success=success,
            error_message=error_message,
        )

        with self._lock:
            self._records.append(record)

        try:
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception as exc:
            logger.warning("[LLMCostTracker] Failed to write to audit log: %s", exc)

        return record

    def get_summary(self) -> Dict[str, Any]:
        """Return high-level summary metrics across all recorded interactions."""
        with self._lock:
            records = list(self._records)

        total_interactions = len(records)
        total_tokens = sum(r.total_tokens for r in records)
        total_cost = sum(r.estimated_cost_usd for r in records)
        operations_count = len({r.operation_id for r in records})

        by_provider: Dict[str, Dict[str, Any]] = {}
        for r in records:
            if r.provider not in by_provider:
                by_provider[r.provider] = {"calls": 0, "tokens": 0, "cost_usd": 0.0}
            by_provider[r.provider]["calls"] += 1
            by_provider[r.provider]["tokens"] += r.total_tokens
            by_provider[r.provider]["cost_usd"] = round(by_provider[r.provider]["cost_usd"] + r.estimated_cost_usd, 6)

        return {
            "total_interactions": total_interactions,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "operations_count": operations_count,
            "by_provider": by_provider,
        }

    def get_operations_report(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return grouped operations with hierarchical list of interactions."""
        with self._lock:
            records = list(self._records)

        grouped: Dict[str, List[LLMInteractionRecord]] = collections.defaultdict(list)
        for r in records:
            grouped[r.operation_id].append(r)

        sorted_ops = sorted(
            grouped.items(),
            key=lambda item: item[1][-1].timestamp if item[1] else "",
            reverse=True
        )[:limit]

        result: List[Dict[str, Any]] = []
        for op_id, op_records in sorted_ops:
            tot_p = sum(x.prompt_tokens for x in op_records)
            tot_c = sum(x.completion_tokens for x in op_records)
            tot_cost = sum(x.estimated_cost_usd for x in op_records)
            tot_latency = sum(x.latency_ms for x in op_records)

            summary = {
                "operation_id": op_id,
                "first_seen": op_records[0].timestamp,
                "last_seen": op_records[-1].timestamp,
                "total_interactions": len(op_records),
                "total_prompt_tokens": tot_p,
                "total_completion_tokens": tot_c,
                "total_tokens": tot_p + tot_c,
                "total_cost_usd": round(tot_cost, 6),
                "total_latency_ms": round(tot_latency, 2),
                "interactions": [x.to_dict() for x in op_records],
            }
            result.append(summary)

        return result


_cost_tracker_instance: Optional[LLMCostTracker] = None
_cost_tracker_lock = threading.Lock()


def get_llm_cost_tracker() -> LLMCostTracker:
    """Return the platform-level LLMCostTracker singleton."""
    global _cost_tracker_instance
    if _cost_tracker_instance is None:
        with _cost_tracker_lock:
            if _cost_tracker_instance is None:
                _cost_tracker_instance = LLMCostTracker()
    return _cost_tracker_instance
