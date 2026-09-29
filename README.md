# Release100: AI Multi-Application Platform Host

> **Copyright 2026 Mahendra GURAV | Licensed under the Apache License, Version 2.0**  
> **Governed strictly by the Global Engineering Excellence Standard (GEES v1.0)**

---

## 1. Executive Summary

**Release100** is an enterprise-grade, edge-deployable multi-application platform host that bridges cloud cognitive APIs with factory-floor, edge-isolated kiosk environments. It features a micro-kernel architecture with dynamically pluggable domain cartridges:

* **Temperature & Attendance Marker Cartridge (`apps.temperature_marker`)**: Fully automated duty check-ins, biometric facial verification, 7-segment digital display OCR temperature extraction, and HACCP compliance auditing for retail and industrial kiosk fleets.
* **Mail Organizer Cartridge (`apps.mail_organizer`)**: Executive email triage, AI-driven meeting scheduling, and automated Project Management task extraction into Jira and Linear.

---

## 2. Multi-Layered Safety Architecture (GEES v1.0)

Release100 operates under a strict three-layer defense-in-depth safety regime:

```
[ Incoming Payload ] ──> [ Layer 0: Deterministic Pre-Execution Gate ]
                                │ ├─ VIP Whitelist & Phone Verification
                                │ ├─ Sensor Physical Sanity Bounds (-20°C to +120°C)
                                │ └─ Haversine GPS Geofencing
                                ▼
                         [ Layer 1: Stochastic Reasoning Engine ]
                                │ ├─ Temperature Clamped to 0.0 – 0.2
                                │ └─ Pydantic Schema Constrained Outputs
                                ▼
                         [ Layer 2: Deterministic Post-Execution Gate ]
                                │ ├─ Biometric & OCR Confidence Gate (< 85% Diverts to Admin Review)
                                │ └─ Dry-Run / Non-Destructive Outbox Staging
                                ▼
                         [ Tri-Format Audit & Cryptographic Chaining ]
```

---

## 3. Core Capabilities & Architectural Components

### 3.1 Outbound Cloud Relay (Zero Inbound Attack Surface)
Industrial and retail kiosks run behind restrictive NATs and carrier-grade cellular firewalls where inbound port forwarding is impossible. Release100 features an outbound WebSocket client (`core_platform.app.ingress.relay_client`) that initiates persistent connections to an edge Cloudflare Worker relay:
* **Relay URI**: `wss://<relay_domain>/ws/{kiosk_id}`
* **Protocols**: Automatic exponential backoff reconnection, heartbeat keep-alive, frame parsing, and ingress dispatch.

### 3.2 1-Click Mobile Geolocation Portal (`/loc`)
When an operator's mobile device does not share native GPS coordinates via WhatsApp, the platform issues a secure one-time session link (`/loc?session=<token>`). When clicked in the mobile browser, HTML5 Geolocation obtains exact hardware coordinates, performs Haversine distance verification against the kiosk knowledge graph, and automatically clears the Layer 0 safety gate.

### 3.3 Live Diagnostics & Settings Console (`/settings`)
Interactive operational console providing:
* Real-time platform health and uptime monitoring.
* Outbox queue health and retry dispatcher stats.
* 1-Click automated configuration backup snapshot generation (`.env` and fleet topologies).
* Dynamic log level adjustment and skill telemetry verification.

### 3.4 Regulatory Non-Repudiation Audit Engine
* **Tri-Format Logging**: Contemporaneously writes operational records to `.jsonl` (SIEM/Cloud), `.csv` (Excel/Accounting), and `.html` (Visual audit dashboard).
* **Cryptographic Hash Chaining**: Every record is linked via $\text{SHA-256}(\text{Prev Hash} + \text{Timestamp} + \text{Payload})$ ensuring FDA 21 CFR Part 11 and ISO 22000 tamper evidence.

---

## 4. Verification & Quality Gates

The codebase is protected by the **GEES v1.0 Dual-Engine Verification Regime**:

### Engine A: Synthetic Unit Test Suite
```powershell
# Run full unit test suite (292 tests, 100% pass mandatory)
pytest tests/unit -v
```

### Engine B: High-Fidelity Live Benchmark Suite
```powershell
# Run official live benchmark quality gate
python run_live_benchmark.py --quality-gate
```
* **Mandatory Pass Rate**: **100.0% Hard Safety Pass Rate** and **$\ge 80.0\%$ Overall Functional Pass Rate**.
* **Reports Produced**: Interactive HTML (`reports/live_benchmark.html`) and structured JSON (`reports/live_benchmark.json`).

### Strict Type Completeness
```powershell
# Enforce zero type errors across all source files
mypy core_platform apps --ignore-missing-imports
```

---

## 5. Operations & Execution

### 5.1 CLI Dispatcher (`manage.py`)
```powershell
# Launch in Headless Console Mode
python manage.py run --mode headless --port 8002

# Launch in Desktop System Tray Mode
python manage.py run --mode tray --port 8002

# Run Local Health Diagnostics
python manage.py health

# Seed Sample Data for Testing
python manage.py seed

# Export Tamper-Evident Audit Package (ZIP) to Desktop
python manage.py export-audit
```

### 5.2 Key Web Endpoints

| Route | Method | Description |
| :--- | :--- | :--- |
| `/admin/apps/temperature-marker/fleet` | GET | Fleet Overview, Kiosk Status & Attendance Roster |
| `/settings` | GET | Live Diagnostics & Configuration Snapshot Console |
| `/loc` | GET / POST | Operator 1-Click Geolocation Verification Portal |
| `/health` | GET | Comprehensive JSON Health & Cloud Relay Telemetry |
| `/mcp/` | SSE / POST | Multi-app Model Context Protocol (MCP) Tool Host |

---

## 6. Deployment Packaging

Release100 supports both full platform distributions and hardened edge-only kiosks:
* **Kiosk Retail Edition**: Built via `deployment/packaging_windows/Kiosk_Retail_Edition.spec`. Contains solely the Temperature Marker cartridge, Core Platform, and Desktop Tray, strictly excluding Mail Organizer to minimize attack surface and binary footprint.
* **Installer Compilation**: Run `python deployment/packaging_windows/build_installer.py --edition kiosk`.
