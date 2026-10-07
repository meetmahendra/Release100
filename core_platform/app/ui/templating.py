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

"""Single Jinja2 templating factory for every UI surface (Plan 11, T08).

``build_templates`` replaces the per-package ``Jinja2Templates(...)`` instances. It keeps
Starlette's default behaviour (autoescape on for every template) and adds:

* a shared template directory searched after the caller's own directories, so a
  cartridge finds its own ``base.html`` first and falls back to the shared shell;
* the ``t`` global (translation, locale taken from ``request.state.locale``);
* the ``status_badge`` and ``status_info`` globals (status registry SSOT).

Translated text is returned as plain ``str`` so Jinja autoescape always applies; it is
never marked safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import jinja2
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from core_platform.app.i18n.catalog import get_catalog
from core_platform.app.ui.contracts import StatusInfo
from core_platform.app.ui.status_registry import get_status_registry

SHARED_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _locale_of(context: jinja2.runtime.Context) -> str:
    """Return the request locale from the template context, or the catalog default."""
    request = context.get("request")
    state = getattr(request, "state", None)
    locale = getattr(state, "locale", None)
    return locale if isinstance(locale, str) and locale else get_catalog().default_locale


@jinja2.pass_context
def translate(context: jinja2.runtime.Context, key: str, count: Optional[int] = None, **variables: object) -> str:
    """Jinja global ``t(key, count=None, **vars)``: resolve ``key`` for the request locale."""
    return get_catalog().translate(key, _locale_of(context), count=count, **variables)


@jinja2.pass_context
def status_info(context: jinja2.runtime.Context, code: str, app_id: Optional[str] = None) -> StatusInfo:
    """Jinja global returning the :class:`StatusInfo` for ``code``."""
    return get_status_registry().get(code, app_id)


@jinja2.pass_context
def status_badge(context: jinja2.runtime.Context, code: str, app_id: Optional[str] = None) -> Markup:
    """Jinja global rendering a minimal accessible badge (icon name plus localized text)."""
    info = get_status_registry().get(code, app_id)
    label = get_catalog().translate(info.label_key, _locale_of(context))
    return Markup(
        '<span class="ui-badge ui-badge--{tone}" data-status="{code}">'
        '<span class="ui-badge__icon" data-icon="{icon}" aria-hidden="true"></span>'
        '<span class="ui-badge__label">{label}</span></span>'
    ).format(tone=escape(info.tone), code=escape(info.code), icon=escape(info.icon), label=escape(label))


def build_templates(
    own_dirs: Sequence[Path],
    extra_filters: Optional[Mapping[str, Callable[..., Any]]] = None,
    extra_globals: Optional[Mapping[str, Any]] = None,
) -> Jinja2Templates:
    """Build a ``Jinja2Templates`` that searches ``own_dirs`` first, then the shared directory.

    Args:
        own_dirs: Template directories owned by the caller (searched first, in order).
        extra_filters: Additional Jinja filters, for example cartridge date formatters.
        extra_globals: Additional Jinja globals.

    Returns:
        Templates object with autoescape enabled and the UI globals installed.
    """
    search_paths = [str(path) for path in own_dirs] + [str(SHARED_TEMPLATE_DIR)]
    env = jinja2.Environment(
        loader=jinja2.ChoiceLoader([jinja2.FileSystemLoader(path) for path in search_paths]),
        autoescape=True,
    )
    env.globals["t"] = translate
    env.globals["status_info"] = status_info
    env.globals["status_badge"] = status_badge
    for name, func in (extra_filters or {}).items():
        env.filters[name] = func
    for name, value in (extra_globals or {}).items():
        env.globals[name] = value
    return Jinja2Templates(env=env)
