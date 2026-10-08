# Mandatory Engineering Excellence Standard (GEES v3.0) Operating Directives

> **INVIOLABLE OPERATIONAL DIRECTIVE FOR ALL AGENTS AND DEVELOPERS:**
> This repository is governed by the **Global Engineering Excellence Standard (GEES v3.0)** defined in [ENGINEERING_EXCELLENCE_STANDARD_v3.0.md](./ENGINEERING_EXCELLENCE_STANDARD_v3.0.md).
> All agents, contributors, and subagents MUST automatically and strictly follow these rules on **EVERY** task without requiring explicit user instruction or reminders.

---

## 1. 4-Plane Microkernel Architecture & System Applications
* **Plane 1 (Ingress/Edge):** Pure host normalization, TLS, and raw context synthesis. Zero DB/auth logic in ingress.
* **Plane 2 (Slim Microkernel Substrate):** The kernel contains ZERO domain or UI concepts. Provides DI Service Locator (Protocols), Event Bus, and Polyglot DB pool.
* **Plane 3 (System Applications):** Core functions (`tenancy`, `iam`, `rbac`, `entitlements`, `admin_shell`, `ops_control`) are autonomous, non-configurable System Apps. Each app strictly owns its database tables (Data Sovereignty) and communicates exclusively via `Protocol` interfaces.
* **Plane 4 (Domain Workload Cartridges):** Cartridges in `apps/<app_id>/` consume platform capabilities strictly through the injected `AppContext` SDK.

## 2. Platform Synergy & Composable UI
* **Composable UI Shell:** All UI screens integrate into the unified Admin Shell using shared Jinja2 UI macros and design tokens.
* **Event-Driven Choreography:** Cross-app workflows execute via asynchronous domain events over the kernel event bus with zero direct code coupling.
* **Shared Cognitive Substrate:** All apps leverage shared cognitive skills (`core_platform/app/skills/`).

## 2. Dual-Engine Verification Regime
* **Engine A (Fast Synthetic Suite):** Every component must have `pytest` unit tests with mocked boundaries, **>= 80% line/branch code coverage**, zero type errors under `mypy --strict`, verified architectural AST boundaries, and automated **Packaging & Manifest Integrity Verification** (`test_packaging_manifest_integrity.py` asserting all imports, top-level packages, and Jinja2 templates are 100% declared in `pyproject.toml`).
* **Engine B (High-Fidelity Live Benchmark Suite):** Every application must feature `run_live_benchmark.py` and a curated `benchmark_catalog.json`.
* **The Quality Gate (`--quality-gate`):**
  * **100.0% Hard Safety Pass Rate** is mandatory (Zero safety breaches, zero loops, zero unauthorized actions).
  * **>= 80.0% Overall Functional Pass Rate** is mandatory.
  * Interactive HTML dashboard (`reports/live_benchmark.html`) and JSON summary (`reports/live_benchmark.json`) must be produced on every run.

## 3. Strict Microkernel Architecture & Zero Domain Pollution in Core
* **Core Microkernel Boundary:** `core_platform/` must contain **ZERO** domain concepts, domain keywords, or domain decision trees. `core_platform/` MUST NEVER import any module from `apps/`.
* **Plugin Inversion of Control:** Domain cartridges in `apps/<app_id>/` are 100% self-contained, declaring their own routes, templates, outbox message handlers, and lifecycle hooks via `BaseApplication` (`plugin.py`).
* **Hermetic Cognitive Skills:** Skills in `core_platform/app/skills/` are pure stateless perceptual algorithms (OCR, Face Embeddings, Geofence Math). Skills must never embed domain business rules.

## 4. Zero-Hardcoding & Runtime Dynamic Resolution
* **Zero Hardcoded Constants in Code:** No entity IDs, station names, phone numbers, URLs, physical thresholds, prompt strings, or magic constants may ever be hardcoded in Python source code.
* **Typed Configuration:** All operational settings must be declared and validated via typed Pydantic `Settings`.
* **Dynamic Knowledge Resolution:** All locations, user rosters, kiosk IDs, and organizational graphs must be loaded dynamically from database or Knowledge Graph runtime.

