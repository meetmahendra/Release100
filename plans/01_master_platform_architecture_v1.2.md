# MASTER PLATFORM ARCHITECTURE SPECIFICATION
## Enterprise Multi-Application Agentic Platform (`Release100`)

**Document ID:** `01_master_platform_architecture`  
**Document Version:** `v1.2.0`  
**Date:** September 13, 2026  
**Status:** DRAFT / UNDER REVIEW  
**Target Repository:** `D:\Release100`  
**Foundational Assets (Untouched Reference Sources):**  
- `D:\AI-ProjectManager` (Desktop Supervisor, Cloud Relay, Packaging Hub)
- `D:\WhatsappClientForMailOrganized` (WhatsApp Webhook Gateway & MCP Client)
- `D:\mailOrganizer` (LangGraph Engine, Telemetry, Safety Rules, SSE MCP Server)

---

## Document Revision History & Changelog

| Version | Date | Author | Description of Changes | Status |
| :--- | :--- | :--- | :--- | :--- |
| **v1.0.0** | 2026-09-13 | AI Architecture Team | Initial Master Platform Architecture: Ecosystem topology, microkernel & cartridges model, multi-customer deployment matrix, and directory layout. | Superseded |
| **v1.1.0** | 2026-09-13 | AI Architecture Team | Added JSON audit logs and multi-platform Linux/Cloud targets. *(Identified accidental omissions)* | Superseded |
| **v1.2.0** | 2026-09-13 | AI Architecture Team | **Comprehensive Alignment & Restoration**: <br>1. Re-anchored **FDA (21 CFR Part 11) & ISO 22000 compliance** as a core pillar of the multi-format audit engine.<br>2. Restored **`ProcessSupervisor` (Pluggable Process Supervisor & Health Monitor)** in global topology diagrams and lifecycle flow.<br>3. Restored `deployment/supervisor/` in directory structure.<br>4. Restored **Section 6: Phased Step-by-Step Delivery Roadmap** with Mermaid Gantt schedule.<br>5. Preserved all JSON/JSONL and multi-platform deployment specifications. | **Current** |

---

## 1. Executive Summary & Strategic Vision

`Release100` is a unified, enterprise-grade AI application hosting platform and distribution runtime. Rather than developing isolated, monolithic automation tools, `Release100` establishes a **decoupled, cross-platform modular ecosystem** where:

1. **The Core Orchestrator** acts as a channel-agnostic, multi-tenant host providing out-of-the-box (OOTB) infrastructure:
   - Universal multi-channel ingress (WhatsApp, Email, Web, Crawlers, MCP Server).
   - Pluggable LLM Provider Gateway (Cloud: Gemini/Claude/OpenAI; Local: Ollama/DeepSeek).
   - Unified Authentication & RBAC (Built-in credentials, Enterprise Google/Microsoft SSO, API keys).
   - 3-Layer Deterministic Safety & Confidence Guardrails.
   - **Regulatory Audit Compliance (FDA 21 CFR Part 11 & ISO 22000)**: Produces **Structured JSON/JSONL** for automated digital downstream ingestion, CSV for spreadsheet audits, and partitioned HTML dashboards for visual human inspection.
   - Native Model Context Protocol (MCP) Server host for external agents (Cursor, Claude Desktop).

2. **Domain Applications** plug in as isolated, hot-swappable packages ("cartridges"):
   - **App 1: `mail_organizer`**: Autonomous Gmail & Calendar triage, categorization, and meeting assistant.
   - **App 2: `temperature_marker`**: Computer vision operator face verification, 7-segment/LCD temperature readout extraction, HACCP food safety compliance, and ERP telemetry.
   - **Future Apps (`app_inventory`, `app_maintenance`, etc.)**: Seamlessly mountable without modifying core code.

