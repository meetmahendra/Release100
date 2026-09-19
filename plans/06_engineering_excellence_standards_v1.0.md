# Global Engineering Excellence Standard (GEES) v1.0
## Architectural, Safety, Verification, and Operational Framework for Mission-Critical & Agentic Software Systems

```
Document Reference : EES-STD-2026-V1.0
Status             : Approved Organizational & Open-Source Standard
Author             : Mahendra GURAV
License            : Apache License, Version 2.0
Scope              : Universal (All Core Platforms, Domain Cartridges, Kiosk Systems & AI Agents)
```

---

## 1. Executive Mandate & Philosophical Foundation

The rapid rise of stochastic artificial intelligence, agentic state machines, and edge-connected IoT devices introduces immense transformative capability alongside severe risks: silent hallucinations, cascading failure loops, data tampering, credential leakage, and non-deterministic application states.

**Toy prototypes and hackathon scripts are strictly prohibited from entering production.** 

The **Global Engineering Excellence Standard (GEES)** codifies the mandatory architectural, safety, testing, security, and governance requirements that must govern any software system built within our organization and across our open-source initiatives. 

### The Five Inviolable Axioms
1. **Determinism Surrounds Stochasticity:** Probabilistic AI models must always be encased in deterministic pre-execution guardrails and deterministic post-execution validators. No model output is ever trusted blindly.
2. **Hard Safety is Non-Negotiable:** A single safety breach (such as an unauthorized financial transaction, infinite email reply loop, or temperature falsification) represents total failure. The safety pass threshold for release is **100.0%**.
3. **Non-Repudiation by Default:** Every critical transaction, decision, and sensor capture must be permanently logged in immutable, cryptographically verifiable audit trails conforming to international regulatory standards (e.g., FDA 21 CFR Part 11, ISO 22000, SOC 2).
4. **Zero-Trust Credential Isolation:** No secret, token, key, or unencrypted credential may ever touch version control or persist in plain text at rest.
5. **Living Documentation & Empirical Benchmarks:** If an architectural decision is not documented, it does not exist. If a feature is not verified against a high-fidelity benchmark suite, it is considered broken.

---

## 2. Pillar 1: Multi-Layered Safety Architecture & Fail-Safe Defaults

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       INCOMING INPUT / USER EVENT                       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 0: Deterministic Pre-Execution Gate                               │
│ • Deterministic VIP / Safe Sender & Blacklist filtering                 │
│ • Hard sanitization (HTML/JS stripping, prompt injection defense)       │
│ • Sensor sanity bounding (e.g. Reject physically impossible values)     │
│ • Hardware & Geofence Verification (Haversine threshold check)          │
│ • Tamper detection & rate limiting                                     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Pass)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: Stochastic Model / Agent Reasoning Engine                      │
│ • Schema-enforced outputs (Pydantic / Structured JSON mode)             │
│ • Grounded context only (Anti-stalling & Anti-hallucination rules)       │
│ • Temperature clamps (Deterministic tasks: 0.0 – 0.2)                   │
│ • Strict model-agnostic abstraction (Configurable LLM provider)         │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: Deterministic Post-Execution Boundary & Quality Gate           │
│ • Confidence scoring guardrails (Confidence < 85% ➔ Human Review Gate)  │
│ • Schema & type validation (Pydantic parsing)                           │
│ • Action authorization check (Verify against RBAC entitlements)         │
│ • Zero-destructive command filter (Intercept deletions / mutations)    │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Pass)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       DOWNSTREAM EXECUTION / STORAGE                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Layer 0: Deterministic Pre-Execution Gate
- **Pre-Model Overrides:** Hard logic rules written in pure, auditable code must execute *before* calling any AI service or model.
  - *Example (Mail System):* Safe sender VIP checks and automated sender (`no-reply`, auto-responders) detection must run deterministically. VIP emails are unconditionally marked high priority; automated notifications are barred from triggering automated replies.
  - *Example (Sensor/Kiosk System):* Raw OCR readings or temperature values outside physical reality (e.g., negative temperatures on ambient lines, or readings exceeding 150°C) must be intercepted immediately before database commit or display.
- **Input Sanitization:** Reject or neutralize potential prompt injections, malicious payloads, script tags, and malformed binary headers before stochastic processing.
- **Physical Verification:** Physical parameters (e.g., GPS coordinates via Haversine distance calculations) must be validated against kiosks or facility geofences prior to authorizing actions.

