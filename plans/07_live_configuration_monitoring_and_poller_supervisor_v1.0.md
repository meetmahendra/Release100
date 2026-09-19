# LIVE CONFIGURATION, APPLICATION REGISTRY & RESILIENT POLLER SUPERVISOR SPECIFICATION
## Host Control Plane, Live Diagnostics & Cooperative Process Lifecycle (`Release100`)

```
Document ID         : 07_live_configuration_monitoring_and_poller_supervisor
Document Version    : v1.0.0
Date                : September 15, 2026
Status              : APPROVED FOR IMPLEMENTATION
Target Packages     : core_platform/app/diagnostics, core_platform/app/apps_registry,
                      apps/mail_organizer/services, deployment/desktop_tray,
                      deployment/supervisor
Master References   : 01_master_platform_architecture_v1.4.md
                      04_app_mail_organizer_v1.0.md
                      05_deployment_and_packaging_hub_v1.2.md
                      06_engineering_excellence_standards_v1.0.md
Source Reference    : D:\AI-ProjectManager\tray_app, D:\mailOrganizer\issues\ISSUE-005
License             : Apache License 2.0 (Copyright 2026 Mahendra GURAV)
```

---

## Document Revision History & Changelog

| Version | Date | Author | Description of Changes | Status |
| :--- | :--- | :--- | :--- | :--- |
| **v1.0.0** | 2026-09-15 | AI Architecture Team | **Initial Approved Plan**: <br>1. **Live Web Configuration & Testing Console**: Ported from `AI-ProjectManager` to `core_platform/app/diagnostics`, mounting `/settings`, `/api/diagnostics/verify`, `/api/diagnostics/save`, and `/api/diagnostics/restore` with automated `.env` backup and 1-click rollback.<br>2. **Dynamic Active/Inactive Applications Monitoring**: Real-time discovery and tracking of installed cartridges (`temperature_marker`, `mail_organizer`), reporting active/inactive state in the Windows tray menu and `/settings`.<br>3. **Mail Organizer Poller with Guaranteed Clean Shutdown**: Resolves **ISSUE-005** with a dual-layer cooperative shutdown engine (chunked 0.5s sleep loop + atomic `.poll_worker_stop` file sentinel + verified process tree killer) ensuring zero orphaned background processes on Windows and Linux.<br>4. **Desktop Tray UI Hardening**: Dynamic application menu items, real-time poller checkmark synchronization, and background monitoring thread. | **Current** |

---

## 1. Subsystem Mission & Architectural Goals

The **Live Configuration, Application Monitoring & Poller Supervisor** bridges runtime operator convenience with rugged, deterministic process guarantees. It provides factory administrators and plant operators with immediate visibility, non-destructive configuration editing, on-demand diagnostics, and leak-free process management.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ WINDOWS TASKBAR NOTIFICATION AREA (pystray DesktopTrayApp)                  │
│                                                                             │
│  [Right-Click Context Menu]                                                  │
│  ├── ⚙️ Live Settings & Testing Console  ───> Opens Browser: /settings      │
│  ├── ───────────────────────────────                                        │
│  ├── Applications:                                                          │
│  │   ├── ● Temperature Marker (Active)  ───> Opens /admin/apps/temperature-..│
│  │   └── ● Mail Organizer (Active)      ───> Opens /admin/apps/mail-organizer│
│  ├── ───────────────────────────────                                        │
│  ├── [✓] Mail Poller (Running)         ───> Toggles Poller (Cooperative Kill)│
│  ├── ───────────────────────────────                                        │
│  ├── 📊 Visual Audit Dashboard (HTML)  ───> Opens /audit_dashboard.html      │
│  ├── 📦 1-Click Export Audit (ZIP)     ───> Packages to Desktop              │
│  └── ❌ Shutdown Release100 & Exit     ───> Clean Cascade Shutdown           │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │ Poller Toggle / Web Navigation
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ CORE PLATFORM HOST (FastAPI :8000)                                          │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ /settings Web Console (core_platform/app/diagnostics/web_dashboard.py)│  │
│  │                                                                       │  │
│  │  [Tab 1: Active Applications]                                         │  │
│  │  • Live registry of installed vs enabled apps                         │  │
│  │  • Dynamic toggle: Enable / Disable without full restart               │  │
│  │  • Mail Poller State: RUNNING / STOPPED with instant start/stop       │  │
│  │                                                                       │  │
│  │  [Tab 2: Live Diagnostics & Pingers]                                  │  │
│  │  • verify_gemini: Google AI Studio token generation ping              │  │
│  │  • verify_whatsapp: Graph API token & Phone Number ID check           │  │
│  │  • verify_cloud_relay: Outbound WebSocket handshake test              │  │
│  │  • verify_webhook: Webhook verification challenge simulation          │  │
│  │  • verify_ports: TCP listener check (:8000, etc.)                     │  │
│  │  • send_test_whatsapp_message: Live test message dispatch             │  │
│  │                                                                       │  │
│  │  [Tab 3: Configuration & Backups]                                     │  │
│  │  • Non-destructive master .env editor                                 │  │
│  │  • Automatic pre-save timestamped backup (config_backups/env_*.bak)   │  │
│  │  • 1-Click Rollback to any historical backup                          │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                       │
│                                      ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Application Registry (core_platform/app/apps_registry.py)             │  │
│  │ • Auto-discovers cartridges in apps/                                  │  │
│  │ • Compares with settings.ENABLED_APPLICATIONS                         │  │
│  │ • Broadcasts state changes to Main Tray and Health Heartbeat          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │ Spawns & Supervises
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ MAIL ORGANIZER POLLER SERVICE (apps/mail_organizer/services/poll_worker.py) │
│                                                                             │
│  Dual-Layer Cooperative Shutdown Engine (Solving ISSUE-005):                │
│  1. Atomic Sentinel File: .poll_worker_stop                                 │
│  2. Chunked Sleep Loop: Sleeps in 0.5s intervals, checking stop event       │
│  3. Verified Process Tree Killer: taskkill /F /T /PID -> proc.wait(2s)      │
│  4. Zero Zombie Guarantee: Process table re-query confirms total exit       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component 1: Mail Organizer Poller Service & Clean Shutdown (ISSUE-005 Fix)