## 5. Code Generation Type Discipline (`mypy --strict`)
* **Mandatory on Code Generation:** All newly written or modified Python functions, methods, parameters, and return values MUST feature complete, explicit type annotations conforming to `mypy --strict` from the first keystroke.
* **No Untyped Escapes:** Untyped arguments, untyped return values, or bare `Any` escapes without explicit architectural justification are strictly forbidden.
* **Pydantic Contracts:** All API request/response bodies, message payloads, and database DTOs must be explicitly defined as Pydantic models.
* **Causal Exception Chaining:** Bare `except:` clauses are banned. Catch explicit exception types and chain causal context (`raise DomainError(...) from err`).

## 6. Clean-Slate Bootstrapping & Resource Scoping
* **Zero-Entity Resilience:** Every module, graph node, and router must boot and operate cleanly from a clean-slate state (0 users, 0 stations, 0 kiosks, empty DB) without unhandled exceptions or 500 errors.
* **Deterministic Resource Management:** All database handles, SQLite connections, HTTP sessions, thread pools, and file descriptors must be strictly scoped within deterministic context managers (`with` / `async with`).
* **ASCII-Safe CLI Output:** All build scripts, packaging tools, and CLI utilities must output ASCII-safe tags (e.g. `[BUILD]`, `[SUCCESS]`, `[ERROR]`) to prevent fatal `UnicodeEncodeError` exceptions on Windows consoles (`cp1252`/`cp437`).

## 7. Regulatory Compliance & Deep Telemetry
* **Tri-Format Logging:** All significant events must contemporaneously stream to `.jsonl` (Cloud/SIEM), `.csv` (Excel/Shop-floor), and `.html` (Visual audit dashboard).
* **Cryptographic Non-Repudiation:** SHA-256 hash chaining ($\text{Record Hash} = \text{SHA-256}(\text{Prev Hash} + \text{Timestamp} + \text{Payload})$) must be enforced on all audit trails to prevent retrospective tampering (FDA 21 CFR Part 11 / ISO 22000 compliance).

## 8. Zero-Trust Security & Credential Isolation
* **Zero Real Credentials or Secret Signatures in Git / Code / Tests:** `.env`, secrets, private keys, tokens, and `*.db` files must NEVER be committed to Git.
* **Mandatory Synthetic Test Fixtures:** Unit tests, mocks, fixtures, and documentation MUST NEVER contain real credentials or live provider secret signatures (e.g. `AIza...`, `AQ....`, `EAA...`, `ghp_...`, `sk-...`). All test keys, test assertions, and placeholder tokens MUST use generic, synthetic dummy strings (e.g. `mock_gemini_test_key_12345`, `mock_whatsapp_access_token_abcdef`, `test_jwt_secret_98765`).
* **Automated Zero-Secret Leak Guard:** The test suite must continuously execute an automated secret scanner (`test_zero_secret_leak_guard.py`) that fails the test build if any tracked file matches live credential token patterns or unmasked credentials.
* **Encryption at Rest:** Sensitive tokens, credentials, and biometric embeddings must be encrypted locally using **AES-256-GCM**.
* **Zero Inbound Attack Surface:** Edge machines must use outbound reverse tunnels / WebSocket relays (e.g. Cloudflare Workers with Durable Objects) instead of open inbound ports.
* **Public Endpoint Sanitization:** Public `/health` endpoints must return strictly minimal status (`{"status": "UP", "version": "..."}`); detailed diagnostics require authenticated admin access.

## 9. Intellectual Property & Licensing
* All source files must contain the standard **Apache License 2.0** copyright notice:
  `Copyright 2026 Mahendra GURAV`

## 10. Protected Pet Projects Constraint
* The pet projects `D:\mailOrganizer`, `D:\WhatsappClientForMailOrganized`, and `D:\AI-ProjectManager` are read-only references. **NEVER modify or write to those directories under any circumstances.**

## 11. Explicit User Approval for Remote Git Pushes
* **Explicit Go Required for Remote Pushes:** Under NO circumstances may an agent or subagent execute `git push` to GitHub or any remote repository without first presenting the proposed commit list/diff to the USER and receiving explicit user confirmation ("go" / approval). Local git commits and local tests may proceed autonomously, but remote pushes are strictly gated by user consent.