3. **Multi-Target Distribution & Process Supervision**:
   - **Process Supervisor (`supervisor/`)**: Dynamic lifecycle manager that monitors listening ports, launches child services, tracks health metrics, and provides automated recovery.
   - **Windows Desktop / Kiosk**: Windows taskbar system tray control plane (`tray_app/`) + 1-click zero-Python `.exe` installer (PyInstaller + Inno Setup).
   - **Linux Edge / Factory Server**: Headless `systemd` background service or standalone Linux binary for factory edge servers (Ubuntu, Debian, Raspberry Pi).
   - **Cloud & Containers**: Production Docker containers (`Dockerfile` + `docker-compose.yaml`) deployable to cloud platforms (Render, Fly.io, AWS ECS/Fargate, Google Cloud Run, Azure, Kubernetes).
   - **Outbound WebSocket Cloud Relay**: Bypasses corporate NATs, firewalls, and port-forwarding across all environments.

4. **100% Isolation of Existing Pet Projects**:
   - `D:\AI-ProjectManager`, `D:\WhatsappClientForMailOrganized`, and `D:\mailOrganizer` remain completely untouched.
   - Proven, battle-tested components are re-architected and consolidated cleanly inside `D:\Release100`.

---

## 2. Global Ecosystem Topology

```mermaid
graph TD
    subgraph "Layer 1: Multi-Platform Distribution & Supervision"
        TrayApp[Windows System Tray Controller]
        LinuxDaemon[Linux systemd Daemon Service]
        CloudContainer[Cloud Container Runner]
        
        ProcessSupervisor[Pluggable Process Supervisor & Health Monitor]
        CloudRelay[Cloud Relay Server - Outbound WS NAT Bypass]
        WinInstaller[Zero-Python Windows .exe Installer]
    end

    subgraph "Layer 2: Platform Ingress & Ingress Adapters"
        WA_Adapter[WhatsApp Gateway Adapter]
        Email_Adapter[IMAP / Graph API Email Adapter]
        Web_Adapter[Web Dashboard & REST API]
        MCP_Server[Native MCP Server Endpoint for Cursor/Claude]
        Poller_Adapter[Autonomous Background Pollers & Crawlers]
    end

    subgraph "Layer 3: Orchestrator Core (The Platform Engine)"
        AuthEngine[Adaptive Auth: Built-in User/Pass + Google/MS SSO + API Keys]
        RBACFilter[RBAC Entitlement & User Permission Filter]
        SemanticRouter[Multi-Modal LLM Supervisor / Intent Router]
        LLMManager[Pluggable LLM Manager - Cloud & Local Ollama]
        SafetyEngine[3-Layer Deterministic Safety & Confidence Guardrails]
        
        subgraph "Universal Audit & Telemetry Suite (FDA 21 CFR Part 11 / ISO 22000)"
            AuditJSON[Structured JSON / JSONL - Digital & Machine Consumption]
            AuditCSV[Standard CSV Logs - Spreadsheet Audits]
            AuditHTML[Partitioned HTML Visual Dashboard]
        end
        
        ExecutionModes[Execution Engine: Shadow / Assistive / Autonomous]
        AppRegistry[Dynamic Application Registry & Plugin Loader]
    end

    subgraph "Layer 4: Plugged-In Domain Applications (Cartridges)"
        subgraph "Application: Food Temperature & Attendance"
            TempGraph[LangGraph State Graph]
            VisionEngine[InsightFace ID + 7-Segment/LCD Vision OCR]
            FoodKG[Knowledge Graph: Shifts, Machines & HACCP Rules]
            ERPMCP[ERP MCP Server & REST Adapter]
            TempWizard[Progressive Stepper Admin Wizard]
        end

        subgraph "Application: Email & Calendar Organizer"
            MailGraph[LangGraph Triage State Graph]
            GmailCalendar[Gmail & Google Calendar Connectors]
            PMQueue[Human-in-the-Loop PM Task Queue]
            MailAdminUI[Mail Accounts & Taxonomy Rules UI]
        end
    end

    TrayApp --> ProcessSupervisor
    LinuxDaemon --> ProcessSupervisor
    CloudContainer --> ProcessSupervisor
    CloudRelay -->|Outbound WS Stream| WA_Adapter
    
    ProcessSupervisor -->|Monitors & Launches| Layer2
    
    WA_Adapter & Email_Adapter & Web_Adapter & MCP_Server & Poller_Adapter --> AuthEngine
    
    AuthEngine --> RBACFilter --> SemanticRouter
    SemanticRouter --> LLMManager
    SemanticRouter --> SafetyEngine
    SafetyEngine --> ExecutionModes
    
    ExecutionModes --> AppRegistry
    ExecutionModes --> AuditJSON & AuditCSV & AuditHTML
    AppRegistry --> TempGraph
    AppRegistry --> MailGraph
```

