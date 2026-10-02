# Global Engineering Excellence Standard (GEES) v2.0
## Architectural, Safety, Verification, and Operational Framework for Mission-Critical, Modular & Agentic Software Systems

```
Document Reference : EES-STD-2026-V2.0
Status             : Approved Organizational & Open-Source Standard
Author             : Mahendra GURAV
License            : Apache License, Version 2.0
Scope              : Universal (All Core Platforms, Domain Cartridges, Kiosk Systems & AI Agents)
```

---

## 1. Executive Mandate & Philosophical Foundation

The rapid rise of stochastic artificial intelligence, agentic state machines, and edge-connected IoT devices introduces immense transformative capability alongside severe risks: silent hallucinations, cascading failure loops, domain pollution across shared cores, hardcoded assumptions, data tampering, credential leakage, and non-deterministic application states.

**Toy prototypes, hackathon scripts, and un-encapsulated monoliths are strictly prohibited from entering production.** 

The **Global Engineering Excellence Standard (GEES v2.0)** codifies the mandatory architectural, safety, testing, security, type discipline, and governance requirements that must govern any software system built within our organization and across our open-source initiatives. 

### The Six Inviolable Axioms
1. **Determinism Surrounds Stochasticity:** Probabilistic AI models must always be encased in deterministic pre-execution guardrails and deterministic post-execution validators. No model output is ever trusted blindly.
2. **Strict Microkernel Separation:** The shared platform core must remain 100% domain-agnostic. Domain cartridges must be self-contained and modular. Domain logic, entity names, or app-specific imports must NEVER pollute the core.
3. **Hard Safety & Zero Regressions are Non-Negotiable:** A single safety breach represents total failure. The safety pass threshold for release is **100.0%**.
4. **Type Completeness on Code Generation:** All Python code must be generated with 100% explicit type annotations adhering strictly to `mypy --strict`.
5. **Non-Repudiation by Default:** Every critical transaction, decision, and sensor capture must be permanently logged in immutable, cryptographically verifiable audit trails conforming to international regulatory standards (e.g., FDA 21 CFR Part 11, ISO 22000, SOC 2).
6. **Zero-Trust Credential Isolation:** No secret, token, key, or unencrypted credential may ever touch version control or persist in plain text at rest.

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
│ • Unregistered entity / Ghost sender pre-execution filtering            │
│ • Tamper detection & rate limiting                                     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Pass)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: Stochastic Model / Agent Reasoning Engine                      │
│ • Schema-enforced outputs (Pydantic / Structured JSON mode)             │
│ • Grounded context only (Anti-stalling & Anti-hallucination rules)       │
│ • Temperature clamps (Deterministic tasks: 0.0 – 0.2)                   │
│ • Strict model-agnostic abstraction (Configurable LLM gateway)          │
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
- **Input Sanitization:** Reject or neutralize potential prompt injections, malicious payloads, script tags, and malformed binary headers before stochastic processing.
- **Physical Verification:** Physical parameters (e.g., GPS coordinates via Haversine distance calculations) must be validated against kiosks or facility geofences prior to authorizing actions.
- **Ghost Ingress Defense:** Unregistered senders or unknown external actors must be intercepted at Layer 0 with clean onboarding guidance without creating spurious database records or triggering administrative escalations.

### 2.2 Layer 1: Stochastic Model Reasoning & Constraints
- **Structured Contracts Only:** Free-form raw text parsing from LLMs is prohibited. All model inferences must return strictly typed schemas (Pydantic models, JSON Schema enforcement).
- **Grounding & Anti-Hallucination:** Models must be provided explicit context and strictly instructed not to extrapolate facts. In draft generation, models must adhere to anti-stalling guardrails.
- **Temperature Governance:** Deterministic classification, OCR parsing, and factual triage must use temperatures between `0.0` and `0.2`. Creative or conversational tasks must not exceed `0.7`.

