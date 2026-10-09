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

"""UiContext: the single source of shell data for every page (Plan 11, T09, decision D13)."""

from __future__ import annotations

from typing import Iterable, List, Literal, Optional

from pydantic import BaseModel, ConfigDict

from core_platform.app.auth.models import SecurityContext
from core_platform.app.config import settings
from core_platform.app.ui.contracts import Breadcrumb, NavItem
from core_platform.app.ui.nav_builder import compose_nav

__all__ = ["Breadcrumb", "NavItem", "UiContext", "build_ui_context"]

RuntimeMode = Literal["live", "preview", "off"]
ShellMode = Literal["full", "bare"]

_MODE_MAP: dict[str, RuntimeMode] = {"enforce": "live", "shadow": "preview", "off": "off"}
_PLATFORM_TENANTS = frozenset({"default_tenant", "system", "public", "platform"})


class UiContext(BaseModel):
    """Everything the shared shell needs; templates never read these from elsewhere."""

    model_config = ConfigDict(frozen=True)

    locale: str
    tenant_name: str
    tenant_slug: str
    principal_label: str
    role_label_key: str
    runtime_mode: RuntimeMode
    breadcrumbs: List[Breadcrumb]
    nav: List[NavItem]
    shell_mode: ShellMode = "full"
    node_id: str = ""
    station_name: str = ""


def _role_key(ctx: SecurityContext) -> str:
    if not ctx.is_authenticated:
        return "core.role.guest"
    if ctx.is_devops:
        return "core.role.devops"
    if ctx.is_admin:
        return "core.role.admin"
    return "core.role.operator"


def build_ui_context(
    locale: str,
    ctx: Optional[SecurityContext],
    allowed_apps: Iterable[str] = (),
    tenant_name: Optional[str] = "",
    breadcrumbs: Iterable[Breadcrumb] = (),
    shell_mode: ShellMode = "full",
    node_id: Optional[str] = None,
    station_name: Optional[str] = None,
) -> UiContext:
    """Build a ``UiContext``; tolerates no principal and no tenant (clean-slate boot).

    Args:
        locale: Negotiated locale for the request.
        ctx: Authenticated principal, or None.
        allowed_apps: App ids already filtered by tenant scope and RBAC.
        tenant_name: Display name of the active tenant, empty when none.
        breadcrumbs: Breadcrumb trail for the page.
        shell_mode: ``full`` for the whole shell, ``bare`` for login-style pages.
        node_id: Host node identifier (defaults to settings.NODE_ID).
        station_name: Host station display name (defaults to settings.STATION_NAME).

    Returns:
        An immutable ``UiContext``.
    """
    principal = ctx if ctx is not None else SecurityContext.unauthenticated()
    slug = principal.tenant_id if (principal.is_authenticated and principal.tenant_id) else ""
    eff_tenant_name = str(tenant_name or (settings.ORGANIZATION_NAME if principal.is_authenticated else "") or "")
    eff_node_id = str(node_id if node_id is not None else (settings.NODE_ID or "NODE-01") if principal.is_authenticated else "")
    eff_station_name = str(station_name if station_name is not None else (settings.STATION_NAME or "Release100 Node #01") if principal.is_authenticated else "")
    return UiContext(
        locale=locale,
        tenant_name=eff_tenant_name,
        tenant_slug=slug,
        principal_label=principal.principal_id if principal.is_authenticated else "",
        role_label_key=_role_key(principal),
        runtime_mode=_MODE_MAP.get(settings.ENTITLEMENT_ENFORCEMENT_MODE, "off"),
        breadcrumbs=list(breadcrumbs),
        nav=compose_nav(principal, allowed_apps) if principal.is_authenticated else [],
        shell_mode=shell_mode,
        node_id=eff_node_id,
        station_name=eff_station_name,
    )
