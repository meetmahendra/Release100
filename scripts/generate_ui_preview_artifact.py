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

"""Generates an all-in-one responsive HTML UI gallery artifact with embedded base64 screenshots and discrepancy audit."""

import os
import json
import base64

def generate():
    art_dir = r"C:\Users\depali Gurav\.gemini\antigravity\brain\5dcee49a-51c8-4a1f-aa91-489aba7c34ba"
    catalog_file = os.path.join(art_dir, "ui_screenshots", "ui_catalog.json")
    out_html_path = os.path.join(art_dir, "ui_design_system_preview.html")

    with open(catalog_file, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    screen_notes = {
        "01_login_platform": {
            "finding": "Standard Platform Admin Login. Uses dark backdrop blur and emerald accents.",
            "target_ssot": "Retain as default public/platform login. Dynamic token compliance."
        },
        "02_login_tenant_gurav_family": {
            "finding": "Tenant-scoped Login. Correctly displays Workspace badge [Gurav family].",
            "target_ssot": "Unify login container dimensions and responsive spacing with platform login."
        },
        "03_ops_tenants_directory": {
            "finding": "Uses full-width horizontal topbar with indigo SUPER_ADMIN badge instead of sidebar.",
            "target_ssot": "Adopt unified base_shell layout with persistent sidebar and indigo superadmin section."
        },
        "04_ops_tenant_audit_trail": {
            "finding": "Deep SHA-256 non-repudiation audit table. Uses indigo accents and custom breadcrumb.",
            "target_ssot": "Inherit from base_shell.html using standard data_table macro and SHA-256 verification badge."
        },
        "05_admin_shell_dashboard": {
            "finding": "Collapsible sidebar shell with emerald accents and ready service indicators.",
            "target_ssot": "This serves as the primary structural foundation for base_shell.html across the entire platform."
        },
        "06_admin_company_profile_vault": {
            "finding": "Company profile & BYOK vault. Mixes form card styles with sidebar.",
            "target_ssot": "Standardize form cards using unified render_form_card and render_input macros."
        },
        "07_admin_users_registry": {
            "finding": "Uses standalone header bar with [Platform Dashboard / Users] backlink instead of sidebar shell.",
            "target_ssot": "Refactor users.html to extend base_shell.html with consistent sidebar navigation."
        },
        "08_admin_api_keys": {
            "finding": "Scoped Bearer API keys vault. Good layout but uses standalone card margins.",
            "target_ssot": "Standardize with shared data_table macro and modal_dialog for key generation."
        },
        "09_admin_audit_logs": {
            "finding": "Realtime system logs and telemetry streaming. Terminal style.",
            "target_ssot": "Wrap log viewer in standardized elevated card container with auto-scroll controls."
        },
        "10_admin_llm_costs": {
            "finding": "LLM token consumption and cost breakdown by cartridge and tenant.",
            "target_ssot": "Use standardized kpi_card macro for token counters and cost attribution metrics."
        },
        "11_tenant_workspace_dashboard": {
            "finding": "Customer tenant dashboard for Gurav Family. Clean, but cartridge sub-routes are missing from sidebar.",
            "target_ssot": "Sidebar dynamically injects entitled cartridge sub-menus when cartridge is selected."
        },
        "12_tenant_company_vault": {
            "finding": "Customer BYOK key vault. Scoped to Gurav Family tenant.",
            "target_ssot": "Standardize input styling and password reveal toggles with core macros."
        },
        "13_tenant_user_registry": {
            "finding": "Tenant-scoped user registry with WhatsApp cartridge entitlement toggles.",
            "target_ssot": "Standardize table row action buttons and user creation modal with core macros."
        },
        "14_mail_kpi_dashboard": {
            "finding": "Custom vanilla CSS top navigation header bar (--bg-main: #0b0f19). Disconnected from sidebar.",
            "target_ssot": "Extend base_shell.html; mount Mail Organizer tabs in contextual sub-nav bar or sidebar."
        },
        "15_mail_triage_simulator": {
            "finding": "Interactive triage workbench with custom button padding and non-standard JSON previewer.",
            "target_ssot": "Use standardized form controls, action buttons, and syntax-highlighted code container."
        },
        "16_mail_drafts_review": {
            "finding": "Staged draft replies table with custom action badges.",
            "target_ssot": "Standardize review gate table with shared status_badge and approval modal macros."
        },
        "17_mail_pm_queue": {
            "finding": "Human-in-the-loop project management queue. Custom card border styles.",
            "target_ssot": "Use unified data_table and task resolution dialog macro."
        },
        "18_mail_rules_manager": {
            "finding": "VIP whitelist rules table with custom styling.",
            "target_ssot": "Standardize rule builder modal and priority badges with shared macros."
        },
        "19_mail_accounts_oauth": {
            "finding": "Google Workspace OAuth accounts manager.",
            "target_ssot": "Use unified account connection card and status indicator macros."
        },
        "20_temp_fleet_roster": {
            "finding": "Fleet Telemetry & Operations Control. Custom vanilla CSS header bar (--bg-main: #0f172a).",
            "target_ssot": "Extend base_shell.html with Temperature Marker contextual sub-nav."
        },
        "21_temp_wizard_simulator": {
            "finding": "5-step simulation wizard. Uses custom stepper styling.",
            "target_ssot": "Standardize stepper component macro with consistent active step indicator."
        },
        "22_temp_approvals_gate": {
            "finding": "Exceptions and human approval gate table.",
            "target_ssot": "Standardize with shared approval_card macro and single-click resolution."
        },
        "23_temp_loc_calibration": {
            "finding": "Line-of-sight GPS geolocation calibration tool.",
            "target_ssot": "Standardize map container styling and coordinate input fields."
        },
        "24_temp_monitoring_telemetry": {
            "finding": "Kiosk heartbeats and cold-chain temperature telemetry stream.",
            "target_ssot": "Use standardized kpi_card for live temperatures and alert thresholds."
        }
    }

    cards_html = []
    for item in catalog:
        cid = item["id"]
        title = item["title"]
        cat = item["category"]
        url = item["url"]
        img_path = item["filepath"]
        
        b64_str = ""
        if os.path.exists(img_path):
            with open(img_path, "rb") as img_f:
                b64_str = base64.b64encode(img_f.read()).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64_str}" if b64_str else ""
        
        notes = screen_notes.get(cid, {"finding": "Standard screen.", "target_ssot": "Harmonize with base_shell."})
        
        card = f"""
        <div class="screen-card bg-[var(--card)] border border-[var(--border)] rounded-2xl overflow-hidden shadow-md hover:border-emerald-500/50 transition-all flex flex-col" data-category="{cat}">
          <div class="p-4 border-b border-[var(--border)] flex items-center justify-between gap-2">
            <div>
              <span class="text-xs font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">{cat}</span>
              <h3 class="text-base font-bold text-[var(--foreground)] mt-1.5 leading-snug">{title}</h3>
              <p class="text-xs font-mono text-[var(--muted-foreground)] mt-0.5 truncate max-w-[280px] sm:max-w-md">{url}</p>
            </div>
            <button onclick="openLightbox('{cid}')" class="shrink-0 px-3 py-1.5 rounded-lg bg-[var(--sidebar)] hover:bg-emerald-500/20 text-emerald-400 border border-[var(--border)] text-xs font-semibold flex items-center gap-1">
              🔍 Zoom
            </button>
          </div>
          <div class="relative bg-slate-950 p-2 cursor-pointer group" onclick="openLightbox('{cid}')">
            <img id="img-{cid}" src="{data_uri}" alt="{title}" class="w-full h-auto rounded-lg border border-slate-800 group-hover:opacity-90 transition-opacity" loading="lazy" />
            <div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 bg-black/50 transition-opacity rounded-lg">
              <span class="px-3 py-1.5 rounded-full bg-emerald-600 text-white font-bold text-xs shadow-lg">Tap / Click to Zoom</span>
            </div>
          </div>
          <div class="p-4 space-y-2 text-xs flex-1 flex flex-col justify-between border-t border-[var(--border)] bg-[var(--card)]/50">
            <div>
              <div class="mb-2">
                <span class="font-bold text-amber-400">⚠️ Current Discrepancy:</span>
                <p class="text-[var(--muted-foreground)] mt-0.5 leading-relaxed">{notes['finding']}</p>
              </div>
              <div>
                <span class="font-bold text-emerald-400">🎯 Target SSOT Blueprint:</span>
                <p class="text-[var(--foreground)] mt-0.5 leading-relaxed font-medium">{notes['target_ssot']}</p>
              </div>
            </div>
          </div>
        </div>
        """
        cards_html.append(card)

    cards_joined = "\n".join(cards_html)
    catalog_json_str = json.dumps(catalog)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Release100 UI Design System & Live Visual Audit Gallery</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    html {{ scroll-behavior: smooth; }}
    .hide-scrollbar::-webkit-scrollbar {{ display: none; }}
    .hide-scrollbar {{ -ms-overflow-style: none; scrollbar-width: none; }}
  </style>