### 2.1 Root Cause of ISSUE-005 in Legacy Codebase
In `AI-ProjectManager` and legacy `mailOrganizer`, deselecting the background poller in the tray menu showed a toast saying "PAUSED", but the `poll_worker` process continued running indefinitely. The root causes were:
1. **Monolithic Sleep**: `time.sleep(60)` ignored asynchronous OS signals and tray toggles.
2. **PyInstaller Bootloader PID Mismatch**: In frozen mode, `proc.pid` was the launcher process; killing it left the spawned Python worker child orphaned.
3. **Unverified Process Termination**: `taskkill` was fired without calling `proc.wait(timeout=2.0)` or checking if the process and its children actually exited.

### 2.2 Dual-Layer Cooperative Shutdown Engine
The new poller service (`apps/mail_organizer/services/poll_worker.py`) implements:
1. **Atomic Sentinel File**:
   - Stop path: `D:\Release100\.poll_worker_stop`.
   - Before executing `taskkill`, the supervisor touches this sentinel.
2. **Chunked Sleep Loop**:
   - Replaces `time.sleep(POLL_INTERVAL)` with:
     ```python
     def interruptible_sleep(seconds: float, stop_event: threading.Event) -> bool:
         """Sleep in 0.5s slices; return True immediately if stop requested."""
         deadline = time.time() + seconds
         while time.time() < deadline:
             if stop_event.is_set() or os.path.exists(STOP_SENTINEL_PATH):
                 return True
             time.sleep(0.5)
         return False
     ```
3. **Graceful Signal Handling**:
   - Hooks `SIGINT` and `SIGTERM` on all platforms.
   - Closes database sessions, releases file locks, and removes the sentinel upon clean exit.
4. **Post-Termination Verification in Supervisor**:
   ```python
   # 1. Touch cooperative sentinel
   touch_sentinel(STOP_SENTINEL_PATH)
   # 2. Issue process tree kill
   subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], ...)
   # 3. Verified wait
   try:
       proc.wait(timeout=2.0)
   except subprocess.TimeoutExpired:
       force_kill_process_tree(proc.pid)
   # 4. Confirm PID is gone
   assert not is_pid_alive(proc.pid)
   ```

---

## 3. Component 2: Dynamic Applications Registry & Monitoring

### 3.1 Registry Responsibilities (`core_platform/app/apps_registry.py`)
1. **Discovery**: Scans `apps/` directory to discover domain cartridges.
2. **Runtime Status Classification**:
   - `ACTIVE`: Installed and included in `settings.ENABLED_APPLICATIONS`.
   - `INACTIVE` / `DISABLED`: Installed in `apps/` but excluded from `settings.ENABLED_APPLICATIONS`.
   - `ERROR`: Cartridge present but failing plugin validation or missing entrypoints.
3. **Metadata Provisioning**:
   - Application title, version, author, description.
   - Primary admin dashboard route (e.g. `/admin/apps/temperature-marker/fleet`, `/admin/apps/mail-organizer/dashboard`).
   - Associated background services (e.g. `mail_poller` for `mail_organizer`).
4. **Dynamic Reconfiguration**:
   - Exposes `enable_application(app_name: str)` and `disable_application(app_name: str)`.
   - Persists changes non-destructively to `.env` via the config backup engine.

---

## 4. Component 3: Live Configuration & Testing Console (`/settings`)

### 4.1 Diagnostics Verifier (`core_platform/app/diagnostics/verifier.py`)
Ported and modernized from `d:\AI-ProjectManager\tray_app\verifier.py`:
- `verify_gemini(api_key: Optional[str])`:
  - Issues a minimal token generation ping (`gemini-2.5-flash` or `gemini-1.5-flash`) to Google AI Studio.
  - Returns `{"status": "ok", "latency_ms": 320, "model": "..."}` or detailed failure diagnostics.
- `verify_whatsapp(access_token: Optional[str], phone_number_id: Optional[str])`:
  - Queries Meta Graph API: `https://graph.facebook.com/v19.0/{phone_number_id}`.
  - Verifies token validity, phone number status, and display name.
