# Mandatory Engineering Excellence Standard (GEES v1.0) Operating Directives

> **INVIOLABLE OPERATIONAL DIRECTIVE FOR ALL AGENTS AND DEVELOPERS:**
> This repository is governed by the **Global Engineering Excellence Standard (GEES v1.0)** defined in [ENGINEERING_EXCELLENCE_STANDARD_v1.0.md](./ENGINEERING_EXCELLENCE_STANDARD_v1.0.md).
> All agents, contributors, and subagents MUST automatically and strictly follow these rules on **EVERY** task without requiring explicit user instruction or reminders.

---

## 1. Multi-Layered Safety Architecture & Fail-Safe Defaults
* **Layer 0 (Deterministic Pre-Execution):** Always execute hardcoded Python checks (VIP whitelists, sensor physical sanity boundaries, Haversine GPS geofence checks) BEFORE any model/LLM invocation.
* **Layer 1 (Stochastic Reasoning Engine):** All AI outputs must be constrained to structured Pydantic schemas. Temperature clamped to 0.0 – 0.2 for deterministic classification/OCR/parsing.
* **Layer 2 (Deterministic Post-Execution):** Any classification, OCR, or face match with confidence < 85% MUST automatically divert to human review (`Needs Review` / Admin Approval Gate). Zero destructive commands (deletions, truncations) executable by autonomous models. Default mode is Shadow/Dry-Run (`DRY_RUN=True`).

## 2. Dual-Engine Verification Regime
* **Engine A (Fast Synthetic Suite):** Every component must have `pytest` unit tests with mocked boundaries and **>= 80% line/branch code coverage**.
* **Engine B (High-Fidelity Live Benchmark Suite):** Every application must feature `run_live_benchmark.py` and a curated `benchmark_catalog.json`.
* **The Quality Gate (`--quality-gate`):**
  * **100.0% Hard Safety Pass Rate** is mandatory (Zero safety breaches, zero loops, zero unauthorized actions).
  * **>= 80.0% Overall Functional Pass Rate** is mandatory.
  * Interactive HTML dashboard (`reports/live_benchmark.html`) and JSON summary (`reports/live_benchmark.json`) must be produced on every run.

## 3. Regulatory Compliance & Deep Telemetry
* **Tri-Format Logging:** All significant events must contemporaneously stream to `.jsonl` (Cloud/SIEM), `.csv` (Excel/Shop-floor), and `.html` (Visual audit dashboard).
* **Cryptographic Non-Repudiation:** SHA-256 hash chaining ($\text{Record Hash} = \text{SHA-256}(\text{Prev Hash} + \text{Timestamp} + \text{Payload})$) must be enforced on all audit trails to prevent retrospective tampering (FDA 21 CFR Part 11 / ISO 22000 compliance).

## 4. Zero-Trust Security & Credential Isolation
* **Zero Credentials in Git:** `.env`, secrets, private keys, tokens, and `*.db` files must NEVER be committed to Git.
* **Encryption at Rest:** Sensitive tokens, credentials, and biometric embeddings must be encrypted locally using **AES-256-GCM**.
* **Zero Inbound Attack Surface:** Edge machines must use outbound reverse tunnels / WebSocket hibernation (Cloudflare Workers with Durable Objects) instead of open inbound ports.

## 5. Code Hygiene & Universal Skills Library
* **Type Completeness:** 100% Python type annotations enforced under `mypy --strict`.
* **Universal Skills Library:** Reusable cognitive skills (`FaceRecognizerSkill`, `DisplayOCRSkill`, `ImageEnhancerSkill`, `GeofencingSkill`) must reside in `core_platform/app/skills/` and remain strictly decoupled from domain cartridges. Cartridges consume them via `ctx.get_skill()`.
* **Style:** Google-style docstrings, PEP 8 formatting via `black` / `ruff`, explicit error handling with causal chaining (`raise DomainError from err`).

## 6. Intellectual Property & Licensing
* All source files must contain the standard **Apache License 2.0** copyright notice:
  `Copyright 2026 Mahendra GURAV`

## 7. Protected Pet Projects Constraint
* The pet projects `D:\mailOrganizer`, `D:\WhatsappClientForMailOrganized`, and `D:\AI-ProjectManager` are read-only references. **NEVER modify or write to those directories under any circumstances.**
