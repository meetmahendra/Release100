# CORE ORCHESTRATOR & PLATFORM SERVICES SPECIFICATION
## The Universal Agentic Host & Gateway (`Release100`)

**Document ID:** `02_orchestrator_core`  
**Document Version:** `v1.1.0`  
**Date:** September 13, 2026  
**Status:** DRAFT / UNDER REVIEW  
**Target Subsystem:** `D:\Release100\core_platform`  
**Master Plan Reference:** `D:\Release100\plans\01_master_platform_architecture_v1.2.md`  

---

## Document Revision History & Changelog

| Version | Date | Author | Description of Changes | Status |
| :--- | :--- | :--- | :--- | :--- |
| **v1.0.0** | 2026-09-13 | AI Architecture Team | Initial Core Orchestrator Specification: Ingress normalization, Adaptive Auth/SSO, RBAC, Pluggable LLM Manager, Multi-Modal Semantic Router, 3-Layer Safety, Tri-Format Audit Engine, Native MCP Server Host, and Admin Shell. | Superseded |
| **v1.1.0** | 2026-09-13 | AI Architecture Team | **Incorporated User Feedback**: <br>1. **Domain-Agnostic Core**: Removed application-specific phrasing (e.g., "food safety audits") to keep the core orchestrator strictly generic and decoupled.<br>2. **Configurable Model Identifiers**: Eliminated hardcoded `gemini-2.5-flash` references; model names are now fully configurable via environment/config settings, defaulting to the latest Gemini Flash model. | **Current** |

---

## 1. Subsystem Mission & Scope

The **Core Orchestrator** is the foundational operating engine of `Release100`. It provides all common infrastructure, security, intelligence routing, and external connectivity as **Out-of-the-Box (OOTB) Platform Services**.

### Core Guarantees:
1. **Zero Boilerplate for Applications**: Domain applications contain strictly business logic and LangGraph state graphs. They never implement their own authentication, WhatsApp parsers, LLM wrappers, or MCP servers.
2. **Channel-Agnostic Core**: The orchestrator operates exclusively on a normalized **`InteractionEnvelope`**. It has zero hardcoded dependencies on WhatsApp or any single chat channel.
3. **Pluggable & Vendor-Agnostic**: LLM providers (Gemini, Claude, OpenAI, Local Ollama), Auth providers (Local User/Pass, Google/Microsoft SSO, API Keys), and storage backends are interchangeable via clean interfaces. Model names are dynamically configurable, defaulting to the latest high-efficiency models.
4. **Strict Safety & Compliance**: Implements the 3-layer deterministic safety guardrail engine and tri-format (JSON/CSV/HTML) regulatory compliance telemetry (supporting FDA 21 CFR Part 11, ISO standards, and SOC 2 audits) borrowed and elevated from `mailOrganizer`.

---

## 2. Ingress Normalization & Transport Adapters

```mermaid
graph TD
    subgraph "External Channel Ingress"
        WA_Webhook[Meta WhatsApp Webhook]
        Email_Stream[IMAP / Graph API Email Listener]
        Web_REST[Web Kiosk / Dashboard REST API]
        Pollers[Background Daemon Pollers & Crawlers]
        External_AI[Cursor / Claude via MCP SSE Endpoint]
    end

    subgraph "Transport Adapters (Ingress Layer)"
        WA_Adapter[WhatsApp Adapter: HMAC Verify + Media Downloader]
        Email_Adapter[Email Adapter: MIME & Thread Parser]
        Web_Adapter[FastAPI Route Controller]
        Poller_Adapter[Event Generator]
        MCP_Adapter[MCP Tool Request Parser]
    end

    subgraph "Canonical Normalization & Concurrency Engine"
        EnvelopeNormalizer[Canonical Envelope Builder]
        SessionManager[Per-User Concurrency Locks & De-duplication Cache]
    end

    WA_Webhook --> WA_Adapter
    Email_Stream --> Email_Adapter
    Web_REST --> Web_Adapter
    Pollers --> Poller_Adapter
    External_AI --> MCP_Adapter

    WA_Adapter & Email_Adapter & Web_Adapter & Poller_Adapter & MCP_Adapter --> EnvelopeNormalizer
    EnvelopeNormalizer --> SessionManager
    SessionManager --> CorePipeline[To Auth & Semantic Router]
```