- `verify_cloud_relay(relay_url: Optional[str])`:
  - Initiates an outbound WebSocket handshake to `wss://<relay_domain>/ws/{kiosk_id}` with a 5-second timeout.
  - Confirms firewall punching and edge reachability.
- `verify_webhook_ingress(verify_token: Optional[str])`:
  - Simulates Meta's `GET /webhook?hub.mode=subscribe&hub.verify_token=...` challenge.
- `verify_hmac_secret(app_secret: Optional[str])`:
  - Verifies SHA-256 HMAC signature calculation against test payloads.
- `send_test_whatsapp_message(phone: str, message: Optional[str])`:
  - Dispatches an actual test message to the operator's phone to verify end-to-end outbound transmission.
- `verify_ports()`:
  - Verifies local ports (`8000`, etc.) are bound and listening.

### 4.2 Non-Destructive Configuration Backup & Rollback (`config_backup.py`)
- **Directory**: `config_backups/`
- **Pre-Save Backup**: Every save creates a timestamped copy: `config_backups/env_YYYYMMDD_HHMMSS.bak`.
- **Safe Key Replacement**: Parses `.env`, updates specific keys while preserving all comments, blank lines, and formatting.
- **Rollback**: Restores any historical backup file with single-click verification.

### 4.3 Web Dashboard Controller (`web_dashboard.py`)
- **Route**: `GET /settings`
- Renders an offline-safe, high-contrast, responsive management UI with:
  1. **Active Applications Tab**: Interactive cards showing app health, direct links to admin dashboards, and Mail Poller start/stop buttons.
  2. **Live Diagnostics Tab**: Test buttons for Gemini, WhatsApp, Cloud Relay, Webhooks, and Ports.
  3. **Configuration & Backups Tab**: Form for editing `.env` parameters, listing backups, and 1-click restore.

---

## 5. Component 4: Dynamic Windows System Tray Menu Hardening

### 5.1 Dynamic Context Menu Structure (`deployment/desktop_tray/main_tray.py`)
```python
pystray.Menu(
    pystray.MenuItem("⚙️ Live Settings & Testing Console", lambda _: self.open_settings(), default=True),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem("Applications:", None, enabled=False),
    pystray.MenuItem(
        "  ● Temperature Marker (Active)", 
        lambda _: self.open_temp_dashboard(),
        visible=lambda _: self.is_app_active("temperature_marker")
    ),
    pystray.MenuItem(
        "  ● Mail Organizer (Active)", 
        lambda _: self.open_mail_dashboard(),
        visible=lambda _: self.is_app_active("mail_organizer")
    ),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem(
        "Mail Poller (Background Ingestion)", 
        self.on_toggle_poller,
        checked=lambda item: self.is_poller_running(),
        visible=lambda _: self.is_app_active("mail_organizer")
    ),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem("📊 Visual Audit Dashboard (HTML)", lambda _: self.open_audit_dashboard()),
    pystray.MenuItem("📦 1-Click Export Audit Package (ZIP)", lambda _: self.trigger_export()),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem("❌ Shutdown Release100 & Exit", lambda _: self.exit_application()),
)
```

### 5.2 Background Poller & State Synchronization Thread
- Runs every 5 seconds.
- Queries `apps_registry` and `supervisor.is_poll_worker_running()`.
- Updates tray icon color:
  - **Green**: Backend healthy & poller running (if enabled).
  - **Yellow**: Standby ready (poller stopped or standby mode).
  - **Red**: Error or process crash.
- Invokes `self.icon.update_menu()` to ensure checkmarks on the Windows native menu stay synchronized without lag or stale visual states.

---

## 6. Verification Regime & Acceptance Criteria

### 6.1 Synthetic Unit Tests (Engine A)
1. `tests/unit/test_poll_worker.py`:
   - Verify chunked sleep loop breaks immediately when sentinel is touched ($< 0.6\text{s}$).
   - Verify unread email ingestion and pipeline invocation.
   - Verify clean shutdown without unhandled exceptions.
2. `tests/unit/test_apps_registry.py`:
   - Verify discovery of installed apps (`temperature_marker`, `mail_organizer`).
   - Verify filtering against `ENABLED_APPLICATIONS`.
   - Verify dynamic enabling/disabling of domain cartridges.
3. `tests/unit/test_diagnostics_api.py`:
   - Verify `GET /api/diagnostics/status`.
   - Verify `POST /api/diagnostics/verify` for mocked Gemini, WhatsApp, and Relay endpoints.
   - Verify `POST /api/diagnostics/save` creates backup before modifying `.env`.
   - Verify `POST /api/diagnostics/restore` restores previous configuration.
4. Line & branch coverage must maintain $\ge 80.0\%$.

### 6.2 High-Fidelity Live Benchmarks (Engine B)
- Re-run `temperature_marker` quality gate ($\ge 80\%$ functional, $100\%$ hard safety).
- Re-run `mail_organizer` quality gate ($\ge 80\%$ functional, $100\%$ hard safety).

### 6.3 Strict Static Typing
- `mypy --strict` with 0 errors across all 84+ source files.
