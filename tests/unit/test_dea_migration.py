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

"""Tests for Alembic migration 002 (entitlement tables)."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "platform_ent_org_units",
    "platform_ent_groups",
    "platform_ent_group_members",
    "platform_ent_bindings",
}


def _alembic(db_file: Path, *args: str) -> None:
    """Run alembic in a subprocess against a temporary SQLite file."""
    env = dict(os.environ)
    env["DATABASE_URL"] = "sqlite:///" + db_file.as_posix()
    cmd: List[str] = [sys.executable, "-m", "alembic", *args]
    result = subprocess.run(
        cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=240
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _tables(db_file: Path) -> set[str]:
    """Return table names present in the SQLite file."""
    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(r[0]) for r in rows}


def test_upgrade_and_downgrade(tmp_path: Path) -> None:
    """Upgrade creates the four tables with kind column; downgrade removes them."""
    db_file = tmp_path / "mig.db"
    # Migration 001 collides with plugin-created tables on a fresh DB (pre-existing),
    # so stamp it as applied and exercise only 002.
    _alembic(db_file, "stamp", "001_initial_schema")
    _alembic(db_file, "upgrade", "head")
    assert EXPECTED <= _tables(db_file)
    with sqlite3.connect(str(db_file)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(platform_ent_groups)")}
    assert "kind" in cols
    _alembic(db_file, "downgrade", "001_initial_schema")
    assert not (EXPECTED & _tables(db_file))