### 2.3 Layer 2: Deterministic Post-Execution Gate
- **Confidence Clamping:** All model-generated decisions must carry an explicit confidence metric. If confidence drops below **85%**, the system must automatically divert the payload to an escalation queue (`Needs Review` / Admin Approval Gate) and prevent autonomous action.
- **Destructive Command Interception:** Destructive mutations (e.g., deleting records, truncating databases, or altering baseline safety parameters) are strictly prohibited from autonomous model execution.
- **Fail-Safe Defaults (Shadow Mode):** All deployments must boot with Dry-Run / Shadow Mode capability (`DRY_RUN=True`).

---

## 3. Pillar 2: Dual-Engine Verification Framework

Quality is guaranteed through an integrated, dual-engine testing regime.

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
- **Type Checking Enforcement:** Zero errors under `mypy --strict` or `pyright`.
- **Architectural Boundary Enforcement:** Automated AST tests verify that `core_platform/` contains zero imports from `apps/`.

### 3.2 Engine B: High-Fidelity Live Benchmark Suite
- **Purpose:** Rigorously validate system performance across authentic, real-world domain scenarios.
- **Hard Safety Quality Gate Thresholds (`--quality-gate`):**
  - **Hard Safety Compliance:** **100.0%** (Zero Tolerance).
  - **Overall Functional Pass Rate:** **>= 80.0%**.
  - **Automated Dual Reports:** Interactive HTML dashboard (`reports/live_benchmark.html`) and machine-readable JSON (`reports/live_benchmark.json`).

---

## 4. Pillar 3: Strict Microkernel Architecture & Domain Isolation

To prevent monolithic spaghetti, regression loops, and domain pollution across apps:

```
+-------------------------------------------------------------------------+
| core_platform/ (Pure Generic Runtime Engine)                            |
|   * Plugin Loader & Lifecycle Supervisor                                |
|   * Transport Ingress (WhatsApp/Web/REST) -> UnifiedMessageEnvelope     |
|   * Universal Skills Library (Raw OCR, Face Embedding, Geofence Math)   |
|   * LLM Gateway & Security/RBAC Guardrails                              |
|   * Outbox Synchronizer & SHA-256 Non-Repudiation Audit Engine          |
+-------------------------------------------------------------------------+
                                   │
                      (Strict Inversion of Control)
                                   ▼
+-------------------------------------------------------------------------+
| apps/<app_id>/ (Self-Contained Domain Cartridges)                       |
|   * Domain State Graph (LangGraph nodes & business rules)               |
|   * Domain Schemas, Pydantic Models, & DB Migrations                    |
|   * Domain Thresholds, UI Templates, & Static Assets                    |
|   * Plugin Manifest (`plugin.py` exposing hooks & routes)               |
+-------------------------------------------------------------------------+
```

### 4.1 Zero Domain Code in Core Platform
- `core_platform/` must contain **ZERO** domain concepts, domain keywords, or domain decision trees.
- `core_platform/` must **NEVER** import any module from `apps/`.
- Core interacts with apps strictly through the `BaseApplication` plugin interface and generic event envelopes (`UnifiedMessageEnvelope`).

### 4.2 Declarative Plugin Inversion of Control
Every application cartridge must be self-contained in `apps/<app_id>/` and declare its own:
1. Transport routes and webhooks via plugin mounting.
2. UI navigation items and templates via manifest properties.
3. Outbox message handlers via hook subscriptions.
4. Background pollers via lifecycle hooks (`on_startup`, `on_shutdown`).

### 4.3 Hermetic Cognitive Skills Decoupling
- Universal cognitive skills in `core_platform/app/skills/` (OCR, Face Embeddings, Geofencing, Audio Processing) are pure stateless algorithms.
- Skills must never embed domain business rules. Domain cartridges consume skills (`ctx.get_skill(...)`) and interpret raw perceptual outputs inside their own state graph nodes.

---

## 5. Pillar 4: Zero-Hardcoding & Runtime Dynamic Resolution

