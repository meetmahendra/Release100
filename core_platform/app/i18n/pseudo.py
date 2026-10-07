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

"""Generated pseudo-locale ``en_XA`` used only by tests to expose hard-coded text (Plan 11, T10).

Every catalog string is accented, padded by ~30 percent and wrapped in brackets, so any text on a
rendered page that is not wrapped in ``[`` ``]`` did not come from the catalog. Placeholders such
as ``{count}`` are preserved exactly.
"""

from __future__ import annotations

import re
from typing import Dict

from core_platform.app.i18n.catalog import I18nCatalog

PSEUDO_LOCALE = "en_XA"

_PLACEHOLDER = re.compile(r"\{[a-z_][a-z0-9_]*\}")
_ACCENTS = str.maketrans(
    "AEIOUaeiouCcNnYy",
    "\u00c0\u00c9\u00ce\u00d5\u00dc\u00e5\u00e9\u00ee\u00f5\u00fc\u00c7\u00e7\u00d1\u00f1\u00dd\u00fd",
)
_PAD_CHAR = "~"
_PAD_RATIO = 0.3


def pseudo_localize(text: str) -> str:
    """Return the accented, padded, bracketed form of ``text`` with placeholders untouched."""
    parts = []
    last = 0
    for match in _PLACEHOLDER.finditer(text):
        parts.append(text[last : match.start()].translate(_ACCENTS))
        parts.append(match.group(0))
        last = match.end()
    parts.append(text[last:].translate(_ACCENTS))
    body = "".join(parts)
    padding = _PAD_CHAR * max(1, int(len(text) * _PAD_RATIO))
    return "[" + body + padding + "]"


def build_pseudo_entries(catalog: I18nCatalog, source_locale: str) -> Dict[str, str]:
    """Return pseudo-localised entries for every key of ``source_locale``."""
    return {key: pseudo_localize(catalog.translate(key, source_locale)) for key in sorted(catalog.keys(source_locale))}


def register_pseudo_locale(catalog: I18nCatalog) -> int:
    """Register ``en_XA`` in ``catalog`` from its default locale; return the entry count."""
    entries = build_pseudo_entries(catalog, catalog.default_locale)
    catalog.register_entries(PSEUDO_LOCALE, entries)
    return len(entries)
