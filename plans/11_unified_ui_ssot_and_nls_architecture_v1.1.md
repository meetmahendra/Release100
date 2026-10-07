# Plan 11 v1.1 - Unified UI, Content SSOT and NLS (Implementation-Grade)

> **Status:** PROPOSED - supersedes the intent of `11_unified_ui_ssot_and_nls_architecture_v1.0.md` (v1.0 is kept unchanged for history).
> **Governed by:** GEES v2.0 (`ENGINEERING_EXCELLENCE_STANDARD_v2.0.md`, `GEMINI.md`, `AGENTS.md`).
> **Style:** Written so a weaker model can implement it task by task, like Plan 10.
> **Dependency:** Plan 10 (DEA) is merged or its branch is the base. Entitlements page already exists.

---

## 0. HOW TO USE THIS DOCUMENT (IMPLEMENTER RULES - READ FIRST)

1. Do **one task at a time**, in order. One local commit per task, with explicit `git add <paths>` (the tree has many unrelated uncommitted files; never `git add -A`).
2. Every new `.py` file starts with the exact Apache header: `Copyright 2026 Mahendra GURAV` (copy from any file under `core_platform/app/entitlements/`).
3. New `.py` and `.html` files are **ASCII only**. Locale JSON files are UTF-8 (needed later for Hindi/Marathi), but `en_US.json` must be ASCII.
4. Full type annotations (`mypy --strict`). Core (`core_platform/`) never imports `apps/` and contains no domain words.
5. **Never modify an existing test.** If an existing test breaks, STOP and report which test and why (see Section 8, F1).
6. Preserve existing comments and docstrings you did not need to change.
7. PowerShell: chain with `;`, never `&&`. Python is `.\.venv\Scripts\python.exe`. Full unit suite takes about 3 minutes: run it as a background task.
8. If a verify command fails twice, STOP and report. Do not improvise around a failing gate.
9. No `git push`. Present the commit list and wait for an explicit "go" (GEMINI.md rule 11).
10. Never touch `D:\mailOrganizer`, `D:\WhatsappClientForMailOrganized`, `D:\AI-ProjectManager`.
11. No real company or product names in code, copy or fixtures. Use imaginary ones (`demo`, `example.com`).

---

## 1. VERIFIED REPOSITORY FACTS (do not re-derive; if reality differs, STOP and report)

### 1.1 Template inventory (22 content templates + 2 cartridge bases)

| Area | File | Lines | Extends |
|---|---|---|---|
| core | `core_platform/app/admin_shell/templates/shell.html` | 457 | - (is the dashboard and current shell, Tailwind CDN) |
| core | `.../entitlements.html` | 448 | standalone |
| core | `.../users.html` | 322 | standalone |
| core | `.../tenants.html` | 243 | standalone |
| core | `.../logs.html` | 184 | standalone |
| core | `.../llm_costs.html` | 176 | `shell.html` |
| core | `.../login.html` | 79 | standalone |
| ops | `ops_control_plane/super_admin/templates/super_admin_tenants.html` | 814 | standalone |
| ops | `.../super_admin_audit.html` | 99 | standalone |
| mail | `apps/mail_organizer/ui/templates/base.html` | 181 | - (cartridge base, vanilla CSS) |
| mail | `dashboard.html` 495, `triage.html` 76, `drafts.html` 42, `pm_queue.html` 85, `rules.html` 42, `accounts.html` 75 | | `base.html` |
| temperature | `apps/temperature_marker/ui/templates/base.html` | 180 | - (cartridge base, vanilla CSS) |
| temperature | `monitoring.html` 920, `fleet.html` 654, `loc.html` 254 (standalone), `wizard.html` 207, `approvals.html` 117 | | `base.html` (except `loc.html`) |