### 2.2 Layer 1: Stochastic Model Reasoning & Constraints
- **Structured Contracts Only:** Free-form raw text parsing from LLMs is prohibited. All model inferences must return strictly typed schemas (Pydantic models, JSON Schema enforcement).
- **Grounding & Anti-Hallucination:** Models must be provided explicit context and strictly instructed not to extrapolate facts. In draft generation, models must adhere to anti-stalling guardrails (e.g., no vague "we will look into it" replies when factual context is missing; require explicit missing information requests).
- **Temperature Governance:** Deterministic classification, OCR parsing, and factual triage must use temperatures between `0.0` and `0.2`. Creative or conversational tasks must not exceed `0.7`.

### 2.3 Layer 2: Deterministic Post-Execution Gate
- **Confidence Clamping:** All model-generated decisions must carry an explicit confidence metric. If confidence drops below **85%** (or an application-defined critical threshold), the system must automatically divert the payload to an escalation queue (`Needs Review` / Admin Approval Gate) and prevent autonomous action.
- **Destructive Command Interception:** Destructive mutations (e.g., deleting emails, purging records, truncating databases, or altering baseline safety parameters) are strictly prohibited from autonomous model execution.
- **Fail-Safe Defaults (Shadow Mode):**
  - All deployments must boot with Dry-Run / Shadow Mode capability (`DRY_RUN=True`). In this mode, mutations are simulated and logged to the audit log without affecting production upstream systems.
  - Zero-Deletion Policy: Implement soft-deletions, state archiving (e.g., moving to an archive label/folder), and append-only ledgers instead of destructive drops.

---

## 3. Pillar 2: Dual-Engine Verification Framework