1. **Zero Hardcoded Constants in Code:** No entity IDs, station names, phone numbers, URLs, physical thresholds, prompt strings, or magic constants may ever be hardcoded in Python source files.
2. **Typed Configuration Injection:** All operational settings must be declared and validated via typed Pydantic `Settings` (loaded from `.env` or system environment).
3. **Dynamic Knowledge Resolution:** All physical locations, user rosters, kiosk IDs, and organizational graphs must be loaded dynamically from the database or Knowledge Graph runtime.
4. **Prompt Externalization:** AI system prompts and instructions must reside in external templates or cartridge prompt registries.

---

## 6. Pillar 5: Code Generation Type Discipline (`mypy --strict`)

1. **100% Type Annotations on Generation:** All newly authored or modified Python functions, methods, parameters, and return values MUST feature complete, explicit type annotations conforming to `mypy --strict` from the moment of code generation.
2. **Prohibition of Implicit `Any`:** Using untyped arguments, untyped return values, or bare `Any` escapes without explicit architectural justification is strictly forbidden.
3. **Pydantic Data Contracts:** All API request/response bodies, message payloads, and database DTOs must be explicitly defined as Pydantic models.
4. **Causal Exception Chaining:** Bare `except:` clauses are banned. Catch explicit exception types and chain causal context (`raise DomainError(...) from err`).

---

## 7. Pillar 6: Clean-Slate Bootstrapping & Resource Scoping

1. **Zero-Entity Bootstrapping Resilience:** Every module, graph node, and router must be designed to boot and operate cleanly from a clean-slate state (0 users, 0 stations, 0 kiosks, empty DB) without unhandled exceptions or 500 errors.
2. **Deterministic Context Management:** All database handles, SQLite connections, HTTP sessions, thread pools, and file descriptors must be strictly scoped within deterministic context managers (`with` / `async with`) to eliminate Windows file locks (`WinError 32`) and resource exhaustion.
3. **ASCII-Safe CLI Output:** All build scripts, packaging tools, and CLI utilities must output ASCII-safe tags (e.g. `[BUILD]`, `[SUCCESS]`, `[ERROR]`) to prevent fatal `UnicodeEncodeError` exceptions on Windows consoles (`cp1252`/`cp437`).

---

## 8. Pillar 7: Regulatory Compliance, Auditing & Deep Telemetry

1. **Tri-Format Contemporaneous Logging:** All critical transactions must stream to `.jsonl` (Cloud/SIEM), `.csv` (Excel/Floor QA), and `.html` (Visual audit dashboard).
2. **Cryptographic SHA-256 Hash Chaining:**
   $$\text{Record Hash} = \text{SHA-256}(\text{Prev Hash} + \text{Timestamp} + \text{Payload})$$
   Enforced on all audit trails to guarantee tamper-evidence under FDA 21 CFR Part 11 and ISO 22000.

---

## 9. Pillar 8: Zero-Trust Security & Credential Isolation

1. **Zero Real Credentials or Secret Signatures in Git / Code / Tests:**
   - `.env`, secrets, private keys, live tokens, and `*.db` files must NEVER be committed to version control.
   - **Mandatory Synthetic Test Fixtures:** Unit tests, doctests, mocks, fixtures, and documentation MUST NEVER contain real credentials or live provider secret signatures (e.g. `AIza...`, `AQ....`, `EAA...`, `ghp_...`, `sk-...`). All test keys, test assertions, and placeholder tokens MUST use generic, synthetic dummy strings (e.g. `mock_gemini_test_key_12345`, `mock_whatsapp_access_token_abcdef`, `test_jwt_secret_98765`).
   - **Automated Zero-Secret Leak Guard:** The test suite must continuously execute an automated secret scanner (`test_zero_secret_leak_guard.py`) that fails the test build if any tracked file matches live credential token patterns or unmasked credentials.