### 1.2 Wiring facts
- **Four** separate `Jinja2Templates(...)` instances exist: `core_platform/app/admin_shell/routes.py:53`, `apps/mail_organizer/ui/routes.py:51`, `apps/temperature_marker/ui/routes.py:52`, `ops_control_plane/super_admin/routes.py:54`.
- Every core and ops template loads Tailwind from `https://cdn.tailwindcss.com` (offline/edge machines lose styling). Cartridge bases use hand-written CSS variables (`--bg-main`).
- `core_platform/main.py` mounts `StaticFiles` only for `/logs/media` and `/logs/photos`. There is **no** UI static mount.
- `BaseApplication` (`core_platform/app/plugin_engine/base_plugin.py`) already exposes `get_ui_router()` and (from Plan 10) `get_entitlement_manifest()`. The same pattern is used for the new hooks below.
- 32 unit-test files use `TestClient`. Several assert on rendered HTML text (`test_mail_organizer_ui.py`, `test_temperature_marker_ui.py`, `test_security_sprint_sec.py`, `test_access_control_audit.py`, `test_dea_ui.py`, others). **Changing visible wording can break them.** This drives decision D1.
- Entitlements page renders most of its text in JavaScript from JSON (`fetch`), so Jinja `t()` alone cannot translate it. This drives decision D8.
- Plan 10 manifests (`apps/*/entitlements.json`) carry English `plain_title`, `plain_description`, `summary`, `who_its_for`, `cannot_do`. This drives decision D9.

### 1.3 Existing baseline
Record the real baseline in T00 (last known: 680 passed, 5 skipped on `feature/dea-entitlements`). Use whatever T00 prints as BASELINE.

---

## 2. LOCKED DECISIONS (do not re-open)

