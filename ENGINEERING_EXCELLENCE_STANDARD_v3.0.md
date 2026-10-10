# Global Engineering Excellence Standard (GEES) v3.0
## Decoupled Microkernel, System Applications & Unified Platform Synergy Framework for Mission-Critical, Multi-Cloud & Multi-Tenant Systems

```
Document Reference : EES-STD-2026-V3.0
Status             : Approved Organizational & Open-Source Standard
Author             : Mahendra GURAV
License            : Apache License, Version 2.0
Scope              : Universal (Microkernel, System Apps, Domain Cartridges, Kiosk Systems & Agentic Fabrics)
Supercedes         : GEES v2.0 (EES-STD-2026-V2.0)
```

---

## 1. Executive Mandate & Architectural Evolution

As modular platforms scale across heterogeneous environments (on-premise edge kiosks, cloud Kubernetes clusters, bare-metal servers, and dynamic reverse proxies), a monolithic core creates severe architectural fragility:
1. **Coupling Monoliths:** Tightly coupling routing, ingress host inspection, tenant resolution, authentication, permissions, and admin UI views directly inside the core platform kernel.
2. **Hidden Spaghetti Imports:** Splitting folders superficially without hard abstract boundaries, leading to cyclic cross-module imports and shared schema coupling.
3. **Domain & Cloud Fragility:** Hardcoding domain names, tunnel prefixes, or magic role constants, breaking portability when deployed across different cloud providers or custom domains.
4. **Siloed Fragmentation:** Over-isolating modules into disconnected fragments without visual, behavioral, or cognitive synergy.

The **Global Engineering Excellence Standard (GEES v3.0)** establishes the architectural foundation for a **True Slim Microkernel** surrounded by **Autonomous System Applications**, **Pluggable Domain Cartridges**, and a **Unified Platform Synergy Fabric**.

---

## 2. The 4 Orthogonal Planes of Responsibility

The platform is strictly segregated across four orthogonal architectural planes:

```
══════════════════════════════════════════════════════════════════════════════════════════════════════
PLANE 1: INGRESS & CONTEXT PLANE (Untrusted Edge / Gateway)
  • Responsibilities: TLS termination, RFC 1035 host normalization, Raw RequestContext synthesis.
  • Strict Isolation: Zero database access, zero business logic, zero credential verification.
══════════════════════════════════════════════════════════════════════════════════════════════════════
                                              │
                                              ▼ (Passes RequestContext)
══════════════════════════════════════════════════════════════════════════════════════════════════════
PLANE 2: THE SLIM MICROKERNEL ENGINE (The Runtime Substrate)
  • Service Registry (Inversion of Control / DI): Apps publish & consume abstract Interfaces (Protocols).
  • Event Bus & Outbox Broker: Asynchronous, decoupled cross-app domain event messaging.
  • Polyglot DB Substrate: Provides scoped connection handles; owns ZERO domain tables.
  • AST Boundary Enforcer: Static and runtime guards preventing cross-app concrete imports.
══════════════════════════════════════════════════════════════════════════════════════════════════════
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    ▼                                                   ▼
═══════════════════════════════════════════════   ════════════════════════════════════════════════════
PLANE 3: SYSTEM CONTROL & GOVERNANCE APPS         PLANE 4: DOMAIN WORKLOAD CARTRIDGES
(Platform Level - Non-Configurable Services)      (Tenant Level - Pluggable Business Apps)
                                                  
 ┌─────────────────────────────────────────────┐   ┌────────────────────────────────────────────────┐
 │ 1. Tenancy Provider (`ITenantService`)      │   │ • AI Mail & Calendar Cartridge                 │
 │    • Owns: `tenants`, `tenant_domains`      │   │ • Industrial Temperature Marker Cartridge      │
 ├─────────────────────────────────────────────┤   └────────────────────────────────────────────────┘
 │ 2. IAM Provider (`IIdentityService`)        │                         ▲
 │    • Owns: `users`, `credentials`, `tokens` │                         │
 ├─────────────────────────────────────────────┤                         │ (Access ONLY via AppContext SDK)
 │ 3. Policy Engine (`IAuthorizationPolicy`)   │                         │
 │    • Owns: `roles`, `permissions`, `scopes` │                         │
 ├─────────────────────────────────────────────┤                         │
 │ 4. Entitlements (`IEntitlementService`)     │                         │
 │    • Owns: `tiers`, `features`, `quotas`    │                         │
 ├─────────────────────────────────────────────┤                         │
 │ 5. Admin Shell (`IAdminShellService`)       │                         │
 │    • Owns: Master Layout, Nav, Design Tokens│                         │
 ├─────────────────────────────────────────────┤                         │
 │ 6. Ops Control Plane (`IOpsControlPlane`)   │                         │
 │    • Owns: Multi-Tenant & Audit Inspector   │                         │
 └─────────────────────────────────────────────┘                         │
                    │                                                    │
                    └────────────────────────────────────────────────────┘
                      (Inter-app communication strictly via Protocols / Events)
```