### 2.1. The Canonical `InteractionEnvelope` (Universal Contract)

Regardless of where an event originates, the transport adapters convert the raw payload into a standard `InteractionEnvelope`:

```python
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class ChannelType(str, Enum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    WEB_KIOSK = "web_kiosk"
    MCP_AGENT = "mcp_agent"
    BACKGROUND_POLLER = "background_poller"

class MediaAttachment(BaseModel):
    media_id: Optional[str] = None
    media_type: str                  # "image/jpeg", "image/png", "application/pdf"
    raw_bytes: Optional[bytes] = None
    media_url: Optional[str] = None
    sha256_hash: Optional[str] = None

class InteractionEnvelope(BaseModel):
    envelope_id: str = Field(description="Unique UUID for distributed tracing")
    tenant_id: str = Field(default="default_tenant", description="Multi-tenant identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    channel: ChannelType
    sender_id: str = Field(description="Normalized sender ID (phone number, email, or API key ID)")
    
    # Payload content
    text_content: Optional[str] = None
    attachments: List[MediaAttachment] = []
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Channel-specific headers & tokens")
    
    # Concurrency key
    session_id: str = Field(description="Lock key: tenant:channel:sender_id")
```

### 2.2. WhatsApp Adapter Specifications
- **Webhook GET**: Responds to Meta `hub.challenge` using configured `WHATSAPP_VERIFY_TOKEN`.
- **Webhook POST**: Verifies cryptographic `X-Hub-Signature-256` header against `WHATSAPP_APP_SECRET` using `hmac.compare_digest` to prevent timing attacks.
- **Media Downloader**: When `message_type == "image"`, retrieves media URL from Meta Graph API (`GET /v20.0/{media_id}`) and downloads binary bytes directly into a `MediaAttachment` with calculated SHA-256 hash.
- **Deduplication**: In-memory LRU cache / Redis storing `message_id` for 30 minutes to drop duplicate Meta retry events.

---

## 3. Adaptive Identity, Authentication & RBAC Engine

```mermaid
graph TD
    InboundEnvelope[Inbound InteractionEnvelope] --> AuthResolver{Determine Auth Strategy}

    subgraph "Adaptive Auth Strategies"
        AuthResolver -->|Channel: WhatsApp / Kiosk| PhoneBiometric[Strategy A: Phone & Biometric Verification]
        AuthResolver -->|Channel: Web Admin / Email| EnterpriseSSO[Strategy B: OAuth2 / OIDC Google & Microsoft SSO]
        AuthResolver -->|Channel: Web Dashboard| LocalCredentials[Strategy C: Built-in Username/Password + JWT]
        AuthResolver -->|Channel: MCP / REST API| ScopedAPIKey[Strategy D: Scoped API Key Engine]
    end

    PhoneBiometric & EnterpriseSSO & LocalCredentials & ScopedAPIKey --> SecurityContext["SecurityContext
    ├── Principal ID
    ├── Tenant ID
    ├── User Roles: ['operator', 'admin', 'auditor']
    └── Permitted Apps: ['app_a', 'app_b']"]

    SecurityContext --> RBACFilter[RBAC Entitlement Pruning Filter]
```

### 3.1. RBAC Entitlement Pruning
Before invoking any LLM, the system dynamically calculates the candidate applications for the current user:

$$\text{Candidate Apps} = \text{Tenant.EnabledApps} \;\cap\; \text{Principal.PermittedApps}$$

* **Single App Match**: If the user is only permitted access to 1 app, the router bypasses LLM semantic classification and routes directly to that app’s workflow (**0 latency, 0 token cost**).
* **Zero App Match**: Returns immediate 403 Forbidden / Access Denied message without consuming LLM tokens.
* **Multiple App Match**: Advances to the Multi-Modal Semantic Router.

