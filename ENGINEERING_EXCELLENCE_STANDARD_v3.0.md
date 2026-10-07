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

## 7. Versioning & Governance

```
┌───────────────┬─────────────────┬─────────────────────────────────────────────────────────────┐
│ Standard      │ Release Date    │ Key Directives                                              │
├───────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ GEES v1.0     │ Jan 2026        │ 3-Layer Safety, Dual-Engine Verification, SHA-256 Audit     │
│ GEES v2.0     │ Jun 2026        │ Zero-Hardcoding, `mypy --strict`, Secret Scanner Guard      │
│ GEES v3.0     │ Oct 2026        │ Slim Microkernel, System Apps, Data Sovereignty, Synergy    │
└───────────────┴─────────────────┴─────────────────────────────────────────────────────────────┘
```

All software components, subagents, and future pull requests in this repository are strictly governed by **GEES v3.0**.
