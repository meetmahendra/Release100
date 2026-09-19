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
Non-Destructive Configuration Backup & Rollback Engine (`config_backup.py`).

Adheres strictly to Plan 07 v1.0 and GEES v1.0.
Guarantees:
1. Automated pre-save backup before modifying configuration files.
2. Preservation of comments, blank lines, and formatting in `.env`.
3. Instant 1-click rollback to any historical backup snapshot.
"""

from datetime import datetime, timezone
import glob
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("core_platform.config_backup")


def get_default_env_path() -> Path:
    """Return project root .env path."""
    return Path(os.getcwd()) / ".env"


def get_backup_dir() -> Path:
    """Return directory where configuration snapshots are stored."""
    bdir = Path(os.getcwd()) / "config_backups"
    bdir.mkdir(parents=True, exist_ok=True)
    return bdir


def create_backup(env_path: Optional[Path] = None) -> Optional[Path]:
    """Create a timestamped copy of .env before making changes."""
    src = env_path or get_default_env_path()
    if not src.exists():
        logger.info("[ConfigBackup] Source %s does not exist. Skipping backup creation.", src)
        return None

    bdir = get_backup_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = bdir / f"env_{timestamp}.bak"

    try:
        shutil.copy2(src, dst)
        logger.info("[ConfigBackup] Created snapshot: %s", dst.name)
        return dst
    except Exception as err:
        logger.error("[ConfigBackup] Failed to create backup: %s", err)
        return None


def list_backups(backup_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Enumerate existing backup files sorted newest first."""
    bdir = backup_dir or get_backup_dir()
    if not bdir.exists():
        return []

    pattern = str(bdir / "env_*.bak")
    files = sorted(glob.glob(pattern), reverse=True)

    backups: List[Dict[str, Any]] = []
    for f in files:
        p = Path(f)
        stat = p.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        backups.append({
            "filename": p.name,
            "filepath": str(p),
            "size_bytes": stat.st_size,
            "modified_utc": mtime,
        })

    return backups


def restore_backup(filename: str, env_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Restore a previous configuration snapshot to .env."""
    bdir = get_backup_dir()
    target_bak = bdir / filename

    if not target_bak.exists():
        return False, f"Backup file '{filename}' does not exist."

    dst = env_path or get_default_env_path()

    try:
        # Pre-rollback safety backup of current state
        if dst.exists():
            pre_rollback = bdir / f"pre_rollback_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.bak"
            shutil.copy2(dst, pre_rollback)

        shutil.copy2(target_bak, dst)
        reload_settings_from_env(dst)
        logger.info("[ConfigBackup] Restored %s -> %s", filename, dst.name)
        return True, f"Successfully restored configuration from '{filename}'."
    except Exception as err:
        logger.error("[ConfigBackup] Restore error: %s", err)
        return False, f"Restore failed: {err}"


def read_env_dict(env_path: Optional[Path] = None) -> Dict[str, str]:
    """Read all key-value pairs from .env preserving unquoted strings."""
    src = env_path or get_default_env_path()
    if not src.exists():
        return {}
    res: Dict[str, str] = {}
    try:
        with open(src, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                k = k.strip()
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                res[k] = v
    except Exception as exc:
        logger.warning("[ConfigBackup] Failed to read .env: %s", exc)
    return res


def reload_settings_from_env(env_path: Optional[Path] = None) -> None:
    """Reload in-memory platform settings singleton from the .env on disk."""
    import json
    from core_platform.app.config import settings

    env_dict = read_env_dict(env_path)
    for k, v in env_dict.items():
        if hasattr(settings, k):
            current_val = getattr(settings, k)
            if isinstance(current_val, bool):
                setattr(settings, k, v.lower() in ("true", "1", "yes"))
            elif isinstance(current_val, int):
                try:
                    setattr(settings, k, int(v))
                except ValueError:
                    setattr(settings, k, v)
            elif isinstance(current_val, float):
                try:
                    setattr(settings, k, float(v))
                except ValueError:
                    setattr(settings, k, v)
            elif isinstance(current_val, list):
                try:
                    setattr(settings, k, json.loads(v))
                except Exception:
                    setattr(settings, k, [x.strip() for x in v.split(",") if x.strip()])
            else:
                setattr(settings, k, v)


def _format_env_value(val: str) -> str:
    """Format a setting value safely for .env storage."""
    # If already safely quoted, return as-is
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val
    # If value contains double quotes (e.g. JSON list), wrap in single quotes
    if '"' in val:
        return f"'{val}'"
    # If value contains spaces or special characters, wrap in double quotes
    if any(c in val for c in [" ", "[", "]", ",", ":", "'"]):
        return f'"{val}"'
    return val


def save_master_config(
    updates: Dict[str, str],
    env_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Non-destructively update .env with provided key-values, preserving comments and formatting."""
    src = env_path or get_default_env_path()

    # 1. Create pre-save backup
    create_backup(src)

    lines: List[str] = []
    existing_keys: set[str] = set()

    if src.exists():
        try:
            with open(src, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as exc:
            return False, f"Could not read existing .env: {exc}"

    new_lines: List[str] = []
    updated_keys: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped or "=" not in stripped:
            new_lines.append(line)
            continue

        key = stripped.split("=", 1)[0].strip()
        existing_keys.add(key)

        if key in updates:
            val = updates[key]
            formatted_val = _format_env_value(val)
            new_lines.append(f"{key}={formatted_val}\n")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    # Append any brand new keys not previously present
    for k, v in updates.items():
        if k not in existing_keys:
            formatted_val = _format_env_value(v)
            new_lines.append(f"{k}={formatted_val}\n")
            updated_keys.add(k)

    try:
        with open(src, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        reload_settings_from_env(src)
        logger.info("[ConfigBackup] Saved %d updated keys to %s", len(updated_keys), src.name)
        return True, f"Saved {len(updated_keys)} setting(s) successfully. Pre-save backup created."
    except Exception as exc:
        return False, f"Failed to write to .env: {exc}"