### 3.2. Scoped API Key Lifecycle
- External AI clients (Cursor, Claude Desktop) and external systems authenticate via HTTP Header `Authorization: Bearer ak_live_...`.
- Keys are hashed with SHA-256 at rest; raw keys are presented only once at creation.
- Keys specify explicit scopes (e.g., `['app_name:read', 'app_name:write']`, `max_requests_per_min: 60`).

---

## 4. Pluggable LLM Provider Gateway

The Orchestrator provides a unified, vendor-neutral LLM service (`BaseLLMProvider`) supporting both public cloud APIs and on-premise air-gapped local models:

```mermaid
graph LR
    OrchestratorCore[Orchestrator Core & Apps] --> LLMGateway[Unified LLM Gateway]
    
    LLMGateway --> GeminiDriver["Google Gemini (Configurable: Flash / Pro)"]
    LLMGateway --> ClaudeDriver[Anthropic Claude 3.5 / 3.7]
    LLMGateway --> OpenAIDriver[OpenAI GPT-4o / o3-mini]
    LLMGateway --> OllamaDriver[Local / On-Premise Ollama / vLLM / DeepSeek]
```

### Dynamic Task-Based Model Routing:
Model identifiers are **fully configurable** via environment variables or configuration files, defaulting to the latest high-efficiency Gemini Flash model:

```yaml
llm_routing:
  default_provider: "gemini"
  tasks:
    intent_routing:
      provider: "gemini"
      # Configurable: defaults to latest Gemini Flash model
      model: "${GEMINI_ROUTING_MODEL:gemini-flash-latest}"
    vision_processing:
      provider: "gemini"
      # Configurable: defaults to latest Gemini Flash model
      model: "${GEMINI_VISION_MODEL:gemini-flash-latest}"
    private_local_logs:
      provider: "local_ollama"
      model: "${LOCAL_LLM_MODEL:deepseek-r1:14b}"
```

Apps request models abstractly via the execution context: `ctx.get_llm(task="vision_processing")`.

---

## 5. Multi-Modal LLM Supervisor & Semantic Router

When an authenticated user has entitlement to multiple active applications, the **Semantic Router** evaluates the multi-modal payload (text, image, or document) using the **configured routing model** (defaulting to the latest Gemini Flash model) with structured JSON output:

```json
{
  "system_instruction": "You are the Executive Router for Release100. Evaluate the user payload against the candidate application descriptors and route to the correct application.",
  "candidate_applications": [
    {
      "app_id": "app_sample_a",
      "description": "Processes operational images, gauges, and duty logs."
    },
    {
      "app_id": "app_sample_b",
      "description": "Processes emails, inbox categorization, and meeting schedules."
    }
  ]
}
```

### Structured Routing Decision Schema:
```json
{
  "selected_app": "app_sample_a",
  "confidence": 0.98,
  "reasoning": "Image contains operational machinery and operator verification request.",
  "intent_category": "operational_duty_log",
  "requires_disambiguation": false
}
```

* **Disambiguation Loop**: If `confidence < 0.75`, the router generates an interactive quick-reply button prompt back to the user (WhatsApp buttons, Web modal, or API prompt) asking them to select the intended action.

---

## 6. 3-Layer Deterministic Safety & Confidence Guardrails

Borrowed and elevated from `mailOrganizer/app/pipeline/safety_rules.py`:

```mermaid
graph TD
    Input[Incoming Request / Extracted Values] --> Layer1{Layer 1: Deterministic Pre-Check}
    Layer1 -->|Violates Physical Sanity e.g. Out-of-bounds sensor values| RejectHard[Reject / Alert Instantly]
    Layer1 -->|Passes Sanity Check| Layer2[Layer 2: AI Semantic / Vision Reasoning]
    
    Layer2 --> Layer3{Layer 3: Confidence Guardrail}
    Layer3 -->|Confidence >= 85%| AutoPass[Pass to Operational Mode Engine]
    Layer3 -->|Confidence < 85%| DivertReview[Divert to 'Needs Human Review' / Retake Prompt]
```