| # | Decision |
|---|---|
| **D1** | **Two-pass migration.** *Pass A* = move text into the catalog **verbatim** and move pages onto the shared shell; rendered output must stay equivalent (verified by snapshots, T02). *Pass B* = copy-editing (new wording) happens only in Phase 7, after the user signs off the terminology (T39). No page changes wording in Pass A. |
| **D2** | Engine lives in `core_platform/app/i18n/`. Zero domain words. Cartridges own their catalogs in `apps/<app_id>/locales/<locale>.json`, discovered through a new optional `BaseApplication.get_locale_dir()` hook (default `None`). |
| **D3** | **Locales:** ship `en_US` only. Build a generated **pseudo-locale `en_XA`** (test-only, e.g. `[!! Sav3 !!]`) to prove nothing is hardcoded. Hindi (`hi_IN`) and Marathi (`mr_IN`) are scaffolded (empty catalogs fall back to `en_US`) but not translated in this plan. |
| **D4** | **Settings, not constants:** `UI_DEFAULT_LOCALE`, `UI_SUPPORTED_LOCALES`, `UI_LOCALE_COOKIE_NAME`, `UI_MISSING_KEY_POLICY` (`marker` or `key`) are typed fields in `core_platform/app/config.py`. |
| **D5** | **Key format:** `<namespace>.<area>.<name>`, lowercase snake segments, e.g. `core.entitlements.groups.title`, `apps.temperature_marker.fleet.add_kiosk`. Cartridge keys must start with `apps.<app_id>.`. A cartridge may not define keys in `core.` (rejected at load). |
| **D6** | **Interpolation and plurals:** `{name}` placeholders via a safe `format_map` (unknown placeholder renders literally, never raises). Plurals use sibling keys `<key>_one` and `<key>_other` selected by `count`. Output is HTML-escaped by Jinja autoescape; **never `\|safe` on translated text**. A guard test fails on `\|safe` applied to `t(...)`. |
| **D7** | **Missing key never raises at render.** Policy `marker` returns `[[key]]` and logs once per key; `key` returns the key. Unit tests treat any logged missing key as failure. |
| **D8** | **JavaScript text:** each page embeds the subset it needs through macro `i18n_bundle(['core.entitlements'])`, which emits `<script type="application/json" id="i18n-bundle">`. Shared `ui.js` exposes `window.t(key, vars)`. No extra route, so no extra auth surface. |
| **D9** | **Manifest text:** a cartridge manifest field may be either a plain string (legacy, English) or a **key** `{"key": "apps.mail_organizer.bundles.inbox_user.title"}`. The catalog view (Plan 10 T15) resolves keys with the viewer's locale. Pass A keeps strings; Pass B converts to keys. |
| **D10** | **Machine codes stay stable.** APIs keep returning codes such as `HIGH_RISK_CONFIRMATION_REQUIRED`. The UI maps `errors.<code_lowercase>` to a message. Unknown code shows `errors.generic`. Logs and audit keep the code. |
| **D11** | **One templating factory:** `core_platform/app/ui/templating.py::build_templates(own_dirs)` returns a `Jinja2Templates` with a `ChoiceLoader([own_dirs..., shared_dir])`, autoescape on, and globals `t`, `status_badge`, `ui`. All four existing instances are replaced by it (T08, then per-area tasks). |
| **D12** | **Shared shell:** `core_platform/app/ui/templates/base_shell.html`. Cartridge `base.html` files become **thin shims** that extend `base_shell.html` and keep their existing block names, so child templates are untouched until their own task. Standalone pages (login) use `shell_mode = "bare"`. |
| **D13** | **`UiContext` is the only source** for tenant name, slug, role label, runtime mode, locale, breadcrumbs and nav. It replaces the ad-hoc `organization` / `tenant_name` / `active_tenant` / `tenant_id` variants. During migration old variable names are still supplied for compatibility. |
| **D14** | **Status registry SSOT:** `core_platform/app/ui/status_registry.py`. Generic codes only (`active`, `inactive`, `pending`, `approved`, `rejected`, `success`, `warning`, `failed`, `off`, `shadow`, `enforce`). Cartridges add their own through optional `BaseApplication.get_ui_statuses()` (code -> tone + label key), namespaced `apps.<app_id>.status.*`. |
| **D15** | **Navigation:** cartridges declare menu items through optional `BaseApplication.get_ui_nav()` returning typed `NavItem(label_key, path, required_action)`. The shell shows an item only if the tenant has the app enabled **and** the principal passes the existing gate. Core never hardcodes cartridge names. |
| **D16** | **Offline-safe styling:** vendor the Tailwind standalone browser build as a local file served at `/ui-static/` (new mount). No CDN calls. A Node build step is explicitly out of scope. Design tokens live in `tokens.css` plus an inline Tailwind config partial; cartridge CSS variables are re-pointed to tokens. |
| **D17** | **Tone, not colour only:** badges always show text plus an icon glyph name, never colour alone (accessibility). |
| **D18** | **Copy is persona-aware.** Terminology (Pass B) is derived from the real string inventory (T01) and approved by the user (T39). Wording rules: "tamper-evident" (not "tamper-proof"); plain verbs on buttons; every input has a realistic example placeholder and one-line help. |
| **D19** | **Tracked guards (fail the build):** locale key parity, placeholder parity, no hardcoded visible text in migrated templates (allowlist file), no `\|safe` on translations, pseudo-locale render shows no un-wrapped English. |
| **D20** | Rollout is per screen behind no flag: a screen is either old or migrated. The old cartridge `base.html` stays as a shim until its last child is migrated. |

---

## 3. TARGET MODULE MAP (all new unless marked)

```text
core_platform/app/i18n/
    __init__.py
    catalog.py            I18nCatalog: load, translate, plural, fallback, bundle subset
    negotiation.py        locale negotiation (query > cookie > Accept-Language > default)
    pseudo.py             en_XA generator (test/dev only)
core_platform/app/ui/
    __init__.py
    status_registry.py    StatusRegistry + StatusInfo
    ui_context.py         UiContext, NavItem, Breadcrumb (Pydantic)
    templating.py         build_templates(), Jinja globals
    nav_builder.py        builds nav from plugin hooks + tenant + gate
    static/               tailwind.standalone.js (vendored), tokens.css, ui.js
    templates/
        base_shell.html
        components/macros.html
        components/_tokens.html
core_platform/locales/en_US.json         (new)
apps/mail_organizer/locales/en_US.json   (new)
apps/temperature_marker/locales/en_US.json (new)
core_platform/app/config.py              (modify: UI_* settings)
core_platform/app/plugin_engine/base_plugin.py (modify: get_locale_dir, get_ui_nav, get_ui_statuses)
core_platform/main.py                    (modify: mount /ui-static, locale middleware)
scripts/ui_string_inventory.py           (new, dev tool)
scripts/capture_ui_snapshots.py          (new, dev tool)
tests/ui_snapshots/baseline/*.html       (new, committed golden files)
tests/unit/test_ui_*.py                  (new)
docs/ui/string_inventory.csv             (generated, committed in T01)
docs/ui/terminology.md                   (T39)
```

