<!--
Copyright 2026 Mahendra GURAV

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Release100 Platform — Operations & Administration Manual

> **Document Version:** 1.3.0  
> **Standard:** Global Engineering Excellence Standard (GEES v1.0)  
> **Author:** Platform Engineering Team  
> **Copyright:** © 2026 Mahendra GURAV  

---

## 1. System Architecture & Overview

**Release100** is an enterprise-grade multi-application cognitive kiosk platform engineered for rugged factory floors, cold-chain distribution centers, and distributed management hubs. It hosts modular domain cartridges (`temperature_marker`, `mail_organizer`) atop a resilient core platform featuring deterministic safety gates, outbound-only cloud relay connectivity, SHA-256 cryptographic audit chaining, and multi-format telemetry.

```
                  ┌────────────────────────────────────────┐
                  │          WhatsApp Cloud API            │
                  └──────────────────┬─────────────────────┘
                                     │ Webhook POST
                                     ▼
                  ┌────────────────────────────────────────┐
                  │    Edge Cloud Relay (Worker/Render)    │
                  │   wss://relay.domain.com/ws/{kiosk_id} │
                  └──────────────────┬─────────────────────┘
                                     │ Outbound Persistent WS
                                     │ (Zero inbound firewall ports)
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ KIOSK WORKSTATION (Windows 10/11 VM or Physical Device)                    │
│                                                                            │
│  ┌───────────────────────┐         ┌────────────────────────────────────┐  │
│  │ Process Supervisor     │ ──────> │ Platform Host (FastAPI :8000)       │  │
│  │ System Tray App       │ Heart-  │  - Health API (/health)            │  │
│  │ Watchdog Auto-Restart │ beat    │  - Cloud Relay Client              │  │
│  └───────────────────────┘         │  - Multi-App Dispatcher            │  │
│                                     └───────┬────────────────────┬───────┘  │
│                                             │                    │          │
│                       ┌─────────────────────┴──┐    ┌────────────┴─────┐    │
│                       │ temperature_marker     │    │ mail_organizer   │    │
│                       │  - Display OCR Skill   │    │  - LangGraph     │    │
│                       │  - Face Recognizer     │    │    State Graph   │    │
│                       │  - GPS Geofencing      │    │  - PM Queue Sync │    │
│                       └────────────────────────┘    └──────────────────┘    │
│                                             │                    │          │
│                       ┌─────────────────────┴────────────────────┴───────┐  │
│                       │ Cryptographic Audit Engine (SHA-256 Chain)       │  │
│                       │ Streams: .jsonl (SIEM) | .csv | .html Dashboard  │  │
│                       └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Hardware & Operating Environment Prerequisites

| Component | Specification |
| :--- | :--- |
| **Operating System** | Windows 10 (Build 19041+) or Windows 11 / Windows Server 2022 |
| **Processor** | 64-bit Intel / AMD x86_64, 4+ Cores recommended |
| **RAM** | 8 GB minimum (16 GB recommended for concurrent OCR + local inference) |
| **Storage** | 10 GB free SSD storage for OS, dependencies, and audit logs |
| **Network** | Outbound HTTPS/WSS (TCP Port 443) to Cloud Relay & Gemini API. **Zero inbound ports required.** |
| **Python** | Python 3.12.x (64-bit) with `pip` and virtual environment support |
| **Display** | Minimum 1280x720 display resolution (for Admin Dashboard and System Tray) |

---

## 3. Installation & Certificate Staging

### 3.1 Code Signing Certificate Overview
Release100 executables and scripts are digitally signed to eliminate Windows SmartScreen warnings and guarantee tamper detection. In staging and virtual environments, a dedicated self-signed root certificate authority is utilized.

### 3.2 Certificate Generation (Build Machine)
On the build machine, generate the signing certificate pair:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\deployment\packaging_windows\generate_test_cert.ps1
```
This produces `Release100_TestCert.pfx` (private key for signing) and `Release100_TestCert.cer` (public certificate for target machines).