---

## 3. System Applications (Core Modules) vs. Domain Cartridges

To guarantee full separation of concern, responsibility, and maintainability:

### 3.1 The Slim Microkernel (`core_kernel/`)
The microkernel contains **zero** domain concepts, zero business logic, zero UI HTML/CSS, and zero hardcoded credentials. It provides strictly:
1. **Topological Bootstrapping:** Discovers and boots apps in deterministic dependency order.
2. **Service Locator / DI:** Inversion-of-Control container registering abstract Python `Protocol` interfaces.
3. **Database Connection Pool:** Scoped connection managers and raw session lifecycle.
4. **Event Bus & Outbox Broker:** Decoupled in-memory / persistent domain event dispatch.
5. **Contract Definitions:** `BaseSystemApp`, `BaseCartridge`, and `SkillInterface`.

### 3.2 System Applications (`system_apps/`)
System Applications are **always required, non-configurable** platform subsystems. Each system app is a self-contained black box:
* **`system_apps/tenancy`:** Ingress host resolution, CNAME registry, RFC 1035 base-domain offset resolution, and `TenantContext` middleware.
* **`system_apps/iam`:** User directory, password hashing (PBKDF2/Argon2), JWT token generation/validation, and Tenant Memberships.
* **`system_apps/rbac`:** Role-based access control, granular scopes, and capability policy decision point (PDP).
* **`system_apps/entitlements`:** Feature flagging, tier management, and usage quota enforcement.
* **`system_apps/admin_shell`:** Central workspace UI, authentication screens, navigation bar, command palette (`Ctrl+K`), and Jinja2 UI macros.
* **`system_apps/ops_control`:** Super-Admin control plane, multi-tenant provisioning, and SHA-256 audit hash chain verifier.
* **`system_apps/ingress`:** External communication webhooks (WhatsApp Cloud API, OAuth Magic Links, Edge Sync Relays).

### 3.3 Domain Cartridges (`apps/`)
Domain Cartridges are **pluggable, tenant-scoped business applications** (e.g. `mail_organizer`, `temperature_marker`). Cartridges consume platform capabilities exclusively through an injected, immutable `AppContext` SDK.

---

## 4. Architectural Axioms of True Separation

### 4.1 Data Sovereignty per Application
* Every application (System App or Cartridge) **strictly owns its database schema and tables**.
* **Zero Cross-App SQL:** No application may execute SQL queries against another application's tables or declare foreign keys pointing to another application's tables.
* If App A needs data owned by App B, it must consume App B's published `Protocol` service contract or listen to App B's domain events.

### 4.2 Protocol / Contract-Based Inversion of Control
* Concrete Python classes must never be imported across app boundaries.
* Applications communicate exclusively through abstract Python protocols (`typing.Protocol`) registered in the Kernel Service Registry.