---

## 4. CONTRACTS (copy exactly; later tasks reference these)

```python
# core_platform/app/ui/ui_context.py
class Breadcrumb(BaseModel):
    model_config = ConfigDict(frozen=True)
    label_key: str
    path: Optional[str] = None

class NavItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    label_key: str
    path: str
    required_action: Optional[str] = None   # DEA action id, gate decides visibility

class UiContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    locale: str
    tenant_name: str            # display name, "" if none
    tenant_slug: str            # "" if none (platform-level pages)
    principal_label: str
    role_label_key: str         # e.g. "core.role.tenant_admin"
    runtime_mode: Literal["live", "preview", "off"]
    breadcrumbs: List[Breadcrumb]
    nav: List[NavItem]
    shell_mode: Literal["full", "bare"] = "full"
```

```python
# core_platform/app/ui/status_registry.py
class StatusInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    tone: Literal["neutral", "success", "warning", "danger", "info"]
    icon: str                   # glyph name, e.g. "check", "clock", "alert"
    label_key: str              # catalog key
```

```python
# core_platform/app/i18n/catalog.py (public surface)
class I18nCatalog:
    def load_core(self, directory: Path) -> None: ...
    def load_app(self, app_id: str, directory: Path) -> None: ...      # rejects keys outside apps.<app_id>.
    def translate(self, key: str, locale: str, count: Optional[int] = None, **vars: object) -> str: ...
    def bundle(self, prefixes: Sequence[str], locale: str) -> Dict[str, str]: ...
    def keys(self, locale: str) -> FrozenSet[str]: ...
```

---

## 5. TASKS

Each task lists **Files**, **Do**, **Verify**, **Commit**. "Run unit tests" always means the targeted file(s) named plus, at gates, the full suite.

### PHASE 0 - Baseline, inventory, snapshots

**T00 Baseline.** Create branch `feature/ui-ssot-nls` from the DEA branch. Run full suite, `mypy --strict core_platform/app/entitlements`, and note BASELINE counts in the task report. No commit.

**T01 String inventory tool.**
- Files: `scripts/ui_string_inventory.py`, `docs/ui/string_inventory.csv`.
- Do: parse every `.html` under the four template folders with `html.parser`; emit one CSV row per visible text node, `placeholder`, `title`, `aria-label`, `alt` attribute: `file,line,kind,text,candidate_key`. Also scan `.js` blocks for quoted visible strings (best effort). Skip `{% %}` and `{{ }}` expressions. Print totals per file.
- Verify: run the script; CSV exists; totals printed; no crash on the 920-line `monitoring.html`.
- Commit: `feat(ui): T01 string inventory tool and baseline csv`.

**T02 Render snapshot harness.**
- Files: `scripts/capture_ui_snapshots.py`, `tests/ui_snapshots/baseline/*.html`, `tests/unit/test_ui_snapshots.py`.
- Do: in-process `TestClient(core_platform.main.app)` with a seeded tenant and JWTs from `create_jwt_token(...)`; request every page in Section 1.1 and save the HTML. Normalise: collapse whitespace, strip timestamps, nonces, CSRF/session tokens, generated ids. The test re-renders and compares to baseline. A page that needs data uses minimal seeded fixtures (0 or 1 record); clean-slate (0 records) must also render.
- Verify: `pytest tests/unit/test_ui_snapshots.py -q` passes against the untouched templates (proves determinism: run it twice).
- Commit: `feat(ui): T02 render snapshot harness and golden baseline`.
- Note: from here on, a Pass A task must keep its snapshot **equivalent after normalisation** or explain each diff in the commit body (shell chrome differences are expected only from T15 onward and are re-baselined deliberately, one page per commit).