1. **Layer 1: Deterministic Pre-Checks (Pre-AI)**:
   - Evaluates hard boundaries before invoking AI (e.g., sender whitelist, blacklist, physically out-of-bounds sensor values, corrupt payloads).
2. **Layer 2: AI Semantic & Vision Reasoning**:
   - Performs domain-specific inference, embedding matching, and multimodal extraction.
3. **Layer 3: Post-AI Confidence Guardrails**:
   - If confidence scores fall below threshold (`< 0.85`), the system **refuses to guess**. It diverts the transaction to `NEEDS_SUPERVISOR_REVIEW` or prompts the user for a clearer re-submission.

---

## 7. Operational Execution Modes

To ensure safe production rollouts in enterprise environments, the platform supports three execution modes:

```python
class ExecutionMode(str, Enum):
    SHADOW = "shadow"          # AI reasons & logs full audit trail, but performs ZERO real-world mutations
    ASSISTIVE = "assistive"    # AI prepares action; requires 1-click human supervisor approval before commit
    AUTONOMOUS = "autonomous"  # AI commits directly to downstream systems, DB, and notifications
```

- **Staging (Shadow Mode)**: Incoming events are fully reasoned and logged, but downstream mutations (ERP, external APIs) are suppressed. Allows QA and operations managers to verify model precision against ground truth before going live.
- **Transition (Assistive Mode)**: Results are queued for 1-click human sign-off.
- **Production (Autonomous Mode)**: Direct end-to-end synchronization.

---

## 8. Universal Compliance Audit & Telemetry Suite

Produces three synchronized outputs for every single interaction to satisfy regulatory compliance standards (FDA 21 CFR Part 11, ISO standards, SOC 2):

```
logs/audit_partitions/
├── 2026-09-13.jsonl      <-- High-performance streaming JSONL (Machine & SIEM ingest)
├── 2026-09-13.csv        <-- Flattened tabular CSV (Spreadsheet inspection)
└── html/
    └── 2026-09-13.html   <-- Self-contained visual HTML report with search & filter
```

### Digital Query API:
- `GET /api/v1/audit/records?start_date=2026-09-13&app=app_name&format=json`
- Implements SHA-256 cryptographic hashing of the original input payload to guarantee non-repudiation during compliance audits.

---

## 9. Native Model Context Protocol (MCP) Server Host

The Orchestrator exposes an SSE-based **Model Context Protocol (MCP) Server** on `/mcp/sse` and `/mcp/messages`.

```mermaid
graph LR
    Cursor[Cursor IDE / Claude Desktop] -->|SSE Connection with API Key| MCPEndpoint["Orchestrator MCP Host
    (/mcp/sse)"]
    
    MCPEndpoint --> DynamicAggregator[Dynamic Tool Aggregator]
    
    DynamicAggregator -.->|Collects Tools| AppA[App: Cartridge A]
    DynamicAggregator -.->|Collects Tools| AppB[App: Cartridge B]
    
    Cursor -->|tools/call| MCPEndpoint
    MCPEndpoint --> FullPipeline[Full Orchestrator Pipeline: Auth + Guardrails + LangGraph]
```

### Strict Encapsulation Guarantee:
External agents (Cursor, Claude) **never** bypass the orchestrator:
1. When Cursor invokes `tools/call`, the request is intercepted by the Orchestrator.
2. The Orchestrator validates the API key, checks rate limits, executes the application's complete LangGraph workflow, logs the compliance audit record, and returns only the verified result.
3. No direct database or internal application API is ever exposed to the external agent.

---

## 10. Dynamic Admin Shell & Stepper Wizard Host

The Orchestrator hosts a unified FastAPI web dashboard on `/admin/`:
- **Shell Features**: Authentication login page, dynamic navigation sidebar reflecting only enabled apps, system health metrics, and API key management.
- **Progressive Stepper Engine**: Provides an auto-save drafting engine for multi-step configuration wizards:
  - `POST /admin/drafts/save` (Auto-saves partial wizard state every 5 seconds or on field blur).
  - `GET /admin/drafts/resume` (Restores unfinished configurations if a user session disconnects).