### 3.3 Certificate Installation on Target Windows VM
Transfer `Release100_TestCert.cer` to the target workstation and execute:
```powershell
.\deployment\packaging_windows\install_cert_on_vm.ps1
```
* **Elevated Execution:** Automatically installs into `Cert:\LocalMachine\Root` and `Cert:\LocalMachine\TrustedPublisher`.
* **Non-Elevated Fallback:** If elevation is declined or unavailable (e.g. standard user VM profiles), the script automatically detects access limitations (`0x80070005`) and safely provisions the certificate into `Cert:\CurrentUser\Root` and `Cert:\CurrentUser\TrustedPublisher`.
* **Verification:** Run `certutil -store Root "Release100"` to verify root authority installation.

---

## 4. Platform Configuration (`.env`)

Configuration parameters are managed via environment variables or a local `.env` file at the project root.

```ini
# ==============================================================================
# RELEASE100 PLATFORM ENVIRONMENT CONFIGURATION
# ==============================================================================

# Core Identity
TENANT_ID="canebot-enterprise"
KIOSK_ID="kiosk-pune-hub-01"
ORGANIZATION_NAME="CaneBot Automated Systems"
STATION_NAME="Pune Chilled Processing Depot"
ENVIRONMENT="production"
DRY_RUN=false

# Networking & Ports
ORCHESTRATOR_HOST="127.0.0.1"
ORCHESTRATOR_PORT=8000

# Zero-Inbound Cloud Relay (Outbound WebSocket)
# Set to your Cloudflare Worker or Render deployment URL
RELAY_WS_URL="wss://relay.canebot.internal/ws/{kiosk_id}"
RELAY_RECONNECT_INTERVAL_SECONDS=5

# Active Applications (JSON Array of strings)
ENABLED_APPLICATIONS='["temperature_marker", "mail_organizer"]'

# WhatsApp Cloud API Ingress Token Verification
WHATSAPP_VERIFY_TOKEN="Release100SecureVerificationToken2026"
WHATSAPP_ACCESS_TOKEN="EAAX..."
WHATSAPP_PHONE_NUMBER_ID="10987654321"

# Cognitive AI / Gemini Engine
GEMINI_API_KEY="AIzaSy..."
GEMINI_MODEL="gemini-2.5-flash"

# Telemetry & Audit Logs
AUDIT_LOG_DIR="audit_logs"
TELEMETRY_FORMATS='["jsonl", "csv", "html"]'
```

---

## 5. Supervisor Lifecycle & Execution

Release100 is supervised by a multi-process watchdog architecture that ensures high availability (99.9% uptime).

### 5.1 Starting the Supervised Service
To launch the platform host under supervision:
```powershell
python manage.py run --supervisor
```
The Process Supervisor performs:
1. **Health Polling:** Queries `http://127.0.0.1:8000/health` every 5 seconds.
2. **Crash Detection:** If the FastAPI backend crashes or hangs (>15s), the supervisor restarts it with exponential backoff (1s, 2s, 4s, 8s).
3. **System Tray Integration:** Displays a Windows System Tray icon with real-time status:
   * **Green:** Backend Healthy & Cloud Relay Connected.
   * **Yellow:** Backend Recovering or Relay Reconnecting.
   * **Red:** Backend Unhealthy or Process Terminated.

### 5.2 Standalone (Dev/Debug) Mode
To run without the supervisor for interactive debugging:
```powershell
python manage.py run --host 127.0.0.1 --port 8000
```

### 5.3 Health Check Monitoring
Query the heartbeat endpoint locally:
```powershell
curl.exe http://127.0.0.1:8000/health
```
Example Output:
```json
{
  "status": "healthy",
  "timestamp_utc": "2026-09-15T18:40:00.000Z",
  "uptime_seconds": 3612.4,
  "tenant_id": "canebot-enterprise",
  "kiosk_id": "kiosk-pune-hub-01",
  "organization_name": "CaneBot Automated Systems",
  "station_name": "Pune Chilled Processing Depot",
  "enabled_apps": ["temperature_marker", "mail_organizer"],
  "cloud_relay": {
    "enabled": true,
    "relay_url": "wss://relay.canebot.internal/ws/kiosk-pune-hub-01",
    "connected": true,
    "messages_received": 142,
    "connection_attempts": 1,
    "last_connected_at": "2026-09-15T17:40:00.000Z"
  },
  "skills": {
    "geofencing": {"status": "ok"},
    "display_ocr": {"status": "ok"},
    "face_recognizer": {"status": "ok"},
    "image_enhancer": {"status": "ok"}
  },
  "audit_engine": {
    "last_sequence_number": 284,
    "last_record_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "active_records_count": 284
  }
}
```