### PHASE 1 - Engine

**T03 Settings.** `core_platform/app/config.py`: add `UI_DEFAULT_LOCALE="en_US"`, `UI_SUPPORTED_LOCALES=["en_US"]`, `UI_LOCALE_COOKIE_NAME`, `UI_MISSING_KEY_POLICY="marker"`. Test: defaults and validation (unknown policy rejected). Commit `feat(ui): T03 ui settings`.

**T04 Catalog.** `core_platform/app/i18n/catalog.py`, `core_platform/locales/en_US.json` (start with `common.*`, `core.status.*` only). Tests `tests/unit/test_ui_i18n_catalog.py`: lookup, fallback to default locale, plural `_one/_other`, interpolation with unknown placeholder, escaping not applied by catalog (Jinja does it), cartridge prefix rejection, `bundle()` subset, thread-safety smoke (two threads), missing key policies. Coverage >= 90% for the package. Commit `feat(ui): T04 i18n catalog`.

**T05 Locale negotiation.** `core_platform/app/i18n/negotiation.py` + middleware wiring in `core_platform/main.py`. Order: `?lang=` (sets cookie) > cookie > `Accept-Language` > default; only values in `UI_SUPPORTED_LOCALES` accepted. Store result on `request.state.locale`. Tests: each precedence level, unsupported value ignored, malformed header safe. Commit `feat(ui): T05 locale negotiation`.

**T06 Plugin hooks.** Modify `base_plugin.py`: add optional `get_locale_dir() -> Optional[Path]`, `get_ui_nav() -> List[NavItem]`, `get_ui_statuses() -> Dict[str, StatusInfo]`, all default empty. `PluginLoader` calls `I18nCatalog.load_app` for each cartridge that returns a directory. Keep `core_platform` free of `apps` imports (boundary test must pass). Tests: default hooks, loader registration, prefix violation raises at load. Commit `feat(ui): T06 plugin ui hooks`.

**T07 Status registry.** `status_registry.py` + generic statuses + merge of cartridge statuses (namespaced). Tests: lookup, unknown code returns neutral fallback `StatusInfo`, cartridge namespace enforced. Commit `feat(ui): T07 status registry`.

**T08 Templating factory.** `core_platform/app/ui/templating.py`. Globals: `t(key, **vars)` (reads locale from request context), `status_badge(code)`, `ui` (the `UiContext`). Replace the **admin_shell** instance only (`routes.py:53`); the other three are replaced in their own area tasks. Tests: `t` in a template, autoescape of interpolated `<script>`, `status_badge` output, loader finds shared dir. Commit `feat(ui): T08 templating factory`.

**T09 UiContext builder.** `ui_context.py` + `nav_builder.py`. Build from request: tenant (from `SecurityContext` / tenant middleware), principal, mode from `ENTITLEMENT_ENFORCEMENT_MODE` mapped to live/preview/off, nav from plugin hooks filtered by tenant-enabled apps and `required_action` through the DEA gate (fail closed: hide on error). Clean-slate: no tenant -> empty strings, no exception. Tests: three personas (platform admin, tenant admin, operator), hidden nav for disabled app, 0-tenant boot. Commit `feat(ui): T09 ui context and nav builder`.

**T10 Guard tests + pseudo-locale.** `pseudo.py`, tests `test_ui_guards.py`: key parity across locales, placeholder parity, `|safe`-on-translation scanner, hardcoded-text scanner over **migrated** templates (reads allowlist `tests/ui_guards/migrated_templates.txt`, initially empty; each migration task appends its file). Commit `feat(ui): T10 ui guards and pseudo-locale`.

**GATE A (after T10):** full suite = BASELINE + new tests, 0 failures; `mypy --strict core_platform/app/i18n core_platform/app/ui` 0 errors; coverage of both packages >= 90%; boundary and secret-leak tests pass.

### PHASE 2 - Design system

