# Mandatory Engineering Excellence Standard (GEES v3.1) Directives for All Agents

> **INVIOLABLE OPERATIONAL DIRECTIVE FOR ALL AGENTS AND DEVELOPERS:**
> This repository is governed by the **Global Engineering Excellence Standard (GEES v3.1)** defined in [ENGINEERING_EXCELLENCE_STANDARD_v3.0.md](./ENGINEERING_EXCELLENCE_STANDARD_v3.0.md).
> All agents, contributors, and subagents MUST automatically and strictly follow these rules on **EVERY** task without requiring explicit user instruction or reminders.

---

## 1. 4-Plane Microkernel Architecture & System Applications
* **Plane 1 (Ingress/Edge):** Pure host normalization, TLS, and raw context synthesis. Zero DB/auth logic in ingress.
* **Plane 2 (Slim Microkernel Substrate):** The kernel contains ZERO domain or UI concepts. Provides DI Service Locator (Protocols), Event Bus, and Polyglot DB pool.
* **Plane 3 (System Applications):** Core functions (`tenancy`, `iam`, `rbac`, `entitlements`, `admin_shell`, `ops_control`) are autonomous, non-configurable System Apps with strict Data Sovereignty.
* **Plane 4 (Domain Workload Cartridges):** Cartridges in `apps/<app_id>/` consume platform capabilities strictly through the injected `AppContext` SDK.

## 2. Multi-Layered Safety Architecture & Fail-Safe Defaults
* **Layer 0 (Deterministic Pre-Execution):** Always execute hardcoded Python checks (VIP whitelists, sensor physical sanity boundaries, Haversine GPS geofence checks) BEFORE any model/LLM invocation.
* **Layer 1 (Stochastic Reasoning Engine):** All AI outputs must be constrained to structured Pydantic schemas. Temperature clamped to 0.0 – 0.2 for deterministic classification/OCR/parsing.
* **Layer 2 (Deterministic Post-Execution):** Any classification, OCR, or face match with confidence < 85% MUST automatically divert to human review (`Needs Review` / Admin Approval Gate). Zero destructive commands (deletions, truncations) executable by autonomous models. Default mode is Shadow/Dry-Run (`DRY_RUN=True`).

## 3. Zero-False-Success Verification & E2E Rigidity (GEES v3.1)
* **Ban on Shallow Status 200 Tests:** Every UI route test must assert **Actionable DOM Invariants** (verifying `<form action="...">`, required input controls, submit buttons, and localized text exist).
* **Mandatory Clean-Slate Round-Trip Mutation Tests:** All stateful features must be tested starting from the **exact default state of a brand-new tenant on Day 1** (`GET (default)` $\rightarrow$ `POST (mutate)` $\rightarrow$ `GET (verify persisted state)`).
* **6 Mandatory End-to-End Persona & Cartridge Journeys:**
  1. `test_e2e_tenant_admin_onboarding_and_vault.py`: Provision $\rightarrow$ Login $\rightarrow$ Brand & Timezone $\rightarrow$ BYOK/Platform toggle $\rightarrow$ AES-256-GCM encryption $\rightarrow$ User invite.
  2. `test_e2e_mail_organizer_workflow.py`: Email ingress $\rightarrow$ Tenant Context $\rightarrow$ LLM triage $\rightarrow$ Token cost ledger $\rightarrow$ PM review $\rightarrow$ Outbound dispatch.
  3. `test_e2e_temperature_marker_kiosk.py`: Kiosk payload $\rightarrow$ Haversine GPS geofence $\rightarrow$ Face & OCR skills $\rightarrow$ Fever anomaly $\rightarrow$ Supervisor approval $\rightarrow$ WhatsApp alert $\rightarrow$ SHA-256 audit log.
  4. `test_e2e_cross_cartridge_synergy.py`: Kiosk anomaly $\rightarrow$ Kernel Event Bus $\rightarrow$ Mail Organizer briefing (zero cross-app concrete imports).
  5. `test_e2e_concurrent_multi_tenant_key_routing.py`: Simultaneous BYOK vs Platform requests $\rightarrow$ dynamic key resolution $\rightarrow$ expense liability isolation $\rightarrow$ zero key cross-talk.
  6. `test_e2e_clean_slate_boot_and_resilience.py`: Clean boot with 0 tenants/users/kiosks $\rightarrow$ zero unhandled 500s.
