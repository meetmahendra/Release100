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
Platform LLM Cost, Token Usage & Multi-Tenant Attribution Tracker.

Provides granular, thread-safe telemetry for LLM calls:
  - Per-interaction records: prompt/completion tokens, model, provider, latency, estimated cost,
    tenant_id, cartridge_id, and credential_mode (PLATFORM_MANAGED vs CUSTOMER_BYOK vs CORE_INTERNAL_JEV).
  - Multi-tenant expenditure aggregation & financial liability isolation:
      * PLATFORM_MANAGED: Invoiced to customers, platform incurs real vendor API cost.
      * CUSTOMER_BYOK: Zero platform financial liability ($0.00), tracked for customer visibility.
      * CORE_INTERNAL_JEV: Microkernel intent routing / System 1 fixed infrastructure cost.
  - Product optimization & cost hotspots analysis:
      * Analyzes average token consumption, error rates, latencies, and architectural optimization tips.
  - In-memory ring buffer with JSONL persistence for SIEM/auditing.
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
    "gemini-3.6-flash": (0.075, 0.30),
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
    # TypeSafe / Jev System 1 (Internal Core Microkernel)
    "typesafe": (0.001, 0.002),
    "jev-1": (0.001, 0.002),
    # Ollama / Local
    "ollama": (0.0, 0.0),
    "deepseek-r1:14b": (0.0, 0.0),
}

DEFAULT_FALLBACK_PRICE: tuple[float, float] = (0.10, 0.40)