---

## 3. FDA (21 CFR Part 11) & ISO 22000 Compliant Audit Engine

For food processing and pharmaceutical manufacturing, compliance regulations require strict electronic records integrity, non-repudiation, and traceability.

### Tri-Format Output Strategy
Every operational action, operator verification, HACCP boundary evaluation, and ERP transmission produces three synchronized audit artifacts:

1. **Structured JSON / JSONL (Digital Machine Stream)**:
   - Appended atomically to `logs/audit_partitions/YYYY-MM-DD.jsonl`.
   - Directly ingested by external SIEM, ERP, or quality analytics pipelines via `GET /api/v1/audit/logs?format=json`.
2. **Tabular CSV (Spreadsheet / QA Manager Audits)**:
   - Flattened, timestamped rows for quick filtering in Excel by plant auditors.
3. **Partitioned HTML Dashboard (Visual Human Inspection)**:
   - Standalone browser-friendly visual reports (`audit_logs/html/index.html`) borrowable directly from `mailOrganizer`.

```json
{
  "compliance_standard": "FDA 21 CFR Part 11 / ISO 22000",
  "record_id": "aud_20260913_9a8b7c6d",
  "timestamp_iso": "2026-09-13T08:15:22.104Z",
  "tenant_id": "plant_chicago_01",
  "app_id": "temperature_marker",
  "channel": "whatsapp",
  "execution_mode": "AUTONOMOUS",
  "principal": {
    "sender_id": "+15550198234",
    "employee_id": "EMP-1042",
    "employee_name": "Ramesh Kumar",
    "role": "operator"
  },
  "telemetry": {
    "pipeline_latency_ms": 1420,
    "model_used": "gemini-2.5-flash",
    "prompt_tokens": 1250,
    "completion_tokens": 115,
    "traversed_nodes": ["ingest", "face_id", "kg_infer", "temp_ocr", "haccp_check", "erp_sync"]
  },
  "decision_payload": {
    "face_verified": true,
    "face_confidence": 0.94,
    "inferred_machine_id": "PASTEURIZER-02",
    "active_shift": "SHIFT_A_MORNING",
    "extracted_temperature": 74.5,
    "temperature_unit": "C",
    "display_type": "7_segment_led",
    "ocr_confidence": 0.96,
    "haccp_evaluation": {
      "status": "NORMAL",
      "safe_min": 72.0,
      "safe_max": 78.0,
      "is_compliant": true
    }
  },
  "erp_integration": {
    "sync_attempted": true,
    "protocol": "mcp",
    "transaction_id": "ERP_TXN_98214",
    "status": "COMMITTED"
  },
  "security_integrity": {
    "image_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "signature_verified": true
  }
}
```

---

## 4. Multi-Platform Deployment Architecture

```mermaid
graph LR
    CodeBase[Single Release100 Codebase] --> TargetWin[Windows Package Target]
    CodeBase --> TargetLinux[Linux Package Target]
    CodeBase --> TargetCloud[Cloud Container Target]

    TargetWin --> WinArtifacts["output/
    ├── Setup.exe (Inno Setup)
    ├── Portable.zip
    └── Tray App (pystray)"]

    TargetLinux --> LinuxArtifacts["linux/
    ├── systemd/release100.service
    ├── install.sh
    └── Headless CLI Daemon"]

    TargetCloud --> CloudArtifacts["deploy/
    ├── Dockerfile
    ├── docker-compose.yml
    └── Helm / K8s Manifests"]
```

