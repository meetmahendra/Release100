# ARCHITECTURAL DECISION RECORD (ADR)
## ISSUE-003: LangGraph Agentic Workflow Modernization & GEES Standard Alignment

```
Issue ID       : ISSUE-003
Title          : Evaluation of Modern Multi-Agent LangGraph Workflows for Conversational Ingress and Dispatch
Severity       : Architectural Exploration / Enhancement
Component      : core_platform/app/ingress/, apps/temperature_marker/graph/
Status         : OPEN / BACKLOGGED (Pending GEES Standard Review)
Author         : Mahendra GURAV / Antigravity AI Pair
Date           : September 19, 2026
Standard Ref   : GEES v1.0 Standard, Axiom 1 (Determinism Surrounds Stochasticity)
```

---

## 1. Context & Objective

In our current implementation:
- The core ingress routing, rate limiting, session management, and operator-to-manager dispatch rely on deterministic Python state machines.
- Stochastic LLM reasoning (Gemini Vision) is encased strictly in dedicated leaf skills (`DisplayOCRSkill`, `classify_node`).

The question raised is: **Can we modernize the entire conversational ingress and triage lifecycle into an end-to-end LangGraph agentic workflow?**

---

## 2. Proposed Modern LangGraph Architecture

Instead of procedural routing in `whatsapp_router.py`, the system can be modeled as a declarative, multi-agent **StateGraph**:

```
                              [INBOUND WHATSAPP EVENT]
                                         │
                                         ▼
                            ┌────────────────────────┐
                            │ IngressRouterNode      │ (LangGraph Node)
                            └───────────┬────────────┘
                                        │ (Conditional Edge via Intent Classifier)
                ┌───────────────────────┼───────────────────────┐
                ▼                       ▼                       ▼
      ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
      │ AttendanceGraph  │    │ DispatchGraph    │    │ ManagerTriage    │
      │ • FaceMatchNode  │    │ • QueueMsgNode   │    │ • PrioritizeNode │
      │ • WatermarkNode  │    │ • MetaTemplate   │    │ • ReplyRelayNode │
      │ • HACCPNode      │    │   BypassNode     │    │ • ActiveSession  │
      └──────────────────┘    └──────────────────┘    └──────────────────┘
```

### Benefits of the Modern LangGraph Approach:
1. **Unified Graph Paradigm:** Both `temperature_marker` and `mail_organizer` already use LangGraph for domain processing; bringing ingress into LangGraph creates a single, unified architectural abstraction across the entire platform.
2. **State Persistence & Checkpointing:** Native LangGraph checkpointers (`MemorySaver` or `SqliteSaver`) allow long-running multi-turn manager triage sessions to persist across server restarts.
3. **Adaptive Agentic Reasoning:** Capable of handling complex conversational disambiguation, multi-step clarifications, and contextual supervisor delegation without sprawling `if/else` ladders.

---

## 3. Items for GEES Standard Review

To maintain compliance with the **Global Engineering Excellence Standard (GEES v1.0)**, the user will review:
1. **Axiom 1 Alignment:** Ensuring deterministic safety boundaries (geofencing, physical boundaries, auth whitelists) remain non-stochastic pre-execution guards within the graph.
2. **Layer 2 Post-Execution Gates:** Ensuring any agentic decision routes through deterministic validation before mutating production queues or sending outbound WhatsApp messages.
3. **Latency & Token Efficiency:** Ensuring fast-path operations (e.g. status receipts, duplicate checks) do not incur unnecessary LLM round-trips.

---

## 4. Status & Next Steps
- Documented in backlog as **`ISSUE-003`**.
- Awaiting user review of GEES directives before initiating graph refactoring.
