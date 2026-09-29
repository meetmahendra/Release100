# ARCHITECTURAL DECISION RECORD (ADR)
## ISSUE-004: Human-Like Conversational Experience via Multi-Turn History & LLM Orchestration

```
Issue ID       : ISSUE-004
Title          : Human-Like Conversational Ingress via Multi-Turn History & LLM Orchestration
Severity       : Medium (Architectural Modernization & UX Enhancement)
Component      : core_platform/app/ingress/whatsapp_router.py, core_platform/app/llm/, apps/temperature_marker/
Status         : PROPOSED / BACKLOGGED (To Be Resolved Later)
Author         : Mahendra GURAV / Antigravity AI Pair
Date           : September 20, 2026
Standard Ref   : GEES v1.0 Standard, Pillar 1 (Multi-Layered Safety Architecture) & Pillar 5 (Universal Skills)
```

---

## 1. Context & Motivation

In current field trials of the **CaneBot Platform** (`Release100`), interactions with kiosk operators and fleet supervisors through WhatsApp are functional but structurally rigid. 

When operators text the bot:
- Text is processed through procedural, rule-based if/elif keyword matching (`cmd_lower in [...]`, `cmd_lower.startswith(...)`).
- Replies consist of static, pre-templated cards and fixed emojis.
- The interaction lacks true natural language understanding, conversational continuity, and empathy.
- When an operator asks a context-dependent question (e.g. *"I am reaching in 5 mins, should I take the photo now?"* or *"Chiller was serviced yesterday, is 4.5 fine?"*), procedural keyword matching either defaults to attendance error cards or misroutes the intent.

To deliver an exceptional user experience, conversations with operators and managers should feel like communicating with a **helpful, intelligent human fleet coordinator**. This requires integrating an LLM reasoning engine equipped with **multi-turn conversation history** and **live kiosk state context**.

---

## 2. Current Technical Limitations (Hardcoding Analysis)

1. **Stateless Conversational Turns:**
   - Every inbound WhatsApp webhook event is evaluated in isolation without conversational memory of preceding turns.
   - If a manager asks *"Who is at Kiosk 4?"* followed by *"Call him"*, the system cannot resolve pronouns or prior context.
2. **Heuristic & Keyword Brittleness:**
   - Commands require exact phrases (`attendance`, `kiosk`, `hi`, `help`, `register`).
   - Slight colloquialisms, dialect variations (e.g. Marathi/Hindi/English code-switching common in Pune kiosks), or natural questions fall through to fallback templates.
3. **Rigid Output Formatting:**
   - Template strings (e.g. `✅ Shift Attendance: RECORDED at...`) are hardcoded in `whatsapp_router.py`. While compliant, they feel robotic rather than conversational.

---

## 3. Proposed Architecture & Target Design

```
                     ┌──────────────────────────────────────────────┐
                     │ Inbound WhatsApp Event (Text / Media / Voice)│
                     └──────────────────────┬───────────────────────┘
                                            │
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │ Layer 0 Deterministic Pre-Execution Gate     │
                     │  - Rate Limiting (TokenBucket)               │
                     │  - VIP / Sender Whitelist Verification       │
                     │  - Emergency / Hazard Keyword Intercept      │
                     └──────────────────────┬───────────────────────┘
                                            │
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │ Multi-Turn Session Memory (SQLite / Cache)   │
                     │  - Retrieve last N dialogue turns            │
                     │  - Fetch real-time employee & station state  │
                     └──────────────────────┬───────────────────────┘
                                            │
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │ Layer 1 Stochastic Conversational Agent      │
                     │  - Model: Gemini 2.5 Flash via LLM Gateway   │
                     │  - Grounded System Prompt + Station Context   │
                     │  - Structured Function Calling (Tool Gate)   │
                     └──────────────────────┬───────────────────────┘
                                            │
                       ┌────────────────────┴────────────────────┐
                       ▼                                         ▼
            [Tool Invocations]                        [Natural Conversational Reply]
          - verify_location()                           - Context-aware dialogue
          - log_periodic_temp()                         - Empathetic guidance
          - escalate_to_supervisor()                    - Human-like tone
          - answer_kiosk_faq()
                       │                                         │
                       └────────────────────┬────────────────────┘
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │ Layer 2 Deterministic Post-Execution Gate    │
                     │  - Verify Tool Permissions & RBAC            │
                     │  - Check Confidence Threshold (>= 85%)       │
                     │  - Audit Trail Hashing (SHA-256 Chaining)    │
                     └──────────────────────┬───────────────────────┘
                                            │
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │ WhatsApp Cloud API Outbound Response         │
                     └──────────────────────────────────────────────┘
```

### 3.1 Multi-Turn Conversation Memory Store
- Create `ConversationMemoryService` tracking dialog history per user phone:
  - Rolling window of the last $N$ turns (e.g. $N = 10$).
  - Schema: `(id, phone_number, sender_role, message_role, content, media_meta, timestamp_utc)`.
  - Persisted in SQLite `conversation_history` table for persistence across restarts.

### 3.2 Real-Time Grounding Context
Before invoking the model, construct a dynamic contextual injection:
- **Operator Profile:** Name, employee code, assigned kiosk, reporting supervisor.
- **Duty Status:** Today's check-in status (marked at $T$ / pending), GPS geofence state.
- **HACCP Status:** Latest chiller temperature, safe range $[2.0^\circ\text{C}, 4.0^\circ\text{C}]$, compliance state.
- **Pending Tasks:** Open manager notes, unread instructions.

### 3.3 Strict Tool Calling under GEES v1.0
To prevent hallucinations and preserve audit integrity, the LLM cannot directly modify database state. It must call deterministic tools:
- `Tool: record_checkin_intent(location_verified: bool)`
- `Tool: prompt_location_verification(session_url: str)`
- `Tool: submit_maintenance_ticket(category: str, description: str, urgency: str)`
- `Tool: query_kiosk_directory()`
- `Tool: format_manager_triage_digest()`

### 3.4 Empathetic Human-Like Persona
- Tone: Professional, courteous, encouraging, and clear.
- Support multilingual understanding (English, Hindi, Marathi colloquial terms).
- Retains safety discipline: Never compromises on biometric verification or HACCP compliance boundaries while conversing naturally.

---

## 4. Implementation Roadmap (Deferred Scope)

| Phase | Milestone | Deliverable | Priority |
|:---|:---|:---|:---:|
| **Phase 1** | Conversation History Table & Memory Service | SQLite migration + `ConversationMemoryService` | Medium |
| **Phase 2** | LLM Gateway Conversational Prompt & Tools | Pydantic schemas for WhatsApp agent tools | High |
| **Phase 3** | Ingress Router Replacement | Transition `whatsapp_router.py` from if-blocks to Agent Workflow | High |
| **Phase 4** | Multilingual & Edge Case Evaluation | Synthetic conversational evaluation suite in `tests/` | Medium |

---

## 5. Next Steps
When scheduling the conversational overhaul, reference this document:  
[`issues/ISSUE-004_conversational_llm_and_multi_turn_history.md`](file:///D:/Release100/issues/ISSUE-004_conversational_llm_and_multi_turn_history.md).