@dataclass
class LLMInteractionRecord:
    """Telemetry record for a single LLM API request/response with multi-tenant context."""
    interaction_id: str
    operation_id: str  # Correlation ID / Trigger name (e.g. "whatsapp_inbound_corr123")
    task: str  # e.g. "intent_routing", "vision_ocr", "biometric_match", "text_generation"
    provider: str  # "gemini", "claude", "openai", "typesafe", "ollama"
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    success: bool
    error_message: Optional[str] = None
    tenant_id: str = "default_tenant"
    cartridge_id: str = "core_platform"
    credential_mode: str = "PLATFORM_MANAGED"  # "PLATFORM_MANAGED", "CUSTOMER_BYOK", "CORE_INTERNAL_JEV"
    is_platform_liability: bool = True
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to JSON-serializable dictionary."""
        return asdict(self)


class LLMCostTracker:
    """Singleton tracking store for all LLM and cognitive calls across the platform."""

    def __init__(self, max_records: int = 5000, jsonl_log_path: Optional[Path] = None) -> None:
        self._max_records = max_records
        self._records: collections.deque[LLMInteractionRecord] = collections.deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._jsonl_path = jsonl_log_path or Path("logs/llm_cost_audit.jsonl")
        self._load_existing_records()

    def _load_existing_records(self) -> None:
        """Replay historical audit records from JSONL file into memory on startup with backward compatibility."""
        if not self._jsonl_path.exists():
            return
        try:
            with open(self._jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if "tenant_id" not in data:
                            data["tenant_id"] = "default_tenant"
                        if "cartridge_id" not in data:
                            data["cartridge_id"] = "core_platform"
                        if "credential_mode" not in data:
                            data["credential_mode"] = "PLATFORM_MANAGED"
                        if "is_platform_liability" not in data:
                            data["is_platform_liability"] = data.get("credential_mode") != "CUSTOMER_BYOK"
                        rec = LLMInteractionRecord(**data)
                        self._records.append(rec)
                    except Exception:
                        pass
        except Exception as err:
            logger.warning("[LLMCostTracker] Failed to load existing audit records: %s", err)

    @staticmethod
    def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost in USD based on model pricing."""
        rates = PROVIDER_PRICING_PER_1M.get(model, DEFAULT_FALLBACK_PRICE)
        cost_prompt = (prompt_tokens / 1_000_000.0) * rates[0]
        cost_completion = (completion_tokens / 1_000_000.0) * rates[1]
        raw_cost = cost_prompt + cost_completion
        if raw_cost > 0.0 and round(raw_cost, 6) == 0.0:
            return round(raw_cost, 8)
        return round(raw_cost, 6)

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
        tenant_id: Optional[str] = None,
        cartridge_id: Optional[str] = None,
        credential_mode: Optional[str] = None,
    ) -> LLMInteractionRecord:
        """Record an LLM call interaction and append to memory buffer and disk audit log.

        Resolves tenant_id, cartridge_id, and credential_mode with zero-hardcoding defaults.
        """
        # 1. Resolve tenant_id
        eff_tenant = (tenant_id or "").strip()
        if not eff_tenant:
            try:
                from core_platform.app.middleware.tenant_context import get_current_tenant_id
                eff_tenant = get_current_tenant_id()
            except Exception:
                eff_tenant = "default_tenant"

        # 2. Resolve cartridge_id
        eff_cartridge = (cartridge_id or "").strip()
        if not eff_cartridge:
            if task in ("intent_routing", "fast_classification"):
                eff_cartridge = "core_router"
            elif task in ("vision_ocr", "biometric_match"):
                eff_cartridge = "core_skills"
            else:
                eff_cartridge = "core_platform"

        # 3. Resolve credential_mode
        eff_cred_mode = (credential_mode or "").strip().upper()
        if not eff_cred_mode:
            if (
                provider in ("typesafe", "jev", "local", "ollama")
                or (task in ("intent_routing", "fast_classification") and eff_tenant in ("platform", "system", "default", "default_tenant"))
            ):
                eff_cred_mode = "CORE_INTERNAL_JEV"
            else:
                eff_cred_mode = "PLATFORM_MANAGED"

        # Financial liability isolation:
        # CUSTOMER_BYOK -> 0.00 Platform Financial Liability (customer pays vendor directly)
        # PLATFORM_MANAGED & CORE_INTERNAL_JEV -> Platform Financial Liability (billed to platform account)
        is_liability = eff_cred_mode != "CUSTOMER_BYOK"

        cost = self.calculate_cost(model, prompt_tokens, completion_tokens)
        if not success and error_message and ("HTTP 4" in error_message or "INVALID_ARGUMENT" in error_message):
            cost = 0.0
            prompt_tokens = 0
            completion_tokens = 0

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
            tenant_id=eff_tenant,
            cartridge_id=eff_cartridge,
            credential_mode=eff_cred_mode,
            is_platform_liability=is_liability,
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
        """Return high-level summary metrics with financial liability and mode breakdown."""
        with self._lock:
            records = list(self._records)

        total_interactions = len(records)
        total_tokens = sum(r.total_tokens for r in records)
        total_cost = sum(r.estimated_cost_usd for r in records)
        total_platform_liability = sum(r.estimated_cost_usd for r in records if r.is_platform_liability)
        total_byok_value = sum(r.estimated_cost_usd for r in records if not r.is_platform_liability)
        total_internal_jev_cost = sum(r.estimated_cost_usd for r in records if r.credential_mode == "CORE_INTERNAL_JEV")
        operations_count = len({r.operation_id for r in records})

        by_provider: Dict[str, Dict[str, Any]] = {}
        for r in records:
            if r.provider not in by_provider:
                by_provider[r.provider] = {"calls": 0, "tokens": 0, "cost_usd": 0.0}
            by_provider[r.provider]["calls"] += 1
            by_provider[r.provider]["tokens"] += r.total_tokens
            by_provider[r.provider]["cost_usd"] = round(by_provider[r.provider]["cost_usd"] + r.estimated_cost_usd, 6)

        by_credential_mode: Dict[str, Dict[str, Any]] = {}
        for r in records:
            cm = r.credential_mode
            if cm not in by_credential_mode:
                by_credential_mode[cm] = {"calls": 0, "tokens": 0, "cost_usd": 0.0, "platform_liability_usd": 0.0}
            by_credential_mode[cm]["calls"] += 1
            by_credential_mode[cm]["tokens"] += r.total_tokens
            by_credential_mode[cm]["cost_usd"] = round(by_credential_mode[cm]["cost_usd"] + r.estimated_cost_usd, 6)
            if r.is_platform_liability:
                by_credential_mode[cm]["platform_liability_usd"] = round(
                    by_credential_mode[cm]["platform_liability_usd"] + r.estimated_cost_usd, 6
                )

        by_cartridge: Dict[str, Dict[str, Any]] = {}
        for r in records:
            c = r.cartridge_id
            if c not in by_cartridge:
                by_cartridge[c] = {"calls": 0, "tokens": 0, "cost_usd": 0.0, "platform_liability_usd": 0.0}
            by_cartridge[c]["calls"] += 1
            by_cartridge[c]["tokens"] += r.total_tokens
            by_cartridge[c]["cost_usd"] = round(by_cartridge[c]["cost_usd"] + r.estimated_cost_usd, 6)
            if r.is_platform_liability:
                by_cartridge[c]["platform_liability_usd"] = round(
                    by_cartridge[c]["platform_liability_usd"] + r.estimated_cost_usd, 6
                )

        by_tenant: Dict[str, Dict[str, Any]] = {}
        for r in records:
            t = r.tenant_id
            if t not in by_tenant:
                by_tenant[t] = {"calls": 0, "tokens": 0, "cost_usd": 0.0, "platform_liability_usd": 0.0}
            by_tenant[t]["calls"] += 1
            by_tenant[t]["tokens"] += r.total_tokens
            by_tenant[t]["cost_usd"] = round(by_tenant[t]["cost_usd"] + r.estimated_cost_usd, 6)
            if r.is_platform_liability:
                by_tenant[t]["platform_liability_usd"] = round(
                    by_tenant[t]["platform_liability_usd"] + r.estimated_cost_usd, 6
                )

        return {
            "total_interactions": total_interactions,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "total_platform_liability_usd": round(total_platform_liability, 4),
            "total_byok_value_usd": round(total_byok_value, 4),
            "total_internal_jev_cost_usd": round(total_internal_jev_cost, 8) if 0 < total_internal_jev_cost < 0.0001 else round(total_internal_jev_cost, 6),
            "operations_count": operations_count,
            "by_provider": by_provider,
            "by_credential_mode": by_credential_mode,
            "by_cartridge": by_cartridge,
            "by_tenant": by_tenant,
        }

    def get_tenant_breakdown(self) -> List[Dict[str, Any]]:
        """Return aggregated cost and token usage breakdown grouped per customer / tenant."""
        with self._lock:
            records = list(self._records)

        grouped: Dict[str, List[LLMInteractionRecord]] = collections.defaultdict(list)
        for r in records:
            grouped[r.tenant_id].append(r)

        result: List[Dict[str, Any]] = []
        for tid, recs in sorted(grouped.items(), key=lambda x: x[0]):
            modes = {x.credential_mode for x in recs}
            cred_mode_display = list(modes)[0] if len(modes) == 1 else "MIXED"
            tot_p = sum(x.prompt_tokens for x in recs)
            tot_c = sum(x.completion_tokens for x in recs)
            tot_tokens = tot_p + tot_c
            tot_cost = sum(x.estimated_cost_usd for x in recs)
            plat_cost = sum(x.estimated_cost_usd for x in recs if x.is_platform_liability)
            byok_cost = sum(x.estimated_cost_usd for x in recs if not x.is_platform_liability)
            cartridges = sorted(list({x.cartridge_id for x in recs}))

            result.append({
                "tenant_id": tid,
                "credential_mode": cred_mode_display,
                "total_interactions": len(recs),
                "prompt_tokens": tot_p,
                "completion_tokens": tot_c,
                "total_tokens": tot_tokens,
                "total_cost_usd": round(tot_cost, 6),
                "platform_liability_usd": round(plat_cost, 6),
                "byok_value_usd": round(byok_cost, 6),
                "cartridges_used": cartridges,
                "first_seen": recs[0].timestamp if recs else "",
                "last_seen": recs[-1].timestamp if recs else "",
            })

        return result

    def get_cartridge_breakdown(self) -> List[Dict[str, Any]]:
        """Return aggregated usage and latency metrics grouped per application cartridge."""
        with self._lock:
            records = list(self._records)

        grouped: Dict[str, List[LLMInteractionRecord]] = collections.defaultdict(list)
        for r in records:
            grouped[r.cartridge_id].append(r)

        result: List[Dict[str, Any]] = []
        for cid, recs in sorted(grouped.items(), key=lambda x: x[0]):
            tot_toks = sum(x.total_tokens for x in recs)
            tot_cost = sum(x.estimated_cost_usd for x in recs)
            plat_cost = sum(x.estimated_cost_usd for x in recs if x.is_platform_liability)
            avg_lat = sum(x.latency_ms for x in recs) / len(recs) if recs else 0.0
            tasks = sorted(list({x.task for x in recs}))

            result.append({
                "cartridge_id": cid,
                "total_interactions": len(recs),
                "total_tokens": tot_toks,
                "total_cost_usd": round(tot_cost, 6),
                "platform_liability_usd": round(plat_cost, 6),
                "avg_latency_ms": round(avg_lat, 1),
                "tasks_used": tasks,
            })

        return result

    def get_product_optimization_insights(self) -> List[Dict[str, Any]]:
        """Analyze workload hotspots to identify optimization and cost-saving opportunities."""
        with self._lock:
            records = list(self._records)

        grouped: Dict[tuple[str, str, str], List[LLMInteractionRecord]] = collections.defaultdict(list)
        for r in records:
            grouped[(r.cartridge_id, r.task, r.model)].append(r)

        insights: List[Dict[str, Any]] = []
        for (cartridge, task, model), recs in grouped.items():
            calls = len(recs)
            total_toks = sum(x.total_tokens for x in recs)
            tot_p = sum(x.prompt_tokens for x in recs)
            tot_c = sum(x.completion_tokens for x in recs)
            avg_toks = total_toks / calls if calls else 0.0
            avg_prompt = tot_p / calls if calls else 0.0
            avg_comp = tot_c / calls if calls else 0.0
            avg_lat = sum(x.latency_ms for x in recs) / calls if calls else 0.0
            tot_cost = sum(x.estimated_cost_usd for x in recs)
            plat_cost = sum(x.estimated_cost_usd for x in recs if x.is_platform_liability)
            errors = sum(1 for x in recs if not x.success)
            err_rate = (errors / calls * 100.0) if calls else 0.0
            provider = recs[0].provider if recs else "unknown"

            # Determine architectural recommendation
            rec_text = "Optimal execution profile."
            if task in ("intent_routing", "fast_classification") and provider in ("typesafe", "jev", "local"):
                rec_text = "⚡ Efficient Microkernel Fast-Path: Zero cloud latency, high throughput."
            elif task in ("intent_routing", "fast_classification") and provider not in ("typesafe", "jev"):
                rec_text = "⚠️ System 2 fallback active for routing: Check TypeSafe/Jev health to save Gemini cloud costs."
            elif err_rate > 10.0:
                rec_text = f"🚨 High failure rate ({err_rate:.1f}%): Inspect upstream quota or malformed prompt schema."
            elif avg_prompt > 1000 and calls >= 5:
                rec_text = f"💡 High prompt volume ({avg_prompt:.0f} avg toks): Implement semantic prompt caching or trimming."
            elif avg_lat > 2500:
                rec_text = f"⏱️ High latency ({avg_lat:.0f}ms): Consider flash model or parallel execution."
            elif tot_cost > 0.05:
                rec_text = "💰 High cost driver: Profile output token schema to reduce completion length."

            insights.append({
                "cartridge_id": cartridge,
                "task": task,
                "provider": provider,
                "model": model,
                "total_calls": calls,
                "total_tokens": total_toks,
                "avg_tokens_per_call": round(avg_toks, 1),
                "avg_prompt_tokens": round(avg_prompt, 1),
                "avg_completion_tokens": round(avg_comp, 1),
                "avg_latency_ms": round(avg_lat, 1),
                "total_cost_usd": round(tot_cost, 6),
                "platform_liability_usd": round(plat_cost, 6),
                "error_count": errors,
                "error_rate_pct": round(err_rate, 1),
                "recommendation": rec_text,
            })

        # Sort by total cost descending
        insights.sort(key=lambda x: x["total_cost_usd"], reverse=True)
        return insights

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
            tot_plat_cost = sum(x.estimated_cost_usd for x in op_records if x.is_platform_liability)
            tot_latency = sum(x.latency_ms for x in op_records)

            summary = {
                "operation_id": op_id,
                "tenant_id": op_records[0].tenant_id,
                "cartridge_id": op_records[0].cartridge_id,
                "credential_mode": op_records[0].credential_mode,
                "first_seen": op_records[0].timestamp,
                "last_seen": op_records[-1].timestamp,
                "total_interactions": len(op_records),
                "total_prompt_tokens": tot_p,
                "total_completion_tokens": tot_c,
                "total_tokens": tot_p + tot_c,
                "total_cost_usd": round(tot_cost, 6),
                "platform_liability_usd": round(tot_plat_cost, 6),
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