---

## 11. Directory & Package Layout (`core_platform/`)

```text
D:\Release100\core_platform/
├── app/
│   ├── __init__.py
│   ├── config.py                      # Pydantic Settings (Configurable models, defaults)
│   ├── auth/                          # Identity & Authentication
│   │   ├── __init__.py
│   │   ├── strategies.py              # User/Pass, Google/MS SSO, Phone, API Key strategies
│   │   └── api_keys.py                # API Key generation, SHA-256 hashing, scope verification
│   ├── rbac/
│   │   ├── __init__.py
│   │   └── permissions.py             # Role definitions & candidate app pruning
│   ├── ingress/                       # Transport Normalization
│   │   ├── __init__.py
│   │   ├── envelope.py                # Canonical InteractionEnvelope definition
│   │   ├── whatsapp_adapter.py        # Meta Webhook, HMAC-SHA256, Graph media downloader
│   │   ├── email_adapter.py           # IMAP / Graph API email listener
│   │   ├── web_adapter.py             # REST / WebSocket endpoints
│   │   ├── poller_adapter.py          # Scheduled daemon pollers
│   │   └── session_manager.py         # Async per-user mutex locks & deduplication
│   ├── llm/                           # Pluggable LLM Gateway
│   │   ├── __init__.py
│   │   ├── base.py                    # BaseLLMProvider interface
│   │   ├── gemini_provider.py         # Google Gemini (Configurable Flash/Pro)
│   │   ├── claude_provider.py         # Anthropic Claude 3.5 / 3.7
│   │   ├── openai_provider.py         # OpenAI GPT-4o
│   │   └── ollama_provider.py         # Local on-premise Ollama / vLLM
│   ├── routing/                       # Multi-Modal Semantic Routing
│   │   ├── __init__.py
│   │   ├── semantic_router.py         # Configurable model intent classification
│   │   └── disambiguation.py          # Interactive clarification loops
│   ├── safety/                        # 3-Layer Deterministic Guardrails
│   │   ├── __init__.py
│   │   ├── pre_checks.py              # Layer 1: Deterministic sanity rules
│   │   └── confidence_guardrails.py   # Layer 3: Post-AI confidence thresholding
│   ├── telemetry/                     # Compliance Audit Suite (JSON, CSV, HTML)
│   │   ├── __init__.py
│   │   ├── audit_schema.py            # Strongly typed audit record schemas
│   │   ├── jsonl_writer.py            # High-performance async JSONL streaming
│   │   ├── csv_writer.py              # Flattened tabular CSV exporter
│   │   └── html_generator.py          # Partitioned visual HTML dashboards
│   ├── mcp_server/                    # Native SSE MCP Server Host
│   │   ├── __init__.py
│   │   ├── server.py                  # SSE MCP protocol server (:8001 / :8002)
│   │   └── tool_aggregator.py         # Dynamic tool registration from apps
│   ├── admin_shell/                   # Central Web Dashboard Shell
│   │   ├── __init__.py
│   │   ├── routes.py                  # /admin routes (auth, system, drafts)
│   │   ├── templates/                 # Jinja2 / Tailwind shell templates
│   │   └── static/                    # CSS, JS, branding assets
│   └── plugin_engine/                 # Dynamic Application Lifecycle Manager
│       ├── __init__.py
│       ├── base_plugin.py             # BaseApplication interface definition
│       └── loader.py                  # Dynamic module importer & router mounting
├── main.py                            # Clean platform bootstrap (< 60 lines)
└── requirements.txt                   # Platform core dependencies
```

---

## 12. Next Steps

With **Plan 2 updated to `v1.1.0`**, all domain leaks have been removed and model identifiers are fully configurable (defaulting to the latest Gemini Flash model).

We are now ready to proceed to **Plan 3: Food Temperature & Attendance Marker Application Specification** (`03_app_temperature_marker_v1.0.md`).
