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
State Graph Assembly for Mail Organizer Cartridge.

Adheres strictly to Plan 04 v1.0 Section 3 and GEES v1.0.
Assembled using official LangGraph v1.2.11 StateGraph with conditional edges,
deterministic pre-check, Layer 1 stochastic reasoning, Layer 2 safety guardrail,
calendar enrichment, and action planning.
"""

from typing import Any, Callable, Dict, Optional, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from apps.mail_organizer.connectors.calendar_connector import GoogleCalendarConnector
from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.nodes.action_planner_node import action_planner_node
from apps.mail_organizer.graph.nodes.calendar_node import calendar_node
from apps.mail_organizer.graph.nodes.classify_node import classify_node
from apps.mail_organizer.graph.nodes.draft_node import draft_node
from apps.mail_organizer.graph.nodes.execution_node import execution_node
from apps.mail_organizer.graph.nodes.guardrail_node import guardrail_node
from apps.mail_organizer.graph.nodes.ownership_node import ownership_node
from apps.mail_organizer.graph.nodes.pm_extract_node import pm_extract_node
from apps.mail_organizer.graph.nodes.pre_check_node import pre_check_node
from apps.mail_organizer.graph.state import MailOrganizerState
from core_platform.app.telemetry.audit_engine import AuditEngine


def _route_after_guardrail(state: MailOrganizerState) -> str:
    """Route after Layer 2 guardrail check."""
    if state.get("safety_override", False):
        # Sub-threshold confidence (< 0.85): bypass drafting and calendar
        return "action_planner"

    role = state.get("responsibility_role", "PRIMARY_ACTIONEE")
    cat = state.get("category", "")

    # Suppress drafting and task extraction for promotional emails or observer-only emails
    if cat == "@Promotions" or role == "OBSERVER_ONLY":
        return "action_planner"

    # Route meeting requests to calendar enrichment
    if state.get("is_scheduling_request", False) or cat == "@Meeting":
        return "calendar"

    return "draft"


class MailOrganizerWorkflow:
    """Production LangGraph workflow orchestrator for Mail & Calendar automation."""

    def __init__(
        self,
        db_service: Optional[MailDatabaseService] = None,
        gmail_connector: Optional[GmailConnector] = None,
        calendar_connector: Optional[GoogleCalendarConnector] = None,
        audit_engine: Optional[AuditEngine] = None,
        checkpointer: Optional[MemorySaver] = None,
    ) -> None:
        """Initialize and compile the LangGraph state machine."""
        self.db_service = db_service or MailDatabaseService()
        self.gmail_connector = gmail_connector or GmailConnector()
        self.calendar_connector = calendar_connector or GoogleCalendarConnector()
        self.audit_engine = audit_engine or AuditEngine.get_instance()
        self.checkpointer = checkpointer or MemorySaver()

        self.graph = self._build_graph()
        self.compiled_app = self.graph.compile(checkpointer=self.checkpointer)

    def _build_graph(self) -> Any:
        """Assemble StateGraph with discrete nodes and conditional branches."""
        workflow: Any = StateGraph(MailOrganizerState)

        # 1. Register discrete nodes
        async def _pre_check_step(s: MailOrganizerState) -> MailOrganizerState:
            db_vips = [r.pattern for r in self.db_service.get_rules(rule_type="vip")] if self.db_service else []
            custom_vips = list(s.get("vip_senders") or [])
            all_vips = list(set(db_vips + custom_vips))
            return await pre_check_node(s, vip_senders=all_vips)

        workflow.add_node("pre_check", _pre_check_step)
        workflow.add_node("ownership", ownership_node)
        workflow.add_node("classify", classify_node)
        workflow.add_node("guardrail", guardrail_node)
        async def _calendar_step(s: MailOrganizerState) -> MailOrganizerState:
            return await calendar_node(s, calendar_connector=self.calendar_connector)

        async def _execution_step(s: MailOrganizerState) -> MailOrganizerState:
            return await execution_node(
                s,
                db_service=self.db_service,
                gmail_connector=self.gmail_connector,
                audit_engine=self.audit_engine,
            )

        workflow.add_node("calendar", _calendar_step)
        workflow.add_node("draft", draft_node)
        workflow.add_node("pm_extract", pm_extract_node)
        workflow.add_node("action_planner", action_planner_node)
        workflow.add_node("execution", _execution_step)

        # 2. Wire edges
        workflow.set_entry_point("pre_check")
        workflow.add_edge("pre_check", "ownership")
        workflow.add_edge("ownership", "classify")
        workflow.add_edge("classify", "guardrail")

        # Layer 2 Guardrail conditional routing
        workflow.add_conditional_edges(
            "guardrail",
            _route_after_guardrail,
            {
                "calendar": "calendar",
                "draft": "draft",
                "action_planner": "action_planner",
            },
        )

        workflow.add_edge("calendar", "draft")
        workflow.add_edge("draft", "pm_extract")
        workflow.add_edge("pm_extract", "action_planner")
        workflow.add_edge("action_planner", "execution")
        workflow.add_edge("execution", END)

        return workflow

    async def execute(
        self,
        initial_state: MailOrganizerState,
        thread_id: Optional[str] = None,
    ) -> MailOrganizerState:
        """Execute the LangGraph workflow asynchronously with state tracking."""
        tid = thread_id or initial_state.get("thread_id", "THREAD-DEFAULT")
        config: Dict[str, Any] = {"configurable": {"thread_id": tid}}

        final_state = await self.compiled_app.ainvoke(initial_state, config=config)
        return cast(MailOrganizerState, final_state)

    def process_email(
        self,
        initial_state: MailOrganizerState,
        thread_id: Optional[str] = None,
    ) -> MailOrganizerState:
        """Execute the LangGraph workflow synchronously with state tracking."""
        tid = thread_id or initial_state.get("thread_id", "THREAD-DEFAULT")
        config: Dict[str, Any] = {"configurable": {"thread_id": tid}}

        final_state = self.compiled_app.invoke(initial_state, config=config)
        return cast(MailOrganizerState, final_state)
