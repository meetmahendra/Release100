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

"""
Automated Live UI Screenshot Capture Engine using Chrome DevTools Protocol (CDP).

Captures full-fidelity, high-resolution desktop screenshots of every platform,
DevOps control plane, tenant workspace, and domain cartridge page.
"""

import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import websockets

from core_platform.app.auth.jwt_utils import create_jwt_token


SCREENSHOT_DIR = Path(r"C:\Users\depali Gurav\.gemini\antigravity\brain\5dcee49a-51c8-4a1f-aa91-489aba7c34ba\ui_screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_BIN = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = Path(r"d:\IntentRouter_Release100\scratch_chrome_screenshots")
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Generate JWT tokens for authentication
DEVOPS_TOKEN = create_jwt_token(
    principal_id="admin",
    roles=["admin", "devops_admin", "super_admin"],
    permitted_apps=["mail_organizer", "temperature_marker"],
    tenant_id="platform",
)

TENANT_TOKEN = create_jwt_token(
    principal_id="admin_gurav_family",
    roles=["admin"],
    permitted_apps=["mail_organizer"],
    tenant_id="gurav_family",
)


PAGES_TO_CAPTURE = [
    # 1. Authentication
    {
        "id": "01_login_platform",
        "title": "Platform Admin Login Screen",
        "url": "http://127.0.0.1:8000/admin/login",
        "auth": None,
        "category": "Authentication",
    },
    {
        "id": "02_login_tenant_gurav_family",
        "title": "Tenant Scoped Login (Gurav Family)",
        "url": "http://gurav-family.release100.com:8000/admin/login",
        "auth": None,
        "category": "Authentication",
    },

    # 2. DevOps Super-Admin Operations Control Plane
    {
        "id": "03_ops_tenants_directory",
        "title": "DevOps Multi-Tenant Control Plane Directory",
        "url": "http://127.0.0.1:8000/ops/tenants",
        "auth": DEVOPS_TOKEN,
        "category": "DevOps Control Plane",
    },
    {
        "id": "04_ops_tenant_audit_trail",
        "title": "DevOps SHA-256 Non-Repudiation Audit Trail",
        "url": "http://127.0.0.1:8000/ops/tenants/gurav_family/audit",
        "auth": DEVOPS_TOKEN,
        "category": "DevOps Control Plane",
    },

    # 3. Central Admin Shell (Platform Scoped)
    {
        "id": "05_admin_shell_dashboard",
        "title": "Central Operations Shell Dashboard",
        "url": "http://127.0.0.1:8000/admin/",
        "auth": DEVOPS_TOKEN,
        "category": "Platform Admin Shell",
    },
    {
        "id": "06_admin_company_profile_vault",
        "title": "Platform Organization Profile & BYOK Vault",
        "url": "http://127.0.0.1:8000/admin/tenants",
        "auth": DEVOPS_TOKEN,
        "category": "Platform Admin Shell",
    },
    {
        "id": "07_admin_users_registry",
        "title": "Platform Multi-Tenant User Registry",
        "url": "http://127.0.0.1:8000/admin/users",
        "auth": DEVOPS_TOKEN,
        "category": "Platform Admin Shell",
    },
    {
        "id": "08_admin_api_keys",
        "title": "Platform Scoped Bearer API Keys Vault",
        "url": "http://127.0.0.1:8000/admin/api-keys",
        "auth": DEVOPS_TOKEN,
        "category": "Platform Admin Shell",
    },
    {
        "id": "09_admin_audit_logs",
        "title": "Platform Live Log Stream & Deep Telemetry",
        "url": "http://127.0.0.1:8000/admin/logs",
        "auth": DEVOPS_TOKEN,
        "category": "Platform Admin Shell",
    },
    {
        "id": "10_admin_llm_costs",
        "title": "Platform LLM Token Usage & Cost Attribution",
        "url": "http://127.0.0.1:8000/admin/llm-costs",
        "auth": DEVOPS_TOKEN,
        "category": "Platform Admin Shell",
    },

    # 4. Tenant Scoped Admin Shell (Gurav Family Workspace)
    {
        "id": "11_tenant_workspace_dashboard",
        "title": "Customer Workspace Dashboard (Gurav Family)",
        "url": "http://gurav-family.release100.com:8000/admin/",
        "auth": TENANT_TOKEN,
        "category": "Customer Tenant Workspace",
    },
    {
        "id": "12_tenant_company_vault",
        "title": "Customer Company Profile & BYOK Vault",
        "url": "http://gurav-family.release100.com:8000/admin/tenants",
        "auth": TENANT_TOKEN,
        "category": "Customer Tenant Workspace",
    },
    {
        "id": "13_tenant_user_registry",
        "title": "Customer User Registry & Cartridge Entitlements",
        "url": "http://gurav-family.release100.com:8000/admin/users",
        "auth": TENANT_TOKEN,
        "category": "Customer Tenant Workspace",
    },

    # 5. Domain Cartridge: Mail Organizer
    {
        "id": "14_mail_kpi_dashboard",
        "title": "Mail Organizer — KPI Metrics & Queue Dashboard",
        "url": "http://127.0.0.1:8000/admin/apps/mail-organizer/dashboard",
        "auth": DEVOPS_TOKEN,
        "category": "Mail Organizer Cartridge",
    },
    {
        "id": "15_mail_triage_simulator",
        "title": "Mail Organizer — Interactive Triage Simulator",
        "url": "http://127.0.0.1:8000/admin/apps/mail-organizer/triage",
        "auth": DEVOPS_TOKEN,
        "category": "Mail Organizer Cartridge",
    },
    {
        "id": "16_mail_drafts_review",
        "title": "Mail Organizer — Staged Contextual Draft Replies",
        "url": "http://127.0.0.1:8000/admin/apps/mail-organizer/drafts",
        "auth": DEVOPS_TOKEN,
        "category": "Mail Organizer Cartridge",
    },
    {
        "id": "17_mail_pm_queue",
        "title": "Mail Organizer — Human-in-the-Loop PM Action Queue",
        "url": "http://127.0.0.1:8000/admin/apps/mail-organizer/pm-queue",
        "auth": DEVOPS_TOKEN,
        "category": "Mail Organizer Cartridge",
    },
    {
        "id": "18_mail_rules_manager",
        "title": "Mail Organizer — VIP & Whitelist Rules Engine",
        "url": "http://127.0.0.1:8000/admin/apps/mail-organizer/rules",
        "auth": DEVOPS_TOKEN,
        "category": "Mail Organizer Cartridge",
    },
    {
        "id": "19_mail_accounts_oauth",
        "title": "Mail Organizer — Google Workspace OAuth Accounts",
        "url": "http://127.0.0.1:8000/admin/apps/mail-organizer/accounts",
        "auth": DEVOPS_TOKEN,
        "category": "Mail Organizer Cartridge",
    },

    # 6. Domain Cartridge: Temperature Marker
    {
        "id": "20_temp_fleet_roster",
        "title": "Temperature Marker — Fleet Map & Operator Roster",
        "url": "http://127.0.0.1:8000/admin/apps/temperature-marker/fleet",
        "auth": DEVOPS_TOKEN,
        "category": "Temperature Marker Cartridge",
    },
    {
        "id": "21_temp_wizard_simulator",
        "title": "Temperature Marker — 5-Step Stepper Wizard Simulator",
        "url": "http://127.0.0.1:8000/admin/apps/temperature-marker/wizard",
        "auth": DEVOPS_TOKEN,
        "category": "Temperature Marker Cartridge",
    },
    {
        "id": "22_temp_approvals_gate",
        "title": "Temperature Marker — Operator Exceptions & Approvals Gate",
        "url": "http://127.0.0.1:8000/admin/apps/temperature-marker/approvals",
        "auth": DEVOPS_TOKEN,
        "category": "Temperature Marker Cartridge",
    },
    {
        "id": "23_temp_loc_calibration",
        "title": "Temperature Marker — Line-of-Sight GPS Geolocation",
        "url": "http://127.0.0.1:8000/admin/apps/temperature-marker/loc",
        "auth": DEVOPS_TOKEN,
        "category": "Temperature Marker Cartridge",
    },
    {
        "id": "24_temp_monitoring_telemetry",
        "title": "Temperature Marker — Kiosk Heartbeats & Cold-Chain Telemetry",
        "url": "http://127.0.0.1:8000/admin/apps/temperature-marker/monitoring",
        "auth": DEVOPS_TOKEN,
        "category": "Temperature Marker Cartridge",
    },
]


async def capture_all_pages() -> None:
    """Launch headless Chrome and capture screenshots of all registered pages."""
    print("[SCREENSHOT] Launching Chrome Headless with Remote Debugging Port 9222...")
    chrome_proc = subprocess.Popen([
        CHROME_BIN,
        "--headless=new",
        "--remote-debugging-port=9222",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1440,900",
        f"--user-data-dir={USER_DATA_DIR}",
        "about:blank",
    ])

    await asyncio.sleep(2.5)

    try:
        # Discover CDP target
        with urllib.request.urlopen("http://127.0.0.1:9222/json") as resp:
            targets = json.loads(resp.read().decode("utf-8"))
            page_target = next(t for t in targets if t.get("type") == "page")
            ws_url = page_target["webSocketDebuggerUrl"]

        print(f"[SCREENSHOT] Connected to CDP Target: {ws_url}")

        async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
            req_id = 1

            async def send_cmd(method: str, params: dict = None) -> dict:
                nonlocal req_id
                msg_id = req_id
                req_id += 1
                payload = {"id": msg_id, "method": method, "params": params or {}}
                await ws.send(json.dumps(payload))
                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if data.get("id") == msg_id:
                        return data

            # Enable Network and Page domains
            await send_cmd("Page.enable")
            await send_cmd("Network.enable")
            await send_cmd("Emulation.setDeviceMetricsOverride", {
                "width": 1440,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            })

            catalog = []

            for idx, item in enumerate(PAGES_TO_CAPTURE, 1):
                page_id = item["id"]
                title = item["title"]
                url = item["url"]
                auth_token = item["auth"]
                category = item["category"]

                print(f"[{idx}/{len(PAGES_TO_CAPTURE)}] Capturing {title} ({url})...")

                # Clear and set cookies
                await send_cmd("Network.clearBrowserCookies")
                if auth_token:
                    domain = "gurav-family.release100.com" if "gurav-family" in url else "127.0.0.1"
                    await send_cmd("Network.setCookie", {
                        "name": "admin_token",
                        "value": auth_token,
                        "domain": domain,
                        "path": "/",
                        "httpOnly": True,
                    })

                # Navigate
                await send_cmd("Page.navigate", {"url": url})
                await asyncio.sleep(1.5)

                # Capture full screenshot
                shot_resp = await send_cmd("Page.captureScreenshot", {
                    "format": "png",
                    "quality": 100,
                    "fromSurface": True,
                })

                img_b64 = shot_resp.get("result", {}).get("data", "")
                if img_b64:
                    out_path = SCREENSHOT_DIR / f"{page_id}.png"
                    with open(out_path, "wb") as f:
                        f.write(base64.b64decode(img_b64))
                    print(f"    --> Saved: {out_path.name} ({len(img_b64)} bytes base64)")
                    catalog.append({
                        "id": page_id,
                        "title": title,
                        "url": url,
                        "category": category,
                        "filename": f"{page_id}.png",
                        "filepath": str(out_path),
                    })
                else:
                    print(f"    --> ERROR: No image data returned for {page_id}")

            # Write catalog summary JSON
            catalog_file = SCREENSHOT_DIR / "ui_catalog.json"
            with open(catalog_file, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2)

            print(f"\n[SUCCESS] All {len(catalog)} screenshots saved to {SCREENSHOT_DIR}")
            print(f"[CATALOG] Catalog written to {catalog_file}")

    finally:
        chrome_proc.terminate()
        chrome_proc.wait()


if __name__ == "__main__":
    asyncio.run(capture_all_pages())