2. **Encryption at Rest:** Sensitive tokens, credentials, and biometric embeddings must be encrypted locally using **AES-256-GCM**.
3. **Zero Inbound Attack Surface:** Edge machines must use outbound reverse tunnels / WebSocket relays (e.g. Cloudflare Workers with Durable Objects) instead of open inbound ports.
4. **Public Endpoint Sanitization:** Public `/health` endpoints must reveal strictly minimal status (`{"status": "UP", "version": "..."}`); detailed metrics require authenticated administrative tokens.

---

## 10. Pillar 9: Intellectual Property & Governance

1. **Apache License 2.0 Header:** All source files (`.py`, `.ts`, `.js`, `.sh`, `.ps1`) must include the Apache 2.0 copyright notice:
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
2. **Protected Pet Projects Constraint:** The pet projects `D:\mailOrganizer`, `D:\WhatsappClientForMailOrganized`, and `D:\AI-ProjectManager` are strictly read-only references. **NEVER modify or write to those directories under any circumstances.**

---

## 11. Compliance Certification Checklist & Rubric

```
═══════════════════════════════════════════════════════════════════════════
       GEES v2.0 ENGINEERING EXCELLENCE CERTIFICATION CHECKLIST
═══════════════════════════════════════════════════════════════════════════

[ ] 1. SAFETY & DETERMINISM
    [ ] 1.1 Layer 0 Deterministic Pre-Execution Gate active.
    [ ] 1.2 Stochastic reasoning constrained with Structured Pydantic schemas.
    [ ] 1.3 Post-execution confidence threshold gate (Confidence < 85% diverted).
    [ ] 1.4 Zero destructive commands executable autonomously.
    [ ] 1.5 Shadow Mode / Dry-Run (`DRY_RUN=True`) verified.

[ ] 2. DUAL-ENGINE VERIFICATION
    [ ] 2.1 Engine A synthetic test suite passes with >= 80% coverage (`pytest`).
    [ ] 2.2 Curated `benchmark_catalog.json` exists with authentic domain scenarios.
    [ ] 2.3 `run_live_benchmark.py --quality-gate` passes with 100.0% Hard Safety.
    [ ] 2.4 Overall Functional Pass Rate is >= 80.0%.
    [ ] 2.5 Dual reports (`reports/live_benchmark.html` & `.json`) generated.

[ ] 3. MICROKERNEL & MODULAR ISOLATION
    [ ] 3.1 Zero domain logic or entity keywords inside `core_platform/`.
    [ ] 3.2 Automated AST boundary test passes (`core_platform` imports ZERO `apps`).
    [ ] 3.3 Domain cartridges completely self-contained in `apps/<app_id>/`.
    [ ] 3.4 Cognitive skills in `core_platform/app/skills/` are hermetic and raw.

[ ] 4. CONFIGURATION & ZERO HARDCODING
    [ ] 4.1 Zero hardcoded IDs, entity names, phone numbers, or magic numbers.
    [ ] 4.2 All configuration validated via typed Pydantic Settings.
    [ ] 4.3 Clean-slate resilience verified (0-entity state boots cleanly).

[ ] 5. TYPE DISCIPLINE & CODE HYGIENE
    [ ] 5.1 100% type annotations on all code generation (`mypy --strict`).
    [ ] 5.2 Google-style docstrings on all modules, classes, and methods.
    [ ] 5.3 Deterministic context management (`with`) on all DB and I/O handles.
    [ ] 5.4 ASCII-safe console output for Windows CLI compatibility.

[ ] 6. TELEMETRY, SECURITY & GOVERNANCE
    [ ] 6.1 Tri-format audit logging (`.jsonl`, `.csv`, `.html`) active.
    [ ] 6.2 SHA-256 cryptographic hash chaining verified.
    [ ] 6.3 Zero credentials in Git; AES-256-GCM encryption at rest.
    [ ] 6.4 Apache License 2.0 header present on all source files.
    [ ] 6.5 Protected pet projects untouched.
═══════════════════════════════════════════════════════════════════════════
```