**T11 Static assets and tokens.** Vendor the Tailwind standalone browser build into `core_platform/app/ui/static/tailwind.standalone.js` (keep its MIT licence header). Add `tokens.css` and `components/_tokens.html` (palette from the audit: `slate-950` page, `slate-900` card, `slate-800` border, `emerald` primary, `indigo` devops, `amber` preview, `rose` danger). Mount `/ui-static` in `main.py`. Test: `GET /ui-static/tokens.css` is 200, file contains no `http` URL. Commit `feat(ui): T11 offline static assets and design tokens`.

**T12 Base shell.** `base_shell.html`: sidebar (from `ui.nav`), top bar (breadcrumbs, tenant badge, runtime-mode badge, user and role, locale switcher, logout), content block, alert region, `shell_mode="bare"` variant. Blocks: `title`, `extra_head`, `content`, `scripts` (match existing cartridge block names). Test: renders for full and bare, no CDN URL, `aria` landmarks present, pseudo-locale shows wrapped text. Commit `feat(ui): T12 base shell`.

**T13 Macro library.** `components/macros.html`: `kpi_card`, `data_table` (with `empty_state`), `badge` (uses registry), `form_field` (label, example placeholder, help line, error line), `modal`, `confirm_dialog` (used for privileged actions), `alert`, `empty_state`. Test: render each macro with clean-slate data; escaping test. Commit `feat(ui): T13 component macros`.

**T14 JS bundle and ui.js.** `i18n_bundle` macro + `ui.js` (`window.t`, `uiFetch` that maps error `code` to `errors.<code>` using the bundle). Test: bundle JSON is valid and contains only requested prefixes. Commit `feat(ui): T14 js i18n bundle and ui helper`.

**GATE B (after T14):** same checks as Gate A plus clean-slate boot of every page still 200 (snapshot test green because nothing migrated yet).

### PHASE 3 - Pilot (entitlements)

**T15 Entitlements, Pass A.** `entitlements.html`: extend `base_shell.html`, replace hardcoded text with `t()` keys (catalog text equals the current English **exactly**), move JS-rendered text to the bundle, append file to the migrated list in T10. Use `UiContext` for the tenant badge. Add `core.entitlements.*` to `en_US.json`. Re-baseline this page's snapshot in the same commit and describe the intentional chrome diff. Verify: `tests/unit/test_dea_ui.py` (existing, unmodified) passes; pseudo-locale test shows no raw English. Commit `feat(ui): T15 entitlements page on shared shell (pass A)`.

**T16 Entitlement error keys.** Add `errors.*` keys for every Plan 10 reason code (`high_risk_confirmation_required`, `service_group_cannot_hold_high_risk`, `scope_not_allowed`, `group_not_found`, `unknown_bundle`, plus `errors.generic`) with the **current** wording. Wire `uiFetch` mapping on this page. Test: each code maps to a non-marker message; unknown code uses `errors.generic`. Commit `feat(ui): T16 entitlement error message keys`.

**T17 PILOT GATE (user review, no code).** Present screenshots/HTML of the migrated page, the key list, and the list of snapshot diffs. **Wait for explicit user approval** before Phase 4. If rejected, fix here; do not start other screens.

### PHASE 4 - Core platform and DevOps (Pass A)

Per task: switch the page to `base_shell` (or `bare`), replace its text with keys, append to migrated list, re-baseline its snapshot, run its existing tests unmodified, one commit.
- **T18** `shell.html` (dashboard; old shell chrome moves into `base_shell`; keep `llm_costs.html` child working through block names). Also swap the remaining admin_shell template usages to the factory.
- **T19** `login.html` (`bare`). Check tenant-scoped login title still shows the tenant.
- **T20** `users.html`.
- **T21** `tenants.html`.
- **T22** `logs.html`.
- **T23** `llm_costs.html`.
- **T24** `super_admin_audit.html` (switch `ops_control_plane/super_admin/routes.py:54` to the factory; ops catalog namespace `core.ops.*` is allowed because `ops_control_plane` is platform-level, not a cartridge; confirm it holds no domain words).
- **T25** `super_admin_tenants.html` (814 lines): first split into partials `_tenant_table.html`, `_tenant_modals.html`, `_tenant_scripts.html` with **no text change** and a green snapshot, commit; then migrate keys in a second commit.