| Deployment Target | Primary Use Case | Runtime Mechanism | Networking & Ingress |
| :--- | :--- | :--- | :--- |
| **Windows Desktop / Kiosk** | Factory supervisor PC, shop-floor Windows kiosk terminal, office managers. | PyInstaller standalone bundle + Inno Setup installer. Sits in taskbar tray via `pystray`. Process supervised by `supervisor/`. | Outbound WebSocket Cloud Relay connects to cloud webhook receiver without local firewall changes. |
| **Linux Edge Server** | Factory server rack, industrial fanless box (Ubuntu Server), edge IoT gateway. | Python 3.10+ virtualenv supervised by `systemd` daemon (`release100.service`) and internal `supervisor/`. | Direct Nginx reverse proxy with SSL or Cloud Relay daemon. |
| **Cloud (Docker / Cloud Run)** | Scalable SaaS multi-tenant hosting, enterprise cloud (AWS, GCP, Render, Fly.io). | Multi-stage Docker container (`python:3.11-slim`) running supervisor entrypoint. | Managed cloud HTTPS endpoint receiving direct Meta webhooks and REST traffic. |

---

## 5. Comprehensive Directory Layout (`D:\Release100`)

```text
D:\Release100/
├── plans/                                 # Versioned architecture & implementation plans
│   ├── 01_master_platform_architecture_v1.0.md
│   ├── 01_master_platform_architecture_v1.1.md
│   ├── 01_master_platform_architecture_v1.2.md  <-- CURRENT MASTER SPECIFICATION
│   ├── 02_orchestrator_core_v1.0.md
│   ├── 03_app_temperature_marker_v1.0.md
│   ├── 04_app_mail_organizer_v1.0.md
│   └── 05_deployment_and_packaging_hub_v1.0.md
│
├── core_platform/                         # The Core Orchestrator & Platform Services
│   ├── app/
│   │   ├── config/                        # Pydantic platform settings (master config)
│   │   ├── auth/                          # Built-in User/Pass, SSO (Google/MS), API Key manager
│   │   ├── rbac/                          # User roles, app entitlements & permissions
│   │   ├── ingress/                       # Normalized Inbound/Outbound Message Envelopes
│   │   │   ├── whatsapp_adapter.py        # Meta Webhook & Graph Media Downloader
│   │   │   ├── email_adapter.py           # IMAP / Graph API listener
│   │   │   ├── web_adapter.py             # REST / WebSocket endpoints
│   │   │   └── poller_adapter.py          # Scheduled daemon pollers
│   │   ├── routing/                       # Multi-Modal LLM Supervisor & Semantic Router
│   │   ├── llm/                           # Unified LLM Gateway (Gemini, Claude, OpenAI, Ollama)
│   │   ├── safety/                        # 3-Layer deterministic pre-check & confidence guardrails
│   │   ├── telemetry/                     # Deep telemetry, JSON/JSONL, CSV & HTML reports
│   │   │   ├── audit_schema.py            # Pydantic schemas for JSON & CSV audit records
│   │   │   ├── jsonl_writer.py            # High-performance async JSONL streaming logger
│   │   │   ├── csv_writer.py              # Flattened tabular CSV exporter
│   │   │   └── html_generator.py          # Visual partitioned HTML reports
│   │   ├── mcp_server/                    # Native SSE MCP Server exposing platform tools to external AI
│   │   ├── admin_shell/                   # FastAPI Web Admin Shell (dynamic nav & theme)
│   │   └── plugin_engine/                 # Dynamic Application Loader & Lifecycle Manager
│   ├── main.py                            # Platform startup bootstrap
│   └── requirements.txt
│
├── apps/                                  # Pluggable Domain Applications ("Cartridges")
│   │
│   ├── temperature_marker/                # App: Food Processing Temperature & Attendance
│   │   ├── plugin.py                      # BaseApplication implementation manifest
│   │   ├── graph/                         # LangGraph workflow (Face ID -> OCR -> HACCP -> ERP)
│   │   ├── skills/                        # InsightFace matcher, 7-Segment & LCD Vision OCR
│   │   ├── knowledge_graph/               # Shift roster inference & HACCP safety rules
│   │   ├── erp/                           # ERP MCP Client & REST connectors
│   │   ├── ui/                            # Progressive Stepper Admin Wizard & Machine Registry
│   │   └── database/                      # SQLAlchemy models for records & audit trails
│   │
│   └── mail_organizer/                    # App: Email & Calendar Organizer (Rearchitected)
│       ├── plugin.py                      # BaseApplication implementation manifest
│       ├── graph/                         # LangGraph triage & drafting state machine
│       ├── connectors/                    # Gmail API & Google Calendar integration
│       ├── pm_tasks/                      # Task queue & Jira/Linear export adapters
│       └── ui/                            # Mail accounts & classification rules dashboard
│
├── deployment/                            # Multi-Platform Distribution & Supervision Hub
│   ├── supervisor/                        # Dynamic process supervisor & port health monitor (Borrowed & elevated)
│   ├── desktop_tray/                      # Windows taskbar system tray controller
│   ├── packaging_windows/                 # PyInstaller specs + Inno Setup .exe build scripts
│   ├── linux_systemd/                     # release100.service unit file & install.sh
│   ├── docker/                            # Dockerfile, docker-compose.yml & entrypoint scripts
│   └── cloud_relay/                       # Standalone WebSocket Cloud Relay service (Render/Fly.io)
│
└── config/
    ├── platform.env.example               # Master configuration template
    └── factory_machines.example.json      # Sample machine registry & HACCP definitions
```

