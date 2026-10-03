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
Interactive Verification Script for TypeSafe AI / Jev Live Integration.

Usage:
    python scripts/test_live_jev.py
    python scripts/test_live_jev.py --api-key <YOUR_KEY>
"""

import argparse
import asyncio
import os
import sys
import time
from typing import List

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core_platform.app.config import settings
from core_platform.app.llm.gateway import get_platform_llm_gateway
from core_platform.app.llm.typesafe_provider import TypeSafeProvider
from core_platform.app.routing.semantic_router import SemanticRouter
from core_platform.app.skills.intent_classifier import IntentClassifierSkill
from core_platform.app.skills.sentiment_urgency import SentimentUrgencySkill


async def run_live_verification(api_key: str, base_url: str, model: str) -> None:
    """Run step-by-step verification against TypeSafe AI / Jev."""
    print("=" * 70)
    print("  TYPESAFE AI / JEV LIVE INTEGRATION VERIFICATION")
    print("=" * 70)
    print(f"  Target Endpoint : {base_url}")
    print(f"  Model Identifier: {model}")
    print(f"  API Key Status  : {'Configured (' + api_key[:6] + '...)' if api_key else 'NOT CONFIGURED'}")
    print("-" * 70)

    if not api_key:
        print("\n[ERROR] No TypeSafe API key provided.")
        print("Please set TYPESAFE_API_KEY in your .env file or pass --api-key <YOUR_KEY>.")
        sys.exit(1)

    # ── Test 1: Direct Provider Connection ────────────────────────────────────
    print("\n[STEP 1/4] Direct TypeSafeProvider Inference...")
    provider = TypeSafeProvider(api_key=api_key, base_url=base_url, default_model=model)

    test_text = "Good morning! Recording temperature punch 98.4F at chiller station."
    choices = ["temperature_marker", "mail_organizer"]

    t0 = time.perf_counter()
    decision = await provider.classify(text=test_text, choices=choices, context="Kiosk WhatsApp Dispatch")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    if decision:
        print(f"  [SUCCESS] Selected Cartridge: {decision.selected_choice}")
        print(f"  [CONFIDENCE] {decision.confidence * 100:.1f}%")
        print(f"  [LATENCY]    {decision.latency_ms:.1f}ms (Roundtrip: {elapsed_ms:.1f}ms)")
        print(f"  [REASONING]  {decision.reasoning}")
    else:
        print(f"  [FAILED] Provider returned None. Error: {provider.last_error}")

    # ── Test 2: Platform LLM Gateway Dual-Tier Dispatch ───────────────────────
    print("\n[STEP 2/4] Platform LLM Gateway Task Routing...")
    # Inject API key into settings for gateway
    os.environ["TYPESAFE_API_KEY"] = api_key
    gateway = get_platform_llm_gateway()

    email_text = "URGENT: Database master node out of disk space, write queries failing!"
    email_choices = ["@Urgent", "@Action", "@Meeting", "@Promotions", "@Financial"]

    t0 = time.perf_counter()
    gw_decision = await gateway.classify(
        text=email_text,
        choices=email_choices,
        task="fast_classification",
        context="Executive Email Triage",
    )
    gw_elapsed = (time.perf_counter() - t0) * 1000.0

    if gw_decision:
        print(f"  [SUCCESS] Classified Category: {gw_decision.selected_choice}")
        print(f"  [CONFIDENCE] {gw_decision.confidence * 100:.1f}%")
        print(f"  [LATENCY]    {gw_decision.latency_ms:.1f}ms (Total: {gw_elapsed:.1f}ms)")
    else:
        print("  [FAILED] Gateway classify returned None.")

    # ── Test 3: Multi-Cartridge Semantic Router ───────────────────────────────
    print("\n[STEP 3/4] Multi-Cartridge Semantic Router (Microkernel)...")
    route_decision = await SemanticRouter.route(
        text_content="Please triage my unread emails from client ACME Corp and draft replies",
        candidate_apps=["temperature_marker", "mail_organizer"],
    )
    print(f"  [SELECTED APP]  {route_decision.selected_app}")
    print(f"  [CONFIDENCE]    {route_decision.confidence * 100:.1f}%")
    print(f"  [DISAMBIGUATE]  {route_decision.requires_disambiguation}")
    print(f"  [REASONING]     {route_decision.reasoning}")

    # ── Test 4: Universal Stateless Cognitive Skills ──────────────────────────
    print("\n[STEP 4/4] Universal Cognitive Skills (Sentiment & Urgency)...")
    urgency_skill = SentimentUrgencySkill()
    triage = await urgency_skill.assess_triage("Severe ammonia refrigerant leak detected in main cold room!")
    print(f"  [URGENCY LEVEL] {triage.urgency.value}")
    print(f"  [ESCALATION]    {triage.requires_escalation}")
    print(f"  [CONFIDENCE]    {triage.confidence * 100:.1f}%")
    print(f"  [REASONING]     {triage.reasoning}")

    print("\n" + "=" * 70)
    print("  TYPESAFE AI / JEV INTEGRATION TEST COMPLETED SUCCESSFULLY!")
    print("=" * 70)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Test live TypeSafe AI / Jev integration")
    parser.add_argument("--api-key", default=os.getenv("TYPESAFE_API_KEY", settings.TYPESAFE_API_KEY), help="TypeSafe AI API Key")
    parser.add_argument("--base-url", default=os.getenv("TYPESAFE_BASE_URL", settings.TYPESAFE_BASE_URL), help="TypeSafe AI Base URL")
    parser.add_argument("--model", default=os.getenv("TYPESAFE_MODEL", settings.TYPESAFE_MODEL), help="TypeSafe Model identifier")
    args = parser.parse_args()

    asyncio.run(run_live_verification(api_key=args.api_key, base_url=args.base_url, model=args.model))


if __name__ == "__main__":
    main()