**GATE D (after T25):** full suite green (count = BASELINE + new), clean-slate boot of all core and ops pages, no CDN URL in any migrated template (`Select-String` check), guard tests green.

### PHASE 5 - Temperature Marker (Pass A)

- **T26** Replace `apps/temperature_marker/ui/routes.py:52` with the factory. Turn `base.html` into a shim extending `base_shell.html` with the same block names; map old CSS variables to tokens. Add `apps/temperature_marker/locales/en_US.json` and the plugin hooks (`get_locale_dir`, `get_ui_nav`, `get_ui_statuses`). All five children must still render unchanged.
- **T27** `approvals.html`. **T28** `wizard.html`. **T29** `loc.html` (standalone -> extend shim). **T30** `fleet.html` (654 lines; split into partials first, as in T25). **T31** `monitoring.html` (920 lines; split inline CSS into the shared tokens/css, partials first, then keys).

**GATE E (after T31):** same as Gate D plus `python run_live_benchmark.py --domain=temperature_marker --quality-gate` passes.

### PHASE 6 - Mail Organizer (Pass A)

- **T32** factory swap at `apps/mail_organizer/ui/routes.py:51`, `base.html` shim, locale file, plugin hooks.
- **T33** `accounts.html`. **T34** `drafts.html`. **T35** `rules.html`. **T36** `triage.html`. **T37** `pm_queue.html`. **T38** `dashboard.html` (495 lines; partials first).

**GATE F (after T38):** full suite, all migrated pages in the guard allowlist, `--domain=mail_organizer --quality-gate` and `--domain=entitlements --quality-gate` pass, `--domain=temperature_marker` still passes.

### PHASE 7 - Pass B (copy improvement)

**T39 Terminology approval (user gate, no code).** From `docs/ui/string_inventory.csv` produce `docs/ui/terminology.md`: for each flagged string, current text, proposed text, persona (DevOps, customer admin, operator), and reason. Only strings that are **actually shown** appear. Rules: D18. Present to the user; **wait for explicit approval**, row by row if needed.

**T40-T42 Apply approved copy** (core, temperature, mail). Edit only `en_US.json` values (templates are already key-based, which is the payoff of D1). For each existing test that now fails because of new wording, list it for the user **before** touching it; changing an existing test requires the user's explicit approval in that message. Re-baseline snapshots in the same commit. Commits: `feat(ui): T40 approved copy - core`, `T41 ... temperature`, `T42 ... mail`.

Optional follow-up (not in this plan): convert Plan 10 manifest text to keys (D9 Pass B).

### PHASE 8 - Documentation and final gate

**T43 Docs (append only).** `ARCHITECTURE.md` section "UI Shell, Content SSOT and NLS"; `USER_MANUAL.md` short "Language and display" note; `OPERATIONS_MANUAL.md` "Adding a language" (copy `en_US.json`, translate, add to `UI_SUPPORTED_LOCALES`, run parity test) and "Adding a screen" (extend shell, keys, allowlist, snapshot). Commit `docs(ui): T43 ui architecture and operations notes`.

**T44 Final gate (Definition of Done).** Report with numbers:
1. Full `pytest tests/unit -q` = BASELINE + new tests, 0 failures, 0 existing tests modified unless approved in T40-T42 (list them).
2. `mypy --strict core_platform/app/i18n core_platform/app/ui` 0 errors.
3. Coverage of `i18n` and `ui` packages >= 90%.
4. Boundary and secret-leak tests pass.
5. Quality gate for all three domains: 100% safety, >= 80% functional, reports written.
6. Guards green: key parity, placeholder parity, hardcoded-text scanner over all 22 pages, no `|safe` on translations, pseudo-locale shows no raw English.
7. No page loads anything from a CDN (`Select-String "cdn\.|unpkg|googleapis"` returns nothing).
8. Clean-slate boot (0 tenants, 0 users): every page returns 200/redirect, never 500.
Then `git log --oneline`, present the list, **wait for explicit "go"** before any push.

---

## 6. SCREEN COVERAGE CHECK (every page appears exactly once)