* **Inviolable 3-Tier Iterative Verification & Fast-Push Policy:**
  1. **Tier 1 (Targeted Iteration - Always Active):** During active development/fixing, run ONLY the new or impacted test files (`pytest <impacted_test_path>`) for instant 2-3s feedback.
  2. **Tier 2 (Fast Pre-Commit Staging Gate - Always Required):** Always run `python scripts/verify_all.py --fast` (~15s) prior to presenting diffs for commit/push. This validates AST boundaries, `mypy --strict`, packaging manifest integrity, version parity, and zero secrets across the whole codebase without running slow suites.
  3. **Tier 3 (Fast-Push & Asynchronous Quality Gate):** After Tier 1 and Tier 2 pass, present the commit diff for explicit user approval ("go") and push immediately so manual user testing (e.g. mobile, ngrok, UI) can begin without waiting. Concurrently trigger Tier 3 (`python scripts/verify_all.py --quality-gate`) in the background. If any edge-case regression is caught by Tier 3 or manual testing, apply a follow-up targeted fix.
  4. **Port 8000 Exclusivity Rule:** Port 8000 is reserved exclusively for the user's manual server runtime. Agents must NEVER bind to, occupy, kill, or launch background daemons targeting port 8000.

## 4. Dual-Engine Verification Regime
* **Engine A (Fast Synthetic Suite):** Every component must have `pytest` unit tests with mocked boundaries, **>= 80% line/branch code coverage**, zero type errors under `mypy --strict`, verified architectural AST boundaries, and automated **Packaging & Manifest Integrity Verification** (`test_packaging_manifest_integrity.py`).
* **Engine B (High-Fidelity Live Benchmark Suite):** Every application must feature `run_live_benchmark.py` and a curated `benchmark_catalog.json` with **100.0% Hard Safety Pass Rate** and **>= 80.0% Overall Functional Pass Rate**.

## 5. Regulatory Compliance & Deep Telemetry
* **Tri-Format Logging:** All significant events must contemporaneously stream to `.jsonl` (Cloud/SIEM), `.csv` (Excel/Shop-floor), and `.html` (Visual audit dashboard).
* **Cryptographic Non-Repudiation:** SHA-256 hash chaining ($\text{Record Hash} = \text{SHA-256}(\text{Prev Hash} + \text{Timestamp} + \text{Payload})$) must be enforced on all audit trails.

## 6. Zero-Trust Security & Credential Isolation
* **Zero Credentials in Git / Code / Tests:** `.env`, secrets, private keys, tokens, and `*.db` files must NEVER be committed to Git. All test keys must use generic synthetic dummy strings (`mock_gemini_test_key_12345`).
* **Encryption at Rest:** Sensitive tokens, credentials, and biometric embeddings must be encrypted locally using **AES-256-GCM**.
* **Zero Inbound Attack Surface:** Edge machines must use outbound reverse tunnels / WebSocket hibernation instead of open inbound ports.

## 7. Code Hygiene & Universal Skills Library
* **Type Completeness:** 100% Python type annotations enforced under `mypy --strict`.
* **Universal Skills Library:** Reusable cognitive skills (`FaceRecognizerSkill`, `DisplayOCRSkill`, `ImageEnhancerSkill`, `GeofencingSkill`) reside in `core_platform/app/skills/` and remain strictly decoupled from domain cartridges.
* **Style:** Google-style docstrings, PEP 8 formatting, explicit error handling with causal chaining (`raise DomainError from err`).

## 8. Intellectual Property & Licensing
* All source files must contain the standard **Apache License 2.0** copyright notice:
  `Copyright 2026 Mahendra GURAV`

## 9. Protected Pet Projects Constraint
* The pet projects `D:\mailOrganizer`, `D:\WhatsappClientForMailOrganized`, and `D:\AI-ProjectManager` are read-only references. **NEVER modify or write to those directories under any circumstances.**

## 10. Explicit User Approval for Remote Git Pushes
* **Explicit Go Required for Remote Pushes:** Under NO circumstances may an agent or subagent execute `git push` without first presenting the proposed commit list/diff to the USER and receiving explicit user confirmation ("go" / approval).

## 11. Automated Multi-Channel Package Distribution & Version Invariants
* **Strict Version Parity & Semantic Versioning:** Root `pyproject.toml` (`release100-core`), `apps/temperature_marker/pyproject.toml` (`release100-cartridge-temperature-marker`), `apps/mail_organizer/pyproject.toml` (`release100-cartridge-mail-organizer`), and all corresponding `__version__` constants must remain in strict synchronization on every change.
* **Mandatory Version Increment on Code Change:** Any commit modifying code within a cartridge or core platform MUST increment the version in both `pyproject.toml` and the corresponding `__version__` attribute before commit or push (mechanically enforced via `test_version_bump_guard.py` under `MANIFEST-GUARD`).
* **Automated Packaging Verification:** Every new template, asset, or dependency must be declared in `pyproject.toml` and verified via `MANIFEST-GUARD` before push.
* **Automated Sandbox Index Generation:** All pushes to `intent-router` and `main` automatically publish PEP 503 package wheels to GitHub Pages for instant sandbox installation.

## 12. Model Reasoning & Thinking Configuration
* **Mandatory Flash (High) Thinking Level:** All development, bug fixing, deep analysis, and code generation tasks must strictly use the Gemini Flash (High Thinking) model configuration. Never downgrade thinking levels during development.



