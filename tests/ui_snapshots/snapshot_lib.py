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

"""Normalised render snapshots of every UI page (Plan 11, T02).

The snapshot is a line-per-tag skeleton of the rendered HTML with volatile data
(dates, times, numbers, ids, tokens) replaced by placeholders and table bodies
collapsed. It is deterministic across runs and yields a readable ``git diff`` when a
template changes. Used to prove Pass A migrations keep the page equivalent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi.testclient import TestClient

from core_platform.app.auth.jwt_utils import create_jwt_token

BASELINE_DIR = Path(__file__).resolve().parent / "baseline"
ADMIN_APPS = ["all", "mail_organizer", "temperature_marker"]
TM_BASE = "/admin/apps/temperature-marker"
MAIL_BASE = "/admin/apps/mail-organizer"


@dataclass(frozen=True)
class PageSpec:
    """One page to snapshot.

    Attributes:
        name: Stable snapshot file stem.
        path: Request path.
        persona: ``anonymous``, ``admin`` or ``devops``.
    """

    name: str
    path: str
    persona: str


PAGES: Tuple[PageSpec, ...] = (
    PageSpec("core_login", "/admin/login", "anonymous"),
    PageSpec("core_dashboard", "/admin/", "admin"),
    PageSpec("core_api_keys", "/admin/api-keys", "admin"),
    PageSpec("core_users", "/admin/users", "admin"),
    PageSpec("core_tenants", "/admin/tenants", "admin"),
    PageSpec("core_logs", "/admin/logs", "admin"),
    PageSpec("core_llm_costs", "/admin/llm-costs", "admin"),
    PageSpec("core_entitlements", "/admin/entitlements/", "admin"),
    PageSpec("ops_tenants", "/ops/tenants", "devops"),
    PageSpec("tm_fleet", TM_BASE + "/fleet", "admin"),
    PageSpec("tm_wizard", TM_BASE + "/wizard", "admin"),
    PageSpec("tm_approvals", TM_BASE + "/approvals", "admin"),
    PageSpec("tm_verify_location", TM_BASE + "/verify-location", "admin"),
    PageSpec("tm_monitoring", TM_BASE + "/monitoring", "admin"),
    PageSpec("mail_dashboard", MAIL_BASE + "/dashboard", "admin"),
    PageSpec("mail_triage", MAIL_BASE + "/triage", "admin"),
    PageSpec("mail_pm_queue", MAIL_BASE + "/pm-queue", "admin"),
    PageSpec("mail_rules", MAIL_BASE + "/rules", "admin"),
    PageSpec("mail_drafts", MAIL_BASE + "/drafts", "admin"),
    PageSpec("mail_accounts", MAIL_BASE + "/accounts", "admin"),
)

# Volatile-value patterns, applied in order.
_VOLATILE: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"), "<TOKEN>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<HEX>"),
    (
        re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
        "<TS>",
    ),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "<DATE>"),
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?: ?[AaPp][Mm])?"), "<TIME>"),
    (re.compile(r"\d+"), "#"),
)
_VOLATILE_ATTRS = frozenset({"nonce", "csrf-token", "data-csrf"})
_WS = re.compile(r"\s+")


def _scrub(text: str) -> str:
    """Replace volatile values in ``text`` with stable placeholders."""
    for pattern, replacement in _VOLATILE:
        text = pattern.sub(replacement, text)
    return text


class _Skeleton(HTMLParser):
    """Render HTML as a normalised line-per-token skeleton."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: List[str] = []
        self._stack: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if self._skip_depth:
            if tag == "tbody":
                self._skip_depth += 1
            return
        parts: List[str] = []
        for name, value in sorted(attrs, key=lambda item: item[0]):
            if name in _VOLATILE_ATTRS or (tag == "input" and name == "value" and _is_token(attrs)):
                parts.append(f'{name}="<TOKEN>"')
            elif value is None:
                parts.append(name)
            else:
                parts.append(f'{name}="{_scrub(_WS.sub(" ", value).strip())}"')
        self.lines.append("<" + " ".join([tag] + parts) + ">")
        self._stack.append(tag)
        if tag == "tbody":
            self._skip_depth = 1
            self.lines.append("...")

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if not self._skip_depth and self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag == "tbody":
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self.lines.append("</tbody>")
                    if "tbody" in self._stack:
                        self._stack.remove("tbody")
            return
        self.lines.append(f"</{tag}>")
        while self._stack:
            if self._stack.pop() == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        current = self._stack[-1] if self._stack else ""
        if current in ("script", "style"):
            for raw in data.splitlines():
                stripped = raw.strip()
                if stripped:
                    self.lines.append("  " + _scrub(stripped))
            return
        collapsed = _WS.sub(" ", data).strip()
        if collapsed:
            self.lines.append("  " + _scrub(collapsed))


def _is_token(attrs: List[Tuple[str, Optional[str]]]) -> bool:
    """Return True if an input's ``name`` attribute looks like a CSRF/session token."""
    for name, value in attrs:
        if name == "name" and value and ("csrf" in value.lower() or "token" in value.lower()):
            return True
    return False


def normalize_html(html: str) -> str:
    """Return the normalised skeleton of ``html`` (deterministic, newline separated)."""
    # Employee-roster options come from the shared DB and vary with test order.
    html = re.sub(r"<option[^>]*value=""EMP-[^""]*""[^>]*>.*?</option>", "", html, flags=re.S)
    parser = _Skeleton()
    parser.feed(html)
    parser.close()
    return "\n".join(parser.lines) + "\n"


def make_client(persona: str) -> TestClient:
    """Build an in-process client for the given persona (does not follow redirects)."""
    from core_platform.main import app

    client = TestClient(app, follow_redirects=False)
    if persona == "admin":
        client.cookies.set("admin_token", create_jwt_token("admin", ["admin"], list(ADMIN_APPS)))
    elif persona == "devops":
        client.cookies.set(
            "admin_token",
            create_jwt_token(
                principal_id="devops_admin",
                roles=["admin", "devops_admin"],
                permitted_apps=["mail_organizer", "temperature_marker"],
                tenant_id="platform",
            ),
        )
    return client


def capture_page(spec: PageSpec) -> str:
    """Request one page and return its snapshot text (with a status header line)."""
    client = make_client(spec.persona)
    response = client.get(spec.path, headers={"Accept": "text/html"})
    if response.status_code != 200:
        return f"STATUS {response.status_code}\n"
    return "STATUS 200\n" + normalize_html(response.text)


def capture_all() -> Dict[str, str]:
    """Capture every page in :data:`PAGES`, keyed by snapshot name."""
    return {spec.name: capture_page(spec) for spec in PAGES}


def baseline_path(name: str) -> Path:
    """Return the baseline file path for snapshot ``name``."""
    return BASELINE_DIR / f"{name}.html"


def write_baselines(snapshots: Dict[str, str]) -> List[Path]:
    """Write snapshots to the baseline directory and return the paths written."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for name, text in sorted(snapshots.items()):
        target = baseline_path(name)
        target.write_text(text, encoding="utf-8", newline="\n")
        written.append(target)
    return written
