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

"""Inventory every visible UI string in the HTML templates (Plan 11, T01).

Writes ``docs/ui/string_inventory.csv`` with one row per visible text node,
user-visible attribute (placeholder, title, aria-label, alt) and best-effort
quoted string inside ``<script>`` blocks. Jinja expressions are removed first.

Usage:
    python scripts/ui_string_inventory.py
"""

from __future__ import annotations

import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = REPO_ROOT / "docs" / "ui" / "string_inventory.csv"

# (template root relative to repo, key namespace)
TEMPLATE_ROOTS: Tuple[Tuple[str, str], ...] = (
    ("core_platform/app/admin_shell/templates", "core"),
    ("ops_control_plane/super_admin/templates", "core.ops"),
    ("apps/mail_organizer/ui/templates", "apps.mail_organizer"),
    ("apps/temperature_marker/ui/templates", "apps.temperature_marker"),
)

VISIBLE_ATTRS = ("placeholder", "title", "aria-label", "alt")
JINJA_EXPR = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
SCRIPT_STRING = re.compile(r"""(["'`])((?:(?!\1)[^\\\n]){3,140})\1""")
HAS_LETTER = re.compile(r"[A-Za-z]")
CSS_OR_CODE = re.compile(r"^[#.\[\]a-z0-9_:>\-/=,. ()%\"']+$")
SKIP_TAGS = ("style",)


def _slug(text: str, words: int = 4) -> str:
    """Build a lowercase snake_case slug from the first few words of ``text``."""
    parts = re.findall(r"[A-Za-z0-9]+", text.lower())[:words]
    return "_".join(parts) or "text"


class _Collector(HTMLParser):
    """Collect (line, kind, text) tuples from one template."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[Tuple[int, str, str]] = []
        self._stack: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._stack.append(tag)
        for name, value in attrs:
            if name in VISIBLE_ATTRS and value:
                cleaned = JINJA_EXPR.sub(" ", value).strip()
                if HAS_LETTER.search(cleaned):
                    self.rows.append((self.getpos()[0], "attr:" + name, cleaned))

    def handle_endtag(self, tag: str) -> None:
        while self._stack:
            if self._stack.pop() == tag:
                break

    def handle_data(self, data: str) -> None:
        current = self._stack[-1] if self._stack else ""
        line = self.getpos()[0]
        if current in SKIP_TAGS:
            return
        if current == "script":
            for match in SCRIPT_STRING.finditer(data):
                candidate = match.group(2).strip()
                if self._script_candidate(candidate):
                    offset = data.count("\n", 0, match.start())
                    self.rows.append((line + offset, "script", candidate))
            return
        cleaned = " ".join(JINJA_EXPR.sub(" ", data).split())
        if HAS_LETTER.search(cleaned):
            self.rows.append((line, "text", cleaned))

    @staticmethod
    def _script_candidate(text: str) -> bool:
        """Keep only strings that look like human sentences, not code or CSS."""
        if "{{" in text or "${" in text or "http" in text or "/" in text.split(" ")[0]:
            return False
        if ";" in text or text.startswith(")") or "setAttribute" in text:
            return False
        if " " not in text or not HAS_LETTER.search(text):
            return False
        return CSS_OR_CODE.match(text) is None or text[0].isupper()


def scan_template(path: Path) -> List[Tuple[int, str, str]]:
    """Return the visible-string rows of one template file."""
    collector = _Collector()
    collector.feed(path.read_text(encoding="utf-8"))
    return collector.rows


def build_inventory() -> List[Dict[str, str]]:
    """Scan every configured template root and return CSV row dictionaries."""
    rows: List[Dict[str, str]] = []
    for relative_root, namespace in TEMPLATE_ROOTS:
        root = REPO_ROOT / relative_root
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.html")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            for line, kind, text in scan_template(path):
                rows.append(
                    {
                        "file": rel,
                        "line": str(line),
                        "kind": kind,
                        "text": text,
                        "candidate_key": f"{namespace}.{path.stem}.{_slug(text)}",
                    }
                )
    return rows


def main() -> int:
    """Write the CSV and print per-file totals (ASCII only)."""
    rows = build_inventory()
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["file", "line", "kind", "text", "candidate_key"]
        )
        writer.writeheader()
        writer.writerows(rows)
    totals: Dict[str, int] = {}
    for row in rows:
        totals[row["file"]] = totals.get(row["file"], 0) + 1
    for file_name, count in sorted(totals.items()):
        sys.stdout.write(f"[INVENTORY] {count:5d}  {file_name}\n")
    sys.stdout.write(f"[SUCCESS] {len(rows)} strings in {len(totals)} files -> {OUTPUT_CSV}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