```python
# Contract declared in Kernel Interface layer
class IIdentityService(Protocol):
    def authenticate(self, credentials: AuthCredentials) -> AuthResultDTO: ...
    def get_user_profile(self, user_id: str) -> UserProfileDTO: ...

# Consuming App resolves the interface dynamically
identity_service = ctx.resolve(IIdentityService)
```

### 4.3 Automated AST Boundary Enforcement
* The continuous test suite executes an AST-level linter (`test_architectural_boundaries.py`) that fails the build if:
  1. Any `apps/*` module imports from another `apps/*` module.
  2. Any `system_apps/*` module imports internal concrete classes from another `system_apps/*` module.
  3. The `core_kernel` imports any module from `system_apps/*` or `apps/*`.

---

## 5. Platform Synergy & The Amalgamation Fabric

True engineering excellence balances strict modular isolation with a **unified, cohesive platform experience**.

### 5.1 Composable UI Shell & Slot Architecture
* The **Admin Shell** provides the master visual frame (Responsive Sidebar, Top Navigation, Tenant Switcher, Profile Menu, and Global Quick Actions).
* Applications dynamically register navigation items, summary dashboard tiles, and settings panels via standard UI extension hooks.
* **Unified Design Tokens:** All templates consume standard Jinja2 UI macros (`render_status_badge`, `render_data_table`, `render_form_input`, `render_card_header`) to guarantee pixel-perfect visual harmony across every screen.

### 5.2 Collaborative Service & Event Fabric
* Applications publish **Consumable Capabilities** to the Service Registry.
* Applications communicate across domains using asynchronous **Domain Events** over the Kernel Event Bus:
  * Example: `TemperatureMarker` emits `ChillerAnomalyDetectedEvent`.
  * `MailOrganizer` consumes the event and auto-drafts an urgent briefing for the shift supervisor.
  * **Result:** Emergent platform intelligence with **zero direct code coupling**.

### 5.3 Shared Cognitive & Audit Substrate
* All applications share the platform's stateless cognitive skills library (`DisplayOCRSkill`, `FaceRecognizerSkill`, `IntentClassifierSkill`, `LLMProviderRegistry`).
* All critical events from all applications stream into a unified, cryptographically non-repudiable SHA-256 hash-chained audit ledger.

---

## 6. Cloud & Domain Portability (Any Cloud / Any Domain)

The platform must operate identically whether deployed on **AWS, GCP, Azure, Bare-Metal, Localhost, or dynamic reverse proxy tunnels (Ngrok, Cloudflare, Tailscale)**.

### 6.1 Dynamic Ingress Resolution
1. **Configured Base Domain (`BASE_DOMAIN`):** If configured (e.g. `release100.com`), incoming subdomains are parsed relative to the base domain (`{tenant_slug}.release100.com` $\rightarrow$ `tenant_slug`).
2. **Database CNAME Registry (`tenant_domains` table):** Custom domain mappings (e.g. `kiosk.acmecorp.com` $\rightarrow$ `acme_tenant`) are resolved dynamically from database records.
3. **Origin / Relay Ingress:** When no subdomain matches `BASE_DOMAIN` and no custom CNAME is found, the host is treated as a direct platform gateway.
4. **Zero Hardcoded Domain Lists:** No hardcoded lists of tunnel domains or platform prefixes exist in procedural Python code.

### 6.2 Pure Capability-Based Authorization (PDP / PEP)
* Route handlers never evaluate raw hostnames or literal usernames.
* Access control is evaluated solely by the Policy Decision Point (PDP) checking cryptographic tokens for required capabilities (e.g. `platform:manage_tenants`, `mail:triage`).

---

## 7. Anti-Regression & Zero-False-Success Test Engineering Directives (GEES v3.1)

To guarantee that tests verify true operational reliability rather than generating superficial coverage metrics:

### 7.1 Absolute Ban on Shallow "Status 200" Smoke Tests
* Asserting `status_code == 200` alone is **strictly prohibited** as the sole assertion for any page or route containing interactive user workflows.
* Every UI route test **MUST assert Actionable DOM Invariants**:
  1. The expected `<form>` is physically present with exact `action` and `method` attributes.
  2. Expected interactive controls (`<input>`, `<select>`, `<textarea>`, `<button>`) exist with correct `name` and `type` attributes.
  3. The submit `<button type="submit">` is present and active for authorized roles.
  4. All user-facing strings are resolved from the localization catalog (`t(...)`) with zero raw un-localized text.

### 7.2 Mandatory Clean-Slate Round-Trip Mutation Testing (Day-1 Invariant)
* All stateful features must be tested starting from the **exact default state of a brand-new tenant on Day 1** (pre-configured static fixture shortcuts are prohibited for workflow validation).
* Tests must execute the complete state transition loop:
  $$\text{GET /page (default state)} \longrightarrow \text{POST /action (mutate data)} \longrightarrow \text{GET /page (assert updated persisted UI state)}$$
* Both state transitions must be verified:
  - Transitioning from State A to State B (e.g. `PLATFORM_MANAGED` $\rightarrow$ `CUSTOMER_BYOK` with custom keys).
  - Transitioning from State B back to State A (e.g. `CUSTOMER_BYOK` $\rightarrow$ `PLATFORM_MANAGED`).

### 7.3 Anti-Caching & Session Invalidation Invariant
* All authenticated UI routes must assert the presence of anti-caching response headers:
  `Cache-Control: no-store, no-cache, must-revalidate, max-age=0, private`, `Pragma: no-cache`, `Expires: 0`.
* All unauthenticated 401/403 redirect responses to `/admin/login` must assert `Clear-Site-Data: "cache"`.
* All client-side JavaScript must contain defensive `typeof` checks (`typeof window.addEventListener === "function"`) so that headless testing runtimes never crash.

---

## 8. The 6 Mandatory End-to-End Persona & Cartridge Journey Regimes

Every release, pull request, and quality gate must execute these 6 full-lifecycle End-to-End Journey Suites:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  THE 6 MANDATORY E2E JOURNEY REGIMES                                     │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. E2E-1: Multi-Tenant Onboarding & Key Vault Journey (`test_e2e_tenant_admin_onboarding_and_vault.py`)   │
│    • SuperAdmin provisions tenant -> Tenant Admin logs in -> Configures Brand & Timezone -> Toggles      │
│      between Platform-Managed and Customer BYOK Vault -> Verifies AES-256-GCM encryption -> Invites User │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. E2E-2: Mail Organizer Full Ingestion & PM Loop (`test_e2e_mail_organizer_workflow.py`)                │
│    • Inbound email arrives -> Tenant context resolved -> AI intent triage & rule match -> Token cost    │
│      ledger record created -> Lands in PM Queue -> Human approves & dispatches -> Outbound sent          │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. E2E-3: Temperature Kiosk Vision & Anomaly Loop (`test_e2e_temperature_marker_kiosk.py`)              │
│    • Kiosk edge payload -> Haversine GPS geofence check -> Face & Display OCR skills execute -> Fever    │
│      anomaly flagged (NEEDS_REVIEW) -> Supervisor approves override in UI -> WhatsApp alert -> SHA-256   │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 4. E2E-4: Cross-App Event Synergy Choreography (`test_e2e_cross_cartridge_synergy.py`)                   │
│    • Temperature Marker detects safety breach -> Publishes event to Kernel Event Bus -> Mail Organizer   │
│      consumes event & auto-drafts supervisor briefing -> Asserts 100% zero code imports between apps     │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 5. E2E-5: Multi-Tenant Concurrent Key Routing (`test_e2e_concurrent_multi_tenant_key_routing.py`)       │
│    • Simultaneous requests from BYOK tenant (custom key) & Platform tenant (shared key) -> Resolves      │
│      respective keys dynamically -> Financial liability correctly attributed -> Zero key cross-talk     │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 6. E2E-6: Clean-Slate Zero-Entity Boot & Resilience (`test_e2e_clean_slate_boot_and_resilience.py`)      │
│    • Clean database with 0 tenants, 0 users, 0 kiosks -> Boots cleanly with 0 unhandled 500 errors ->   │
│      Bootstrap wizard initializes platform successfully                                                 │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Modular Test Hygiene & ODT Elimination Rules