---

## 6. Phased Step-by-Step Delivery Roadmap

To maintain total execution control and avoid cognitive overload, the system development is partitioned into **5 sequential phases**:

```mermaid
gantt
    title Release100 Implementation Master Schedule
    dateFormat  YYYY-MM-DD
    section Phase 1: Architecture & Master Plans
    Author & Review 5 Architectural Plans  :done, p1, 2026-09-13, 2d
    section Phase 2: Core Platform Engine
    Ingress, Auth, Telemetry, Safety & LLM :p2, after p1, 5d
    Native MCP Server & Admin Web Shell    :p3, after p2, 4d
    section Phase 3: Temperature Marker App
    Vision OCR, Face ID, Knowledge Graph   :p4, after p3, 5d
    HACCP Wizard & ERP MCP Adapter         :p5, after p4, 4d
    section Phase 4: Mail Organizer Rearch
    Adapt mailOrganizer into App Cartridge :p6, after p5, 4d
    section Phase 5: Desktop & Packaging Hub
    Process Supervisor, Tray & Inno Setup  :p7, after p6, 4d
    Linux systemd & Docker Cloud Targets   :p8, after p7, 3d
```

### Milestone Deliverables:
* **Milestone 1 (Plans Complete)**: All 5 modular architectural plans finalized in `D:\Release100\plans\`.
* **Milestone 2 (Core Engine Operational)**: Ingress, Auth, Multi-Modal Router, 3-Layer Safety, JSON/CSV/HTML Telemetry, and Native MCP Server running.
* **Milestone 3 (Temperature Marker Live)**: Face verification + 7-segment/LCD OCR + Knowledge Graph shift lookup + ERP MCP syncing.
* **Milestone 4 (Mail Organizer Re-mounted)**: Mail Organizer plugged in as an independent cartridge with shared telemetry.
* **Milestone 5 (Multi-Platform Distribution)**: Windows `.exe` installer generated, Linux `systemd` scripts verified, and Docker Cloud containers passing end-to-end regression tests.

---

## 7. Next Steps

With **`01_master_platform_architecture_v1.2.md`** approved and fully restored, we proceed directly to **Plan 2: Core Orchestrator & Platform Services Specification** (`02_orchestrator_core_v1.0.md`).
