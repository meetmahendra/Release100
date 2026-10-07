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

"""Build sidebar navigation from cartridge hooks, tenant scope and the entitlement gate (Plan 11, T09)."""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from core_platform.app.auth.models import SecurityContext
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.ui.contracts import NavItem

logger = logging.getLogger("core_platform.ui.nav")


def _is_visible(ctx: SecurityContext, item: NavItem) -> bool:
    """Return True when the entitlement gate allows ``item``; hide on any error (fail closed)."""
    if item.required_action is None:
        return True
    try:
        from core_platform.app.entitlements.dependencies import get_gate

        return bool(get_gate().check(ctx, item.required_action).allowed)
    except Exception as err:  # noqa: BLE001 - a nav check must never break page rendering
        logger.warning("[UiNav] gate check failed for %s: %s", item.required_action, err)
        return False


def build_nav(
    ctx: SecurityContext,
    allowed_apps: Iterable[str],
    applications: Optional[Dict[str, BaseApplication]] = None,
) -> List[NavItem]:
    """Collect nav items from the cartridges in ``allowed_apps`` that the gate lets ``ctx`` see.

    Args:
        ctx: The authenticated principal.
        allowed_apps: App ids already filtered by tenant scope and RBAC.
        applications: Loaded cartridges keyed by id; read from the plugin loader when omitted.

    Returns:
        Visible nav items in cartridge load order. Empty when nothing is allowed.
    """
    allowed = set(allowed_apps)
    if applications is None:
        try:
            from core_platform.main import plugin_loader

            applications = plugin_loader.get_all_applications()
        except Exception as err:  # noqa: BLE001 - clean-slate boot must not fail
            logger.warning("[UiNav] plugin loader unavailable: %s", err)
            applications = {}
    items: List[NavItem] = []
    for app_id, app in applications.items():
        if app_id not in allowed:
            continue
        try:
            declared = app.get_ui_nav()
        except Exception as err:  # noqa: BLE001 - one bad cartridge must not hide the rest
            logger.warning("[UiNav] get_ui_nav failed for %s: %s", app_id, err)
            continue
        visible = [item for item in declared if _is_visible(ctx, item)]
        if not declared:
            visible = [_fallback_item(app_id, app)]
        items.extend(visible)
    return items


def _fallback_item(app_id: str, app: BaseApplication) -> NavItem:
    """Return a single entry for a cartridge that declares no navigation of its own."""
    slug = app_id.replace("_", "-")
    path = getattr(app, "dashboard_url", "") or f"/admin/apps/{slug}/"
    return NavItem(
        label_key="core.nav.group_apps",
        label_text=str(getattr(app, "name", app_id) or app_id),
        path=str(path),
        group_key="core.nav.group_apps",
    )


def _core(label_key: str, path: str, group_key: Optional[str] = None) -> NavItem:
    return NavItem(label_key=label_key, path=path, group_key=group_key)


def compose_nav(
    ctx: SecurityContext,
    allowed_apps: Iterable[str],
    applications: Optional[Dict[str, BaseApplication]] = None,
) -> List[NavItem]:
    """Return the full sidebar: overview, cartridge entries, then role-based core sections."""
    items: List[NavItem] = [_core("core.nav.overview", "/admin/")]
    apps = build_nav(ctx, allowed_apps, applications)
    items.extend(
        item if item.group_key else item.model_copy(update={"group_key": "core.nav.group_apps"}) for item in apps
    )
    if ctx.is_admin or ctx.is_devops:
        ws = "core.nav.group_workspace"
        items.append(_core("core.nav.users", "/admin/users", ws))
        items.append(_core("core.nav.tenants", "/admin/tenants", ws))
        items.append(_core("core.nav.api_keys", "/admin/api-keys", ws))
        if ctx.is_devops:
            items.append(_core("core.nav.devops_plane", "/ops/tenants", ws))
    if ctx.is_devops:
        dg = "core.nav.group_diagnostics"
        items.append(_core("core.nav.llm_costs", "/admin/llm-costs", dg))
        items.append(_core("core.nav.logs", "/admin/logs", dg))
        items.append(_core("core.nav.settings", "/settings", dg))
        items.append(_core("core.nav.health", "/health", dg))
    return items