</head>
<body class="bg-[var(--background)] text-[var(--foreground)] antialiased min-h-screen p-3 sm:p-6">

  <!-- Master Container -->
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- Header Banner -->
    <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 sm:p-6 shadow-lg">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--border)] pb-4">
        <div>
          <div class="flex items-center gap-2">
            <span class="px-2.5 py-1 rounded-md bg-emerald-500/20 text-emerald-400 font-mono font-bold text-xs border border-emerald-500/30">RELEASE100 SSOT</span>
            <span class="text-xs text-[var(--muted-foreground)] font-semibold">Single Source of Truth Design System</span>
          </div>
          <h1 class="text-xl sm:text-2xl font-black text-[var(--foreground)] mt-1.5 tracking-tight">Interactive UI Gallery & Discrepancy Audit</h1>
          <p class="text-xs sm:text-sm text-[var(--muted-foreground)] mt-1">Live visual inventory of all 24 interactive views with discrepancy analysis and unified architectural blueprint.</p>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <div class="px-3 py-2 rounded-xl bg-[var(--sidebar)] border border-[var(--border)] text-center">
            <span class="text-xs font-bold text-[var(--muted-foreground)] block uppercase">Screens</span>
            <span class="text-lg font-black text-emerald-400">24</span>
          </div>
          <div class="px-3 py-2 rounded-xl bg-[var(--sidebar)] border border-[var(--border)] text-center">
            <span class="text-xs font-bold text-[var(--muted-foreground)] block uppercase">Status</span>
            <span class="text-xs font-bold text-emerald-400 mt-1 block">VERIFIED</span>
          </div>
        </div>
      </div>

      <!-- Quick Jump Category Filter Buttons (Mobile Horizontal Scroll) -->
      <div class="flex items-center gap-2 pt-4 overflow-x-auto hide-scrollbar pb-1 text-xs">
        <button onclick="filterCategory('ALL')" class="cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-emerald-600 text-white shadow-sm" data-cat="ALL">
          🌟 All Screens (24)
        </button>
        <button onclick="filterCategory('Authentication')" class="cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-[var(--sidebar)] text-[var(--muted-foreground)] hover:text-white border border-[var(--border)]" data-cat="Authentication">
          🔑 Authentication (2)
        </button>
        <button onclick="filterCategory('DevOps Control Plane')" class="cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-[var(--sidebar)] text-[var(--muted-foreground)] hover:text-white border border-[var(--border)]" data-cat="DevOps Control Plane">
          ⚡ DevOps Control Plane (2)
        </button>
        <button onclick="filterCategory('Platform Admin Shell')" class="cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-[var(--sidebar)] text-[var(--muted-foreground)] hover:text-white border border-[var(--border)]" data-cat="Platform Admin Shell">
          🏢 Platform Operations (6)
        </button>
        <button onclick="filterCategory('Customer Tenant Workspace')" class="cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-[var(--sidebar)] text-[var(--muted-foreground)] hover:text-white border border-[var(--border)]" data-cat="Customer Tenant Workspace">
          👥 Tenant Workspace (3)
        </button>
        <button onclick="filterCategory('Mail Organizer Cartridge')" class="cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-[var(--sidebar)] text-[var(--muted-foreground)] hover:text-white border border-[var(--border)]" data-cat="Mail Organizer Cartridge">
          ✉️ Mail Organizer (6)
        </button>
        <button onclick="filterCategory('Temperature Marker Cartridge')" class="cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-[var(--sidebar)] text-[var(--muted-foreground)] hover:text-white border border-[var(--border)]" data-cat="Temperature Marker Cartridge">
          🌡️ Temperature Marker (5)
        </button>
      </div>
    </div>

    <!-- Architectural Blueprint Cards -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 shadow-sm">
        <div class="flex items-center gap-2 mb-2">
          <span class="text-lg">🏛️</span>
          <h2 class="text-sm font-bold text-[var(--foreground)]">1. Master Base Shell</h2>
        </div>
        <p class="text-xs text-[var(--muted-foreground)] leading-relaxed">
          Unifies sidebar and top context across all 24 routes. Persistent brand header, dynamic cartridge sub-menus, and responsive mobile hamburger drawer.
        </p>
      </div>
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 shadow-sm">
        <div class="flex items-center gap-2 mb-2">
          <span class="text-lg">🎨</span>
          <h2 class="text-sm font-bold text-[var(--foreground)]">2. Shared Design Tokens</h2>
        </div>
        <p class="text-xs text-[var(--muted-foreground)] leading-relaxed">
          Standardized Tailwind tokens across core and cartridges: slate-950 canvas, slate-900 cards, emerald-500 primary, and indigo-500 DevOps accents.
        </p>
      </div>
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 shadow-sm">
        <div class="flex items-center gap-2 mb-2">
          <span class="text-lg">🧩</span>
          <h2 class="text-sm font-bold text-[var(--foreground)]">3. Reusable Jinja2 Macros</h2>
        </div>
        <p class="text-xs text-[var(--muted-foreground)] leading-relaxed">
          Consolidated macro library for data tables, KPI metric cards, action modals, filter searchbars, and SHA-256 audit ledger badges.
        </p>
      </div>
    </div>

    <!-- Screenshot Cards Grid -->
    <div id="gallery-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
      {cards_joined}
    </div>

  </div>

  <!-- Lightbox Modal for Zoom & Fullscreen -->
  <div id="lightbox-modal" class="fixed inset-0 bg-black/90 backdrop-blur-md z-50 hidden flex flex-col p-3 sm:p-6" onclick="closeLightbox(event)">
    <div class="flex items-center justify-between pb-3 text-white max-w-6xl mx-auto w-full">
      <div>
        <h3 id="lightbox-title" class="text-sm sm:text-base font-bold text-white"></h3>
        <p id="lightbox-url" class="text-xs font-mono text-emerald-400"></p>
      </div>
      <button onclick="closeLightboxDirect()" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold border border-slate-700">
        ✕ Close
      </button>
    </div>
    <div class="flex-1 flex items-center justify-center max-w-6xl mx-auto w-full overflow-auto">
      <img id="lightbox-img" src="" alt="Zoomed Screenshot" class="max-h-[85vh] max-w-full rounded-xl border border-slate-800 shadow-2xl object-contain" />
    </div>
  </div>

  <script>
    const catalogData = {catalog_json_str};

    function filterCategory(cat) {{
      const cards = document.querySelectorAll('.screen-card');
      const buttons = document.querySelectorAll('.cat-btn');

      buttons.forEach(btn => {{
        if (btn.getAttribute('data-cat') === cat) {{
          btn.className = 'cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-emerald-600 text-white shadow-sm';
        }} else {{
          btn.className = 'cat-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap bg-[var(--sidebar)] text-[var(--muted-foreground)] hover:text-white border border-[var(--border)]';
        }}
      }});

      cards.forEach(card => {{
        if (cat === 'ALL' || card.getAttribute('data-category') === cat) {{
          card.style.display = 'flex';
        }} else {{
          card.style.display = 'none';
        }}
      }});
    }}

    function openLightbox(id) {{
      const item = catalogData.find(c => c.id === id);
      if (!item) return;
      
      const imgEl = document.getElementById('img-' + id);
      if (!imgEl) return;

      document.getElementById('lightbox-title').innerText = item.title;
      document.getElementById('lightbox-url').innerText = item.url;
      document.getElementById('lightbox-img').src = imgEl.src;
      
      const modal = document.getElementById('lightbox-modal');
      modal.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
    }}

    function closeLightbox(e) {{
      if (e.target.id === 'lightbox-modal' || e.target.id === 'lightbox-img') {{
        closeLightboxDirect();
      }}
    }}

    function closeLightboxDirect() {{
      const modal = document.getElementById('lightbox-modal');
      modal.classList.add('hidden');
      document.body.style.overflow = 'auto';
    }}
  </script>
</body>
</html>
"""

    with open(out_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Generated HTML UI gallery artifact at: {out_html_path} (Size: {len(html_content)} bytes)")

if __name__ == "__main__":
    generate()