### 9.1 Absolute Ban on "Grab-Bag" Coverage Booster Test Files
* A single test file must never import unrelated modules across domain boundaries (e.g. mixing `ImageEnhancerSkill`, `CloudRelayClient`, `LLMCostTracker`, and `MailDatabaseService` in one file).
* All tests must reside strictly within their corresponding architectural domain suite.

### 9.2 Absolute Ban on Module-Level State & Singleton TestClients
* Test files must never instantiate module-level singletons (`client = TestClient(app)`) or mutate global cookies/headers at module scope.
* All test clients, database handles, and temporary files must be strictly scoped within deterministic pytest fixtures (`tmp_path`, `client`).

### 9.3 Absolute Ban on Silent Skips
* Constructing test fixtures with `try ... except: pytest.skip(...)` is strictly forbidden. Any import failure or dependency break must fail the test suite explicitly.

### 9.4 Domain-Driven Test File Naming
* Test file names must reflect architectural capabilities (e.g. `test_rate_limiter.py`, `test_identity_registry.py`), never temporary historical sprint phases (`test_phase2_fixes.py`).

---

## 10. Inviolable Pre-Flight Quality Gate (`scripts/verify_all.py`)

No developer or agent may declare a task complete, propose changes, or commit code without executing the unified pre-flight quality gate and attaching a **100% Green Pass Report**:

```bash
python scripts/verify_all.py --quality-gate
```

**The 7 Inviolable Checks Executed:**
1. **`[AST-GUARD]`** AST Architectural Boundaries: Zero cross-app concrete imports, zero domain leaks in microkernel.
2. **`[TYPE-GUARD]`** Static Type Discipline: 100% `mypy --strict` passing across 100% of source files.
3. **`[UI-GUARD]`** UI & I18n Parity: 100% translation key resolution, zero hardcoded untranslated strings.
4. **`[NODE-GUARD]`** Headless JavaScript Compatibility: `ui.js` executes without DOM errors under Node.js.
5. **`[SECRET-GUARD]`** Zero-Secret Leak Guard: 100% clean scan against live credential patterns.
6. **`[MANIFEST-GUARD]`** Packaging & Manifest Integrity: All packages, wheel assets, and Jinja2 templates declared in `pyproject.toml`.
7. **`[REGRESSION-GUARD]`** Fast Synthetic Unit & E2E Journey Suite: 100% pass rate on all unit tests and the 6 Mandatory End-to-End Journeys.

---

## 11. Versioning & Governance

```
┌───────────────┬─────────────────┬─────────────────────────────────────────────────────────────┐
│ Standard      │ Release Date    │ Key Directives                                              │
├───────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ GEES v1.0     │ Jan 2026        │ 3-Layer Safety, Dual-Engine Verification, SHA-256 Audit     │
│ GEES v2.0     │ Jun 2026        │ Zero-Hardcoding, `mypy --strict`, Secret Scanner Guard      │
│ GEES v3.0     │ Oct 2026        │ Slim Microkernel, System Apps, Data Sovereignty, Synergy    │
│ GEES v3.1     │ Oct 2026        │ Zero-False-Success Directives, 6 E2E Journeys, Verify-All   │
└───────────────┴─────────────────┴─────────────────────────────────────────────────────────────┘
```

All software components, subagents, and future pull requests in this repository are strictly governed by **GEES v3.1**.