core: `shell` T18, `login` T19, `users` T20, `tenants` T21, `logs` T22, `llm_costs` T23, `entitlements` T15.
ops: `super_admin_audit` T24, `super_admin_tenants` T25.
temperature: `approvals` T27, `wizard` T28, `loc` T29, `fleet` T30, `monitoring` T31.
mail: `accounts` T33, `drafts` T34, `rules` T35, `triage` T36, `pm_queue` T37, `dashboard` T38.
Bases: temperature T26, mail T32 (shims). Total 22 pages.

---

## 7. TEST MATRIX (must exist before the matching gate)

| Area | Tests |
|---|---|
| Catalog | fallback, plural, unknown placeholder, prefix rejection, missing-key policies, bundle subset, thread smoke |
| Negotiation | precedence, unsupported locale, malformed header |
| Security | XSS payload in interpolated value is escaped on page and in JS bundle; no `|safe` on translations; cartridge cannot define `core.` keys; nav hidden (not just disabled) without permission |
| Shell | full and bare render, landmarks, no CDN, tenant badge from `UiContext`, clean-slate 0 tenants |
| Macros | each macro with empty data; badge never colour-only |
| Guards | key parity, placeholder parity, hardcoded-text scanner, pseudo-locale |
| Snapshots | every page deterministic (run twice), clean-slate variant |
| Boundary | `core_platform` still imports nothing from `apps/` (existing AST test) |

---

## 8. FAILURE PLAYBOOK

| # | Symptom | Action |
|---|---|---|
| F1 | An **existing** test fails after a Pass A task | Do not edit the test. Compare snapshot diff; Pass A must not change visible text. Fix the template or catalog value so text is identical. If the test checks structure (an id or class), keep that id or class. Still failing twice: STOP and report. |
| F2 | Snapshot differs run to run | Add the volatile token to the normaliser in `capture_ui_snapshots.py` (timestamps, nonces, ids). Do not loosen comparisons beyond that. |
| F3 | Child template breaks after a base shim | The shim must expose every block name the children use. Diff block names in old `base.html` vs shim. |
| F4 | `[[key]]` appears on a page | Key missing from `en_US.json`. Add it with the exact original text. Never edit the template back to hardcoded text. |
| F5 | Boundary test fails | `core_platform` imported from `apps/`. Move the code behind a plugin hook (`get_locale_dir`, `get_ui_nav`, `get_ui_statuses`). |
| F6 | Page 500 on clean slate | `UiContext` must tolerate no tenant/no principal (empty strings). Fix the builder, not the page. |
| F7 | Styling vanishes offline | A template still references a CDN. Replace with `/ui-static/` assets (T11). |
| F8 | Tailwind classes do not apply | The vendored standalone build needs the inline config partial `_tokens.html` before the script tag. |
| F9 | Large template (>400 lines) migration gets messy | Split into partials in a no-text-change commit first, keep snapshot green, then migrate keys. |
| F10 | Verify fails twice | STOP and report command, output and your hypothesis. |

---

## 9. LATER PHASES (not part of this plan)

- Real translations (`hi_IN`, `mr_IN`) and a translator workflow.
- Right-to-left layout support.
- Date, number and currency formatting by locale (add Babel only when a second real locale ships).
- Node/Tailwind build pipeline replacing the vendored standalone script.
- Converting Plan 10 manifest text to catalog keys (D9 Pass B).
- Per-tenant branding (logo, accent colour) on top of tokens.

---

## 10. CHANGES FROM v1.0 (why this version exists)

- Removed the fake Gantt dates and "done" statuses.
- Added verified repository facts, locked decisions, contracts, per-task verify steps, gates, test matrix and failure playbook.
- Split copy changes from code moves (D1), because existing tests assert on text and may not be edited.
- Added the data SSOT (`UiContext`), JavaScript text handling, offline-safe styling, design tokens, pseudo-locale and guard tests.
- Covered all 22 pages including the two `ops_control_plane` pages.
- Made terminology data-driven (inventory first) and user-approved (T39) instead of a guessed table.
- Replaced the overclaim "tamper-proof" with "tamper-evident".
