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
GEES v2.0 Pillar 8 Automated Zero-Secret Leak Guard.

Continuously scans all git-tracked repository source files, tests, documentation, and config templates
to verify:
  1. No real cloud provider API keys (Google AI Studio, Meta WhatsApp, GitHub, AWS, OpenAI, RSA keys)
     exist in tracked source code, unit tests, or fixtures.
  2. No active secrets/tokens from the local .env file have leaked into tracked files.
  3. All test fixtures and mocks use strictly synthetic dummy tokens (e.g. mock_*).
"""

from pathlib import Path
import re
import subprocess
from typing import List, Set, Tuple
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

# Live Secret Regex Signatures (Provider Automated Scanners)
SECRET_PATTERNS = [
    ("Google Gemini / AI Studio API Key", re.compile(r"AIza[0-9A-Za-z-_]{35}")),
    ("Google OAuth / Service Account Token", re.compile(r"AQ\.[0-9A-Za-z-_]{30,}")),
    ("Meta / WhatsApp Cloud API Access Token", re.compile(r"EAA[0-9A-Za-z]{80,}")),
    ("GitHub Personal Access Token", re.compile(r"ghp_[0-9A-Za-z]{36}")),
    ("AWS Access Key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("OpenAI API Key", re.compile(r"sk-[0-9a-zA-Z]{32,}")),
    ("RSA / EC Private Key", re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PRIVATE) KEY-----")),
]

IGNORED_EXTENSIONS = {
    ".pyc",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".zip",
    ".tar.gz",
    ".whl",
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
    ".onnx",
    ".lib",
    ".dll",
    ".exe",
    ".pyd",
    ".bin",
}

SENSITIVE_KEY_SUBSTRINGS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PRIVATE",
    "CREDENTIAL",
    "AUTH",
)


def get_tracked_files() -> List[Path]:
    """Retrieve all tracked repository files via git ls-files, filtering binary extensions."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            check=True,
        )
        files: List[Path] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            p = ROOT_DIR / line
            if p.is_file() and p.suffix.lower() not in IGNORED_EXTENSIONS:
                files.append(p)
        return files
    except Exception:
        # Fallback to rglob if git is not available in test runner
        fallback: List[Path] = []
        ignored_dirs = {".git", ".venv", "venv", "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache", "logs", ".databases", "config_backups"}
        for path in ROOT_DIR.rglob("*"):
            if path.is_file() and not any(part in ignored_dirs for part in path.parts):
                if path.suffix.lower() not in IGNORED_EXTENSIONS and not path.name.startswith(".env"):
                    fallback.append(path)
        return fallback


def test_zero_real_credentials_in_tracked_code() -> None:
    """GEES v2.0 Pillar 8: Verify no live cloud credentials exist in any tracked repository file."""
    files = get_tracked_files()
    assert len(files) > 20, "Repository scan failed to find codebase files."

    violations: List[Tuple[str, str, int, str]] = []

    for file_path in files:
        if file_path.name == "test_zero_secret_leak_guard.py":
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for label, pattern in SECRET_PATTERNS:
            for line_idx, line in enumerate(content.splitlines(), start=1):
                match = pattern.search(line)
                if match:
                    violations.append(
                        (str(file_path.relative_to(ROOT_DIR)), label, line_idx, match.group(0))
                    )

    if violations:
        error_lines = [
            f"\n[SECURITY BREACH] Detected {len(violations)} live secret pattern(s) in repository files:"
        ]
        for rel_path, label, line_num, secret_match in violations:
            masked = secret_match[:6] + "..." + secret_match[-4:] if len(secret_match) > 10 else "***"
            error_lines.append(f"  - {rel_path}:{line_num} -> {label} (Found: {masked})")
        error_lines.append("\nAll test fixtures MUST use purely synthetic strings (e.g. mock_gemini_test_key_12345).")
        pytest.fail("\n".join(error_lines))


def test_local_env_secrets_not_leaked_to_tracked_files() -> None:
    """GEES v2.0 Pillar 8: Ensure actual secrets in local .env are never present in tracked code."""
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        pytest.skip("No local .env file present to audit.")

    raw_env = env_file.read_text(encoding="utf-8")
    real_secrets: List[Tuple[str, str]] = []

    for line in raw_env.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip().upper()
        val = val.strip().strip("'\"")

        # Only check keys that represent secret credentials/keys
        if not any(sub in key for sub in SENSITIVE_KEY_SUBSTRINGS):
            continue

        # Skip dummy placeholders
        if val.startswith(("mock_", "test_", "placeholder_", "change_", "dummy_")) or len(val) < 15:
            continue

        real_secrets.append((key, val))

    if not real_secrets:
        return

    files = get_tracked_files()
    leaks: List[str] = []

    for file_path in files:
        if file_path.name == "test_zero_secret_leak_guard.py":
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for key_name, secret in real_secrets:
            if secret in content:
                leaks.append(f"{file_path.relative_to(ROOT_DIR)} contains active .env secret for '{key_name}': {secret[:6]}...{secret[-4:]}")

    assert not leaks, f"Local .env credentials detected in tracked repository files:\n" + "\n".join(leaks)