Quality is guaranteed through an integrated, dual-engine testing regime. Passing unit tests alone is wholly insufficient for agentic, mission-critical systems.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   DUAL-ENGINE VERIFICATION REGIME                       │
├────────────────────────────────────┬────────────────────────────────────┤
│ ENGINE A: Fast Synthetic Suite     │ ENGINE B: Live Benchmark Suite     │
│ (`pytest`, Unit & Mock Tests)      │ (`run_live_benchmark.py`)          │
├────────────────────────────────────┼────────────────────────────────────┤
│ • Speed: Sub-minute execution      │ • Speed: Exhaustive evaluation     │
│ • Scope: Code coverage, syntax,    │ • Scope: End-to-end scenarios,     │
│   isolated logic, type invariants  │   LLM behavior, edge cases         │
│ • Mocking: 100% mocked external    │ • Modes: Hybrid (Mock Fixtures &   │
│   services, APIs, and networks     │   Live Services / Real Models)     │
│ • Gate Threshold: 80%+ Code Cov    │ • Gate: 100% Safety / >=80% Pass   │
└────────────────────────────────────┴────────────────────────────────────┘
```

### 3.1 Engine A: Fast Synthetic Unit & Integration Suite
- **Execution Environment:** Executed via `pytest` with zero external network dependencies.
- **Code Coverage Minimum:** Minimum **80% line and branch coverage** across all core modules, business rules, and cognitive skill classes.
- **Mocking Boundaries:** All network calls, database connections, and LLM endpoints must have clean unit mock fixtures.
- **Static Gate:** Must pass before any pull request is merged:
  ```bash
  pytest --cov=app --cov-fail-under=80 -v
  ruff check .
  mypy --strict .
  ```

### 3.2 Engine B: High-Fidelity Live Benchmark Suite
- **Purpose:** Rigorously validate system performance across authentic, real-world domain scenarios, stress-testing safety, ownership accuracy, and domain compliance.
- **Benchmark Catalog (`benchmark_catalog.json`):**
  - Must contain a curated, versioned corpus of realistic scenarios covering standard cases, multi-party delegations, adversarial inputs, edge anomalies, and regulatory violations.
  - Each scenario defines:
    - Input payload (headers, message bodies, images, OCR frames, metadata).
    - Expected outcomes (intent classification, extracted fields, priority).
    - Inviolable safety criteria (e.g. `safety_must_not_reply`, `safety_must_flag_anomaly`, `safety_retain_inbox`).
- **Standard Benchmark Runner Interface (`run_live_benchmark.py`):**
  Every project must provide a root-level benchmark runner with standardized CLI flags:
  ```bash
  # Execute full benchmark suite
  python run_live_benchmark.py

  # Filter by specific domain suite
  python run_live_benchmark.py --domain=cold_chain_haccp

  # Limit scenarios for quick smoke test
  python run_live_benchmark.py --limit=10

  # Clean old reports prior to run
  python run_live_benchmark.py --clean

  # Run against real LLM / live local mock RAG service
  python run_live_benchmark.py --mode=live

  # Enforce CI/CD Quality Gate (Exits with non-zero code on failure)
  python run_live_benchmark.py --quality-gate
  ```

### 3.3 The Hard Safety Quality Gate Thresholds
When invoked with `--quality-gate`, the test runner must enforce the following non-negotiable thresholds:

| Metric | Required Threshold | Consequence of Failure |
| :--- | :--- | :--- |
| **Hard Safety Compliance** | **100.0%** (Zero Tolerance) | **IMMEDIATE BUILD ABORT** (Exit Code 1) |
| **Overall Pass Rate** | **>= 80.0%** | **BUILD ABORT** (Exit Code 1) |
| **Average Benchmark Score** | **>= 80.0 / 100** | **BUILD ABORT** (Exit Code 1) |
| **Draft / Field Accuracy** | **>= 80.0%** | Warning / Gated |

### 3.4 Automated Multi-Format Reporting
Every benchmark execution must automatically output dual artifacts to the `reports/` directory:
1. **Interactive HTML Dashboard (`reports/live_benchmark.html`):** Modern, visually polished dashboard containing:
   - Metric summary cards (Total cases, Overall pass rate, Safety score, Latency).
   - Domain-level performance breakdown bar charts.
   - Expandable, detailed scenario inspection cards with color-coded badges (`PASS` in emerald, `FAIL` in crimson, `SAFETY VIOLATION` in amber).
2. **Machine-Readable JSON Summary (`reports/live_benchmark.json`):** Complete execution payload containing timestamps, model parameters, scores, and execution durations for CI/CD ingestion and historical tracking.

---

## 4. Pillar 3: Regulatory Compliance, Auditing & Deep Telemetry

Industrial, food safety, healthcare, and enterprise automation applications must withstand stringent regulatory audits (e.g., FDA 21 CFR Part 11, ISO 22000, HACCP, GDPR, SOC 2 Type II).

### 4.1 Tri-Format Audit Logging
Every critical action, sensor read, classification, and override must be contemporaneously recorded in three synchronized formats:

```
                          ┌───────────────────────────┐
                          │   AUDIT LOGGING ENGINE    │
                          └─────────────┬─────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           ▼                            ▼                            ▼
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  audit_log.jsonl     │     │   audit_log.csv      │     │  audit_report.html   │
├──────────────────────┤     ├──────────────────────┤     ├──────────────────────┤
│ Machine-readable     │     │ Human-accessible     │     │ Visual inspection    │
│ streaming format for │     │ operational format   │     │ dashboard for plant  │
│ SIEM, Elasticsearch, │     │ for floor managers,  │     │ managers, QA leads,  │
│ & cloud ingestion    │     │ Excel, & field QA    │     │ & regulatory audits  │
└──────────────────────┘     └──────────────────────┘     └──────────────────────┘
```

1. **Streaming JSON Lines (`audit_log.jsonl`):** Append-only, newline-delimited JSON for high-throughput automated analysis, SIEM tools, and log aggregators.
2. **Tabular CSV (`audit_log.csv`):** Standard CSV format for operations staff, supervisors, and non-technical auditors to inspect in spreadsheets without developer tooling.
3. **Self-Contained HTML Report (`audit_report.html`):** Formatted visual audit report with filtering, color-coded status badges, and aggregate compliance metrics.

### 4.2 Cryptographic Non-Repudiation (SHA-256 Hash Chaining)
To prevent tampering or retrospective alteration of audit trails:
- Every audit entry must calculate a cryptographic hash:
  $$\text{Record Hash} = \text{SHA-256}(\text{Previous Hash} + \text{Timestamp} + \text{Payload JSON})$$
- The genesis entry uses a predetermined seed hash (`GENESIS_BLOCK_0000000000000000`).
- Any modification, deletion, or insertion in historical log files invalidates the subsequent hash chain, immediately exposing tampering.

### 4.3 Mandatory Audit Payload Schema
Every audit entry must contain the following standard fields:
```json
{
  "event_id": "c61b2a9d-1b3c-44e2-a0d3-3df84f22709e",
  "timestamp_utc": "2026-09-14T02:30:00.123456Z",
  "organization_id": "CANECTAR_FOODS",
  "facility_id": "UNIT_01_MUMBAI",
  "operator_id": "EMP_1042",
  "action_type": "TEMPERATURE_LOG_COMMIT",
  "layer_0_status": "PASSED",
  "layer_1_model": "gemini-2.5-flash",
  "layer_1_confidence": 0.985,
  "layer_2_gate_status": "APPROVED",
  "payload_summary": {
    "chiller_temp_c": 3.2,
    "target_range_c": [2.0, 4.0],
    "haccp_compliant": true,
    "gps_verified": true,
    "gps_distance_meters": 18.4
  },
  "prev_hash": "a8f5b49...e210",
  "record_hash": "e3b0c44...8921"
}
```

---

## 5. Pillar 4: Zero-Trust Security & Cryptographic Isolation

### 5.1 Credential & Secret Isolation
- **Absolute Version Control Ban:** Secrets, API keys, private tokens, OAuth client configurations, and local database files must never be committed to Git.
- **Mandatory `.gitignore` Entries:**
  ```gitignore
  # Secrets and Environment Variables
  .env
  .env.*
  *.pem
  *.key
  credentials.json
  token.json
  client_secrets.json

  # Local Databases and Stateful Caches
  *.db
  *.sqlite
  *.sqlite3

  # Test Artifacts and Temporary Reports
  reports/*.html
  reports/*.json
  .pytest_cache/
  __pycache__/
  ```
- **Tiered Credential Management:**
  - *Local Development:* Local `.env` loaded via strictly typed `pydantic-settings`.
  - *Edge / Desktop Deployments:* OS-level credential managers (Windows Credential Manager / DPAPI, Linux Secret Service).
  - *Production Server Deployments:* Cloud Key Management Service (AWS KMS, Google Cloud KMS, or HashiCorp Vault).

### 5.2 Encryption at Rest & In Transit
- **Data at Rest:** All sensitive personal data (biometrics, face embeddings, employee PII) and authentication tokens stored locally must be encrypted using **AES-256-GCM** with authenticated 128-bit authentication tags.
- **Data in Transit:**
  - All HTTP endpoints must enforce **TLS 1.3** (or minimum TLS 1.2 with strict cipher suites).
  - WebSocket connections must enforce `wss://`.
  - Edge-to-Cloud communication must route over authenticated reverse tunnels or edge relays (e.g., Cloudflare Workers with Durable Objects) to prevent opening inbound ports on factory/retail firewalls.
- **CORS Configuration:**
  - Wildcard origins (`allow_origins=["*"]`) are strictly restricted to local development environments.
  - Production deployments must strictly whitelist authorized domain names with explicit method and header restrictions.

---

## 6. Pillar 5: Code Hygiene, Architecture & Typing Discipline

### 6.1 Strict Type Completeness
- **100% Type Annotations:** Every function signature, method parameter, and return value must include comprehensive Python type annotations.
- **Pydantic Data Contracts:** All internal domain payloads, API request bodies, and database transfer objects (DTOs) must be defined as Pydantic (`BaseModel`) models with explicit validation constraints.
- **Type Checking Enforcement:** Zero errors under `mypy --strict` or `pyright`.

### 6.2 Architectural Decoupling: Core Platform vs. Domain Cartridges
To ensure infinite scalability across multiple applications:
- **Clean Separation of Concerns:**
  - `core_platform/`: Contains the host orchestrator, process supervisor, interaction envelope, authentication, safety gates, audit engine, and cognitive skills library. **Contains zero hardcoded business logic or domain names.**
  - `apps/`: Ultra-lean domain cartridges (e.g., `temperature_marker`, `mail_organizer`, `project_manager`) containing domain business rules and workflows.
- **Universal Cognitive Skills Pattern:**
  - Reusable computer vision, OCR, geofencing, and NLP capabilities are promoted to `core_platform/app/skills/`.
  - Skills are stateless, modular, and single-purpose. Domain cartridges access them via dependency injection (`ctx.get_skill("display_ocr")`).
- **Pluggable Downstream Gateways:**
  - Cartridges must decouple their business outcomes from external persistence.
  - Implement a pluggable gateway pattern supporting REST APIs, Direct SQL databases, Cloud Spreadsheets (Google Sheets/Excel Online), and ERP/MCP connectors via runtime configuration.

### 6.3 Standardized Code Style & Documentation
- **PEP 8 Compliance:** All code formatted via `black` (88-char line length) and linted via `ruff`.
- **Google-Style Docstrings:** Every module, class, and public function must feature comprehensive docstrings detailing Args, Returns, and Raises.
- **Defensive Error Handling:**
  - Bare `except:` clauses are prohibited.
  - Catch explicit exception classes, log contextual debugging details, and re-raise with causal chaining (`raise DomainException("...") from err`).

---

## 7. Pillar 6: Intellectual Property, Licensing & Authorship

### 7.1 Licensing Discipline
- All open-source and shared organizational components must be licensed under the **Apache License, Version 2.0**.
- Every single source file (`.py`, `.ts`, `.js`, `.sh`, `.ps1`) must include the standardized Apache 2.0 copyright header.

### 7.2 Standard Mandatory Header
```python
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
```

### 7.3 Dependency Licensing & Supply Chain Hygiene
- All third-party libraries must be scanned for license compatibility.
- Viral copyleft licenses (e.g., GPL v3, AGPL) must not be linked into proprietary commercial builds unless explicitly authorized.
- Automated dependency vulnerability audits (`pip-audit` or `safety`) must run in CI/CD pipelines to prevent supply-chain vulnerabilities.

---

## 8. Pillar 7: Living Documentation & Operational Runbooks

A codebase without documentation is technical debt from day zero. Every project following this standard must maintain the following living documentation hierarchy:

```
<project_root>/
├── README.md                 # Project Overview, 5-minute Quickstart, Benchmark Execution
├── LICENSE                   # Complete Apache 2.0 License Text
├── docs/
│   ├── ARCHITECTURE.md       # High-level architecture, Layer diagrams, Dataflow, Skills
│   ├── SECURITY.md           # Threat models, Credential handling, Safety guardrails, Disclosure
│   ├── CONTRIBUTING.md       # Developer setup, Code style, PR guidelines, Testing commands
│   ├── CHANGELOG.md          # Semantic versioning (Keep a Changelog format)
│   └── PRESENTATION.md       # Executive overview & operational benefits
├── issues/                   # Architectural Decision Records (ADR) & Issue Post-Mortems
│   ├── ISSUE-001_xxx.md
│   └── ISSUE-002_xxx.md
├── reports/                  # Generated benchmark and audit reports (HTML + JSON)
└── tests/
    ├── unit/                 # Fast synthetic test suite
    └── live_benchmark/       # Benchmark suite, Catalog, Evaluators, Dashboard Reporters
```

### 8.1 Required Standard Documents
1. **`README.md`:** Must provide an architecture summary, environment setup instructions, and single-line commands to run both the synthetic test suite and the live benchmark suite.
2. **`docs/ARCHITECTURE.md`:** Must contain ASCII/Mermaid component topologies, sequence diagrams for core transaction flows, and modular boundaries.
3. **`docs/SECURITY.md`:** Must declare local data retention policies, credential handling rules, safety gate enforcement, and vulnerability reporting contacts.
4. **`docs/CONTRIBUTING.md`:** Must declare commit guidelines, pre-push hook configurations, linting rules, and review standards.
5. **`docs/CHANGELOG.md`:** Adheres strictly to [Keep a Changelog](https://keepachangelog.com/) with semantic versioning (`vMAJOR.MINOR.PATCH`).
6. **`issues/` (Architectural Decision Records & Post-Mortems):** Any significant technical challenge, bug discovery, or architectural pivot must be preserved as a numbered record (`ISSUE-001_description.md`) documenting Context, Root Cause, Options Considered, Decision, and Verification.

---

## 9. Compliance Certification Checklist & Scoring Rubric

Before any project or domain cartridge is certified for staging or production deployment, it must be evaluated against this rubric:

```
═══════════════════════════════════════════════════════════════════════════
        ENGINEERING EXCELLENCE CERTIFICATION AUDIT CHECKLIST
═══════════════════════════════════════════════════════════════════════════

[ ] 1. SAFETY ARCHITECTURE
    [ ] 1.1 Deterministic Pre-Execution Gate (Layer 0) active.
    [ ] 1.2 Stochastic reasoning constrained with Structured JSON / Pydantic schemas.
    [ ] 1.3 Post-execution confidence threshold gate (Confidence < 85% diverted to Review).
    [ ] 1.4 Zero destructive commands executable by autonomous model.
    [ ] 1.5 Fail-safe default (Shadow Mode / Dry-Run support verified).

[ ] 2. DUAL-ENGINE VERIFICATION
    [ ] 2.1 Synthetic test suite passes with >= 80% code coverage (`pytest`).
    [ ] 2.2 Curated `benchmark_catalog.json` exists with authentic domain scenarios.
    [ ] 2.3 `run_live_benchmark.py` passes with `--quality-gate`.
    [ ] 2.4 Hard Safety Pass Rate is exactly 100.0%.
    [ ] 2.5 Overall Functional Pass Rate is >= 80.0%.
    [ ] 2.6 Dual reports (`reports/live_benchmark.html` & `.json`) generated successfully.

[ ] 3. COMPLIANCE & TELEMETRY
    [ ] 3.1 Tri-format audit trail implemented (`.jsonl`, `.csv`, `.html`).
    [ ] 3.2 Cryptographic SHA-256 hash chaining active on all audit records.
    [ ] 3.3 Structured logging active with UTC timestamps and correlation IDs.

[ ] 4. ZERO-TRUST SECURITY
    [ ] 4.1 Git repository verified clean of all secrets, `.env`, tokens, and databases.
    [ ] 4.2 Credentials and biometric tokens encrypted at rest using AES-256-GCM.
    [ ] 4.3 Inbound network attack surface eliminated via outbound relays / TLS 1.3.

[ ] 5. CODE HYGIENE & ARCHITECTURE
    [ ] 5.1 100% type annotation completeness verified (`mypy --strict`).
    [ ] 5.2 Google-style docstrings present on all classes, methods, and modules.
    [ ] 5.3 PEP 8 compliance verified (`ruff` / `black`).
    [ ] 5.4 Domain logic isolated in cartridge; reusable skills promoted to core library.

[ ] 6. INTELLECTUAL PROPERTY & GOVERNANCE
    [ ] 6.1 Apache 2.0 copyright and license notice header on all source files.
    [ ] 6.2 Third-party dependencies verified for license compatibility and security audits.

[ ] 7. LIVING DOCUMENTATION
    [ ] 7.1 Complete documentation suite present (`README`, `ARCHITECTURE`, `SECURITY`,
        `CONTRIBUTING`, `CHANGELOG`).
    [ ] 7.2 Complex architectural decisions recorded in `issues/ISSUE-xxx.md`.

═══════════════════════════════════════════════════════════════════════════
CERTIFICATION LEVELS:
  • Level 1 (Sandbox/Dev) : Passes Section 1 & 5.
  • Level 2 (Staging Beta): Passes Sections 1, 2, 4, 5, 6.
  • Level 3 (Production)  : 100% Compliance across ALL Sections (1 through 7).
═══════════════════════════════════════════════════════════════════════════
```

---

## 10. Adoption & Extension Guide for Global Teams

This standard is designed to be universally applicable across languages (Python, TypeScript, Go, Rust), platforms (Desktop, Web, Cloud, Embedded Kiosk), and industries (Food Tech, FinTech, Healthcare, Logistics).

### How to Adopt in Any New Repository
1. **Copy Standard to Project Root:** Place this document as `ENGINEERING_EXCELLENCE_STANDARD_v1.0.md` or `docs/ENGINEERING_STANDARD.md`.
2. **Implement the Scaffolding:** Create `reports/`, `tests/live_benchmark/`, and `issues/`.
3. **Configure the Quality Gate:** Add `python run_live_benchmark.py --quality-gate` to your CI/CD pipeline (GitHub Actions, GitLab CI, Jenkins).
4. **Enforce in Code Review:** Mandate that no Pull Request may be approved unless all Level 2/3 criteria are verified.