---

## 6. Cloud Relay Server Architecture

### 6.1 Purpose & Security Model
Factory kiosks frequently sit behind carrier-grade NAT (CGNAT) or strict corporate firewalls where opening inbound ports (e.g. TCP 8000 or 443) is strictly forbidden. 

The **Cloud Relay** acts as a stateless, persistent WebSocket multiplexer:
1. **Kiosk Ingress:** Kiosk initiates an outbound TLS connection (`wss://`) to `relay.domain.com/ws/{kiosk_id}`.
2. **Cloud API Webhook:** Meta WhatsApp Cloud API sends HTTP POST webhooks to `https://relay.domain.com/webhook`.
3. **Dispatch:** The relay matches the incoming destination kiosk ID and pushes the payload down the established WebSocket channel.
4. **Local Consumption:** The kiosk `CloudRelayClient` receives the JSON frame and dispatches it directly into `dispatch_whatsapp_payload()`.

---

## 7. Dual-Engine Verification & Benchmark Suite

In compliance with **GEES v1.0**, any software modification or deployment staging must pass both verification engines before deployment approval.

### 7.1 Engine A: Synthetic Unit Test Suite
Execute the fast mocked unit test suite:
```powershell
python -m pytest tests/unit/ -v --cov=core_platform --cov=apps --cov-report=term-missing
```
* **Gate Requirement:** $\ge 80.0\%$ line and branch code coverage.
* **Target:** 100% test pass rate across all 106+ unit tests.

### 7.2 Engine B: High-Fidelity Live Benchmark Suite
Run live end-to-end benchmark scenarios:
```powershell
# Run Temperature Marker live scenarios
python run_live_benchmark.py --domain temperature_marker --quality-gate

# Run Mail Organizer live scenarios
python run_live_benchmark.py --domain mail_organizer --quality-gate
```
* **Gate Requirement:** **100.0% Hard Safety Pass Rate** (zero unhandled exceptions, zero data tampering, zero unauthorized executions).
* **Gate Requirement:** $\ge 80.0\%$ functional pass rate.
* **Output:** Generates `reports/live_benchmark.html` and `reports/live_benchmark.json`.

### 7.3 Static Type Analysis
Enforce strict type completeness:
```powershell
python -m mypy --python-version 3.12 core_platform apps
```
* **Gate Requirement:** `0` type errors under strict annotations.

---

## 8. Audit Trail Verification & Compliance

### 8.1 SHA-256 Hash Chaining
Every operator action, temperature record, email triage result, and PM task update is recorded in an append-only cryptographic ledger:
$$\text{Record Hash}_n = \text{SHA-256}(\text{Record Hash}_{n-1} + \text{Timestamp}_n + \text{Payload}_n)$$

### 8.2 Audit Log Inspection
Log files are written contemporaneously to:
* `audit_logs/audit_trail.jsonl`: Machine-readable SIEM feed.
* `audit_logs/audit_trail.csv`: Human-readable tabular format for Excel / operational audits.
* `audit_logs/audit_dashboard.html`: Interactive visual dashboard.

To verify audit chain integrity:
```powershell
python -c "from core_platform.app.telemetry.audit_engine import AuditEngine; engine = AuditEngine.get_instance(); print('Chain Valid:', engine.verify_chain_integrity())"
```

---

## 9. Troubleshooting & FAQ

| Symptom | Root Cause | Remediation |
| :--- | :--- | :--- |
| `0x80070005 (E_ACCESSDENIED)` during certificate install | Script run without admin rights | Run updated `install_cert_on_vm.ps1` which automatically falls back to `Cert:\CurrentUser\Root`. |
| `Cloud Relay connection error: [WinError 10061]` | Relay server unreachable or port blocked | Verify `RELAY_WS_URL` is accessible via browser; ensure firewall permits outbound port 443. |
| Ingress 401 Unauthorized | Missing or mismatched verify token | Check `WHATSAPP_VERIFY_TOKEN` in `.env` matches Meta webhook settings. |
| Tray Icon displays Yellow / Error | Backend crashed or port 8000 in use | Check `logs/platform.log`; inspect port using `netstat -ano \| findstr 8000`. |
| Confidence score < 85% diverted | Blurry image or low OCR confidence | System intentionally diverted reading to Admin Review Queue per GEES Layer 2 safety directives. |
