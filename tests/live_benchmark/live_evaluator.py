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
High-Fidelity Live Benchmark Evaluator Engine.

Adheres strictly to GEES v1.0 (Pillar 2, Engine B).
Executes catalog scenarios against the active domain workflow, measuring:
1. Hard safety pass rate (mandatory 100%).
2. Functional pass rate (standard >= 80%).
3. Step latency and assertion compliance.
"""

import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.state import MailOrganizerState
from apps.mail_organizer.graph.state_graph import MailOrganizerWorkflow
from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.telemetry.audit_engine import AuditEngine


class LiveBenchmarkEvaluator:
    """Evaluates catalog scenarios against the active domain workflow."""

    def __init__(self, catalog_path: str, temp_dir: Path) -> None:
        """Initialize evaluator with catalog and isolated test database.

        Args:
            catalog_path: Path to scenario catalog JSON.
            temp_dir: Isolated scratch directory for database and audit logs.
        """
        self.catalog_path = Path(catalog_path)
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        with open(self.catalog_path, "r", encoding="utf-8") as f:
            catalog_meta = json.load(f)
        self.domain = catalog_meta.get("domain", "temperature_marker")

        self.audit_engine = AuditEngine(audit_dir=self.temp_dir / "audit_logs")

        if self.domain == "mail_organizer":
            db_file = self.temp_dir / "live_mail.db"
            self.mail_db_service = MailDatabaseService(db_url=f"sqlite:///{db_file}")
            # Seed VIP rules
            self.mail_db_service.add_rule(
                rule_type="vip",
                pattern="ceo@customer-enterprise.com",
                action="tag_vip",
            )
            self.mail_workflow = MailOrganizerWorkflow(
                db_service=self.mail_db_service,
                audit_engine=self.audit_engine,
            )
            self.tm_db_service = None
            self.tm_workflow = None
        else:
            db_file = self.temp_dir / "live_benchmark.db"
            self.tm_db_service = DatabaseService(db_url=f"sqlite:///{db_file}")
            self._seed_employees()
            self.kg_service = KnowledgeGraphService()
            self.tm_workflow = TemperatureMarkerWorkflow(
                db_service=self.tm_db_service,
                kg_service=self.kg_service,
                audit_engine=self.audit_engine,
            )
            from core_platform.app.ingress.location_session import reset_prompt_dates
            reset_prompt_dates()
            self.mail_db_service = None
            self.mail_workflow = None

    def close(self) -> None:
        """Dispose database connections and release resources."""
        if self.tm_db_service:
            self.tm_db_service.close()

    def _seed_employees(self) -> None:
        """Seed test employees for Pune, Mumbai, and Bangalore kiosks."""
        assert self.tm_db_service is not None
        # Pune Operator (Active)
        self.tm_db_service.register_employee(
            emp_code="EMP-1042",
            full_name="Rajesh Pawar",
            phone_number="+919800011122",
            assigned_kiosk_id="CANEBOT-PUNE-04",
            status="ACTIVE",
        )
        # Mumbai Operator (Active)
        self.tm_db_service.register_employee(
            emp_code="EMP-2088",
            full_name="Sunil Patil",
            phone_number="+919800022233",
            assigned_kiosk_id="CANEBOT-MUMBAI-08",
            status="ACTIVE",
        )
        # Bangalore Operator (Active)
        self.tm_db_service.register_employee(
            emp_code="EMP-3012",
            full_name="Kiran Kumar",
            phone_number="+919800033344",
            assigned_kiosk_id="CANEBOT-BLR-02",
            status="ACTIVE",
        )
        # Pending Operator (Awaiting Approval)
        self.tm_db_service.register_employee(
            emp_code="EMP-9999",
            full_name="Amit Sharma",
            phone_number="+919800044455",
            assigned_kiosk_id="CANEBOT-PUNE-04",
            status="PENDING_APPROVAL",
        )
        # Unchecked-in Active Operator (For No-GPS Prompt Scenarios)
        self.tm_db_service.register_employee(
            emp_code="EMP-4050",
            full_name="Deepak Mane",
            phone_number="+919800055566",
            assigned_kiosk_id="CANEBOT-PUNE-04",
            status="ACTIVE",
        )

    async def run_scenario(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single scenario and evaluate assertions.

        Args:
            scenario: Dictionary from scenario catalog.

        Returns:
            Dictionary recording scenario evaluation results and latencies.
        """
        scenario_id = scenario["id"]
        name = scenario["name"]
        is_safety = scenario.get("is_safety_critical", False)
        inp = scenario["input"]
        expected = scenario.get("expected", {})

        start_time = time.perf_counter()

        if self.domain == "mail_organizer":
            mail_state: MailOrganizerState = {
                "gmail_id": inp.get("gmail_id", f"msg_{scenario_id}"),
                "thread_id": inp.get("thread_id", f"thread_{scenario_id}"),
                "sender": inp.get("sender", "user@company.com"),
                "to_recipients": inp.get("to_recipients", ["depali@company.com"]),
                "cc_recipients": inp.get("cc_recipients", []),
                "subject": inp.get("subject", ""),
                "body": inp.get("body", ""),
                "snippet": inp.get("body", "")[:120],
                "auto_reply_headers": {},
                "is_vip": False,
                "is_no_reply": False,
                "has_critical_subject": False,
                "category": "",
                "urgency_score": 5,
                "confidence_score": 0.0,
                "reasoning": "",
                "context_tags": [],
                "is_reply_necessary": False,
                "safety_override": False,
                "override_reason": None,
                "is_scheduling_request": False,
                "calendar_availability": None,
                "responsibility_role": "PRIMARY_ACTIONEE",
                "delegation_target": None,
                "suggested_reply": None,
                "pending_pm_tasks": [],
                "gmail_actions": [],
                "execution_mode": inp.get("execution_mode", "shadow"),
                "actions_taken": [],
                "error_message": None,
                "pipeline_trace": [],
                "correlation_id": inp.get("gmail_id", f"msg_{scenario_id}"),
            }
            assert self.mail_workflow is not None
            final_state = await self.mail_workflow.execute(mail_state)
        else:
            # Prepare initial state
            raw_img = inp.get("raw_image_bytes")
            raw_bytes = raw_img.encode("utf-8") if isinstance(raw_img, str) else raw_img

            coords = inp.get("user_coords")
            user_coords_tuple = tuple(coords) if coords is not None else None

            initial_state: TemperatureMarkerState = {
                "correlation_id": inp.get("correlation_id", f"corr-{scenario_id}"),
                "sender_phone": inp.get("sender_phone", ""),
                "kiosk_id": inp.get("kiosk_id", "CANEBOT-PUNE-04"),
                "user_coords": user_coords_tuple,  # type: ignore
                "raw_image_bytes": raw_bytes,
            }

            # Override face confidence for test if specified
            if "force_low_face_conf" in inp:
                initial_state["face_confidence"] = inp["force_low_face_conf"]
            elif "face_confidence" in inp:
                initial_state["face_confidence"] = inp["face_confidence"]

            assert self.tm_workflow is not None
            final_state = await self.tm_workflow.execute(initial_state)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Evaluate Assertions
        passed = True
        failure_reasons = []

        for key, exp_val in expected.items():
            if key == "must_contain_reply":
                actual_reply = final_state.get("reply_message", "")
                if exp_val not in actual_reply:
                    passed = False
                    failure_reasons.append(f"Reply missing expected text: '{exp_val}'")
            elif key == "has_audit_hash":
                if not final_state.get("audit_record_hash"):
                    passed = False
                    failure_reasons.append("Expected audit_record_hash but found none")
            elif key == "has_sequence_number":
                if not final_state.get("audit_sequence_number"):
                    passed = False
                    failure_reasons.append("Expected audit_sequence_number but found none")
            else:
                actual_val = final_state.get(key)
                if actual_val != exp_val:
                    passed = False
                    failure_reasons.append(f"Field '{key}': expected {exp_val}, got {actual_val}")

        return {
            "id": scenario_id,
            "name": name,
            "description": scenario.get("description", ""),
            "category": scenario.get("category", "general"),
            "is_safety_critical": is_safety,
            "passed": passed,
            "failure_reason": "; ".join(failure_reasons) if failure_reasons else "",
            "latency_ms": round(latency_ms, 2),
            "final_state": final_state,
        }

    async def evaluate_suite(self, limit: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Run all scenarios in catalog and produce summary metrics.

        Args:
            limit: Optional limit on number of scenarios to evaluate.

        Returns:
            Tuple of (scenario_results, summary_metrics).
        """
        with open(self.catalog_path, "r", encoding="utf-8") as f:
            catalog_data = json.load(f)

        scenarios = catalog_data.get("scenarios", [])
        if limit is not None:
            scenarios = scenarios[:limit]

        start_all = time.perf_counter()
        results: List[Dict[str, Any]] = []

        total_scenarios = len(scenarios)
        passed_scenarios = 0
        safety_total = 0
        safety_passed = 0

        for sc in scenarios:
            res = await self.run_scenario(sc)
            results.append(res)
            if res["passed"]:
                passed_scenarios += 1
            if res["is_safety_critical"]:
                safety_total += 1
                if res["passed"]:
                    safety_passed += 1

        total_duration = time.perf_counter() - start_all

        functional_rate = (passed_scenarios / total_scenarios * 100.0) if total_scenarios > 0 else 0.0
        safety_rate = (safety_passed / safety_total * 100.0) if safety_total > 0 else 100.0

        # Quality Gate: 100.0% Hard Safety + >= 80.0% Functional Pass Rate
        quality_gate_passed = (safety_rate == 100.0) and (functional_rate >= 80.0)

        summary = {
            "suite_name": catalog_data.get("suite_name", "Live Benchmark"),
            "domain": catalog_data.get("domain", "temperature_marker"),
            "total_scenarios": total_scenarios,
            "passed_scenarios": passed_scenarios,
            "failed_scenarios": total_scenarios - passed_scenarios,
            "functional_pass_rate_pct": round(functional_rate, 2),
            "safety_scenarios_count": safety_total,
            "safety_passed_count": safety_passed,
            "safety_pass_rate_pct": round(safety_rate, 2),
            "quality_gate_passed": quality_gate_passed,
            "duration_seconds": round(total_duration, 2),
        }

        return results, summary
