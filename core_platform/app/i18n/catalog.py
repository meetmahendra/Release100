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

"""Translation catalog for the unified UI (Plan 11, T04).

Loads hierarchical JSON locale files into flat dotted keys, resolves them with locale
fallback, simple plurals and safe ``{name}`` interpolation. Missing keys never raise at
render time (policy ``marker`` or ``key``); each missing key is logged once.

Catalog files are named ``<locale>.json`` (for example ``en_US.json``). Core files may
not define keys under ``apps.``; a cartridge file for ``app_id`` may only define keys
under ``apps.<app_id>.`` so a cartridge can never override core text.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Dict, FrozenSet, Literal, Mapping, Optional, Sequence, Set

logger = logging.getLogger("core_platform.i18n")

MissingPolicy = Literal["marker", "key"]

_LOCALE_RE = re.compile(r"[a-z]{2,3}_[A-Z]{2}")
_SEGMENT_RE = re.compile(r"[a-z0-9_]+")
_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_APP_NAMESPACE = "apps"


class CatalogError(ValueError):
    """Raised when a locale file is malformed or violates namespace rules."""


def _flatten(prefix: str, node: object, out: Dict[str, str], source: str) -> None:
    """Flatten a nested JSON object into dotted keys, validating segments and values."""
    if isinstance(node, str):
        out[prefix] = node
        return
    if not isinstance(node, dict):
        raise CatalogError(f"{source}: value for '{prefix}' must be a string or object")
    for segment, child in node.items():
        if not isinstance(segment, str) or _SEGMENT_RE.fullmatch(segment) is None:
            raise CatalogError(f"{source}: invalid key segment '{segment}' under '{prefix}'")
        key = f"{prefix}.{segment}" if prefix else segment
        _flatten(key, child, out, source)


class I18nCatalog:
    """Thread-safe locale catalog with fallback, plurals and safe interpolation."""

    def __init__(self, default_locale: str = "en_US", missing_policy: MissingPolicy = "marker") -> None:
        """Create an empty catalog.

        Args:
            default_locale: Locale used when a key is absent in the requested locale.
            missing_policy: ``marker`` renders ``[[key]]``; ``key`` renders the key.
        """
        self._default = default_locale
        self._policy: MissingPolicy = missing_policy
        self._entries: Dict[str, Dict[str, str]] = {}
        self._reported: Set[str] = set()
        self._lock = threading.RLock()

    @property
    def default_locale(self) -> str:
        """Return the fallback locale code."""
        return self._default

    def clear(self) -> None:
        """Remove every loaded entry and the missing-key history."""
        with self._lock:
            self._entries.clear()
            self._reported.clear()

    def load_core(self, directory: Path) -> None:
        """Load every ``<locale>.json`` from ``directory`` as core catalogs.

        A missing directory is tolerated (clean-slate boot) and only logged.
        """
        for locale, entries in self._read_directory(directory).items():
            for key in entries:
                if key.split(".", 1)[0] == _APP_NAMESPACE:
                    raise CatalogError(f"{directory}: core catalog may not define '{key}'")
            self.register_entries(locale, entries)

    def load_app(self, app_id: str, directory: Path) -> None:
        """Load a cartridge's catalogs; keys must live under ``apps.<app_id>.``."""
        prefix = f"{_APP_NAMESPACE}.{app_id}."
        for locale, entries in self._read_directory(directory).items():
            for key in entries:
                if not key.startswith(prefix):
                    raise CatalogError(f"{directory}: key '{key}' must start with '{prefix}'")
            self.register_entries(locale, entries)

    def register_entries(self, locale: str, entries: Mapping[str, str]) -> None:
        """Merge flat ``entries`` into ``locale``; a duplicate key is an error."""
        if _LOCALE_RE.fullmatch(locale) is None:
            raise CatalogError(f"invalid locale code '{locale}'")
        with self._lock:
            bucket = self._entries.setdefault(locale, {})
            for key, value in entries.items():
                if key in bucket:
                    raise CatalogError(f"duplicate key '{key}' for locale '{locale}'")
            bucket.update(entries)

    def locales(self) -> FrozenSet[str]:
        """Return the locales that have at least one entry."""
        with self._lock:
            return frozenset(self._entries)

    def keys(self, locale: str) -> FrozenSet[str]:
        """Return every key defined for ``locale`` (empty set if unknown)."""
        with self._lock:
            return frozenset(self._entries.get(locale, {}))

    def missing_keys(self) -> FrozenSet[str]:
        """Return keys that were requested but not found (reported once each)."""
        with self._lock:
            return frozenset(self._reported)

    def translate(self, key: str, locale: str, count: Optional[int] = None, **variables: object) -> str:
        """Resolve ``key`` for ``locale`` with fallback, plural selection and interpolation.

        Args:
            key: Dotted catalog key.
            locale: Requested locale code.
            count: When given, ``<key>_one`` (count == 1) or ``<key>_other`` is preferred
                and ``{count}`` is available for interpolation.
            **variables: Values for ``{name}`` placeholders. Values are inserted as-is
                and never re-interpreted; HTML escaping is the template engine's job.

        Returns:
            The localized string, or the missing-key rendering when absent everywhere.
        """
        template = self._lookup(key, locale, count)
        if template is None:
            return self._render_missing(key)
        values: Dict[str, object] = dict(variables)
        if count is not None:
            values.setdefault("count", count)
        return _PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)

    def bundle(self, prefixes: Sequence[str], locale: str) -> Dict[str, str]:
        """Return raw templates whose key starts with any prefix (default locale merged under)."""
        with self._lock:
            merged: Dict[str, str] = {}
            for source in (self._default, locale):
                for key, value in self._entries.get(source, {}).items():
                    if any(key == p or key.startswith(p + ".") for p in prefixes):
                        merged[key] = value
            return merged

    def _lookup(self, key: str, locale: str, count: Optional[int]) -> Optional[str]:
        candidates = [key]
        if count is not None:
            candidates.insert(0, f"{key}_{'one' if count == 1 else 'other'}")
        with self._lock:
            for source in dict.fromkeys((locale, self._default)):
                bucket = self._entries.get(source, {})
                for candidate in candidates:
                    if candidate in bucket:
                        return bucket[candidate]
        return None

    def _render_missing(self, key: str) -> str:
        with self._lock:
            first = key not in self._reported
            self._reported.add(key)
        if first:
            logger.warning("Missing UI translation key: %s", key)
        return f"[[{key}]]" if self._policy == "marker" else key

    def _read_directory(self, directory: Path) -> Dict[str, Dict[str, str]]:
        result: Dict[str, Dict[str, str]] = {}
        if not directory.is_dir():
            logger.warning("Locale directory not found: %s", directory)
            return result
        for path in sorted(directory.glob("*.json")):
            locale = path.stem
            if _LOCALE_RE.fullmatch(locale) is None:
                raise CatalogError(f"{path}: file name must be a locale code such as en_US.json")
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as err:
                raise CatalogError(f"{path}: unreadable locale file") from err
            flat: Dict[str, str] = {}
            _flatten("", raw, flat, str(path))
            result[locale] = flat
        return result


_catalog: Optional[I18nCatalog] = None
_catalog_lock = threading.Lock()


def get_catalog() -> I18nCatalog:
    """Return the process-wide catalog, building it from settings on first use."""
    global _catalog
    with _catalog_lock:
        if _catalog is None:
            from core_platform.app.config import settings

            catalog = I18nCatalog(settings.UI_DEFAULT_LOCALE, settings.UI_MISSING_KEY_POLICY)
            catalog.load_core(Path(__file__).resolve().parents[2] / "locales")

            # Discover and load cartridge locales if available
            apps_dir = Path(__file__).resolve().parents[3] / "apps"
            if apps_dir.is_dir():
                for app_folder in sorted(apps_dir.iterdir()):
                    if app_folder.is_dir():
                        loc_dir = app_folder / "locales"
                        if loc_dir.is_dir():
                            try:
                                catalog.load_app(app_folder.name, loc_dir)
                            except Exception:
                                pass
            _catalog = catalog
        return _catalog


def reset_catalog() -> None:
    """Drop the process-wide catalog (tests and reload)."""
    global _catalog
    with _catalog_lock:
        _catalog = None
