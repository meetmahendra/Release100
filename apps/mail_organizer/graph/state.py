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
MailOrganizerState Strongly-Typed State Definition.

Adheres strictly to Plan 04 v1.0 Section 4 and GEES v1.0.
Carried through every node in the LangGraph state machine.
"""

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class MailOrganizerState(TypedDict, total=False):
    """Normalized state schema flowing through the LangGraph triage workflow."""

    # Raw Email Input
    gmail_id: str
    thread_id: str
    subject: str
    sender: str
    body: str
    snippet: str
    to_recipients: List[str]
    cc_recipients: List[str]
    auto_reply_headers: Dict[str, str]

    # Layer 0: Deterministic Pre-Check Flags
    is_vip: bool
    is_no_reply: bool
    is_auto_reply: bool
    has_critical_subject: bool

    # Layer 1: Stochastic Reasoning Outputs
    category: str                      # "@Action", "@Urgent", "@Meeting", "@WaitingOn", "@Promotions", etc.
    urgency_score: int                 # 1 (lowest) to 10 (critical)
    confidence_score: float            # 0.0 to 1.0
    reasoning: str
    context_tags: List[str]            # e.g., ["chiller", "maintenance", "vendor"]
    is_reply_necessary: bool

    # Layer 2: Safety Guardrail Status
    safety_override: bool
    override_reason: Optional[str]

    # Calendar Context
    is_scheduling_request: bool
    calendar_availability: Optional[str]

    # Ownership & Delegation
    responsibility_role: str           # "PRIMARY_ACTIONEE" | "OBSERVER_ONLY" | "DELEGATOR"
    delegation_target: Optional[str]

    # Draft Generation & PM Tasks
    suggested_reply: Optional[str]
    pending_pm_tasks: List[Dict[str, Any]]
    gmail_actions: List[Dict[str, Any]] # e.g. [{"action": "apply_label", "label": "@Urgent"}]

    # Execution & Telemetry
    execution_mode: str                # "shadow" | "assistive" | "autonomous"
    actions_taken: List[Dict[str, Any]]
    error_message: Optional[str]
    pipeline_trace: List[Dict[str, Any]]
    correlation_id: str
    audit_record_hash: Optional[str]
    vip_senders: List[str]

    # Tenant & User Identity Context
    tenant_id: Optional[str]
    cartridge_id: Optional[str]
    user_id: Optional[int]
    user_name: Optional[str]
    user_email: Optional[str]

    # [CODE-MARKER: MO-STATE-01] v1.3.0 Neuro-Symbolic & Multi-Head Triage State
    priority_lane: str                 # "HIGH" (Interactive) | "LOW" (Background Poller)
    rfc_headers: Dict[str, str]
    has_list_unsubscribe: bool
    attachments_present: List[str]

    # Contact & Identity Resolution (REV-03)
    resolved_contact_id: Optional[int]
    contact_resolution_layer: str
    contact_resolution_status: str
    learned_salutations: List[str]
    salutation_extracted: str

    # Dynamic Vocative Ownership & Speech-Act (REV-02 & REV-05)
    header_recipient_role: str         # "PRIMARY_ACTIONEE" | "CO_ACTIONEE" | "OBSERVER_CC" | "MAILING_LIST"
    was_promoted_from_cc: bool
    speech_act: str                    # "REQUEST" | "COMMIT" | "PROPOSE" | "INFORM" | "DECLINE"
    extracted_commitments: List[Dict[str, Any]]
    extracted_entity_facts: List[Dict[str, Any]]

    # Tier 2 Hybrid Context, Missing Reference Gate & Grounded Synthesis (REV-01, REV-12, REV-13)
    hybrid_context_bundle: Dict[str, Any]
    missing_artifact_detected: bool
    missing_artifact_type: Optional[str]
    missing_artifact_description: Optional[str]
    self_critique_passed: bool
    self_critique_notes: Optional[str]
    citation_ids: List[str]
    infographic_card_spec: Optional[Dict[str, Any]]

