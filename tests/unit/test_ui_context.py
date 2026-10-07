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

"""Tests for UiContext and nav builder (Plan 11, T09)."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core_platform.app.auth.models import SecurityContext
from core_platform.app.config import settings
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.ui.contracts import Breadcrumb, NavItem
from core_platform.app.ui.nav_builder import build_nav
from core_platform.app.ui.ui_context import UiContext, build_ui_context


class _FakeApp:
    def __init__(self, items: List[NavItem], boom: bool = False) -> None:
        self._items = items
        self._boom = boom

    def get_ui_nav(self) -> List[NavItem]:
        if self._boom:
            raise RuntimeError("bad cartridge")
        return self._items


def _apps(**kwargs: _FakeApp) -> Dict[str, BaseApplication]:
    return {k: v for k, v in kwargs.items()}  # type: ignore[misc]


def _ctx(roles: List[str], tenant: str = "acme_test", pid: str = "u1") -> SecurityContext:
    return SecurityContext(principal_id=pid, tenant_id=tenant, user_roles=roles, is_authenticated=True)


PLAIN = NavItem(label_key="apps.x.nav.home", path="/x")
GATED = NavItem(label_key="apps.x.nav.gated", path="/x/g", required_action="x.do")


def test_platform_admin_context() -> None:
    ui = build_ui_context("en_US", _ctx(["devops_admin"], tenant="platform", pid="devops_admin"))
    assert ui.tenant_slug == ""
    assert ui.role_label_key == "core.role.devops"
    assert ui.principal_label == "devops_admin"


def test_tenant_admin_context() -> None:
    ui = build_ui_context("en_US", _ctx(["admin"]), tenant_name="Acme Test")
    assert ui.tenant_slug == "acme_test"
    assert ui.tenant_name == "Acme Test"
    assert ui.role_label_key == "core.role.admin"


def test_operator_context() -> None:
    ui = build_ui_context("en_US", _ctx(["operator"]))
    assert ui.role_label_key == "core.role.operator"


def test_clean_slate_no_principal() -> None:
    ui = build_ui_context("en_US", None)
    assert ui.tenant_slug == "" and ui.tenant_name == "" and ui.principal_label == ""
    assert ui.role_label_key == "core.role.guest"
    assert ui.nav == []


def test_frozen_and_breadcrumbs_and_shell_mode() -> None:
    ui = build_ui_context("en_US", None, breadcrumbs=[Breadcrumb(label_key="common.close")], shell_mode="bare")
    assert ui.shell_mode == "bare"
    assert ui.breadcrumbs[0].label_key == "common.close"
    with pytest.raises(Exception):
        ui.locale = "x"  # type: ignore[misc]


@pytest.mark.parametrize(
    "mode,expected", [("enforce", "live"), ("shadow", "preview"), ("off", "off")]
)
def test_runtime_mode_mapping(monkeypatch: pytest.MonkeyPatch, mode: str, expected: str) -> None:
    monkeypatch.setattr(settings, "ENTITLEMENT_ENFORCEMENT_MODE", mode)
    assert build_ui_context("en_US", None).runtime_mode == expected


def test_nav_hidden_for_disabled_app() -> None:
    apps = _apps(x=_FakeApp([PLAIN]), y=_FakeApp([NavItem(label_key="apps.y.nav.a", path="/y")]))
    items = build_nav(_ctx(["admin"]), ["x"], apps)
    assert [i.path for i in items] == ["/x"]


def test_nav_gate_allows_and_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Dec:
        def __init__(self, allowed: bool) -> None:
            self.allowed = allowed

    class _Gate:
        def check(self, ctx: Any, action: str) -> _Dec:
            return _Dec(action == "x.do" and ctx.principal_id == "u1")

    monkeypatch.setattr("core_platform.app.entitlements.dependencies.get_gate", lambda: _Gate())
    apps = _apps(x=_FakeApp([PLAIN, GATED]))
    assert len(build_nav(_ctx(["admin"], pid="u1"), ["x"], apps)) == 2
    assert len(build_nav(_ctx(["admin"], pid="u2"), ["x"], apps)) == 1


def test_nav_gate_error_hides_item(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise RuntimeError("gate down")

    monkeypatch.setattr("core_platform.app.entitlements.dependencies.get_gate", _boom)
    items = build_nav(_ctx(["admin"]), ["x"], _apps(x=_FakeApp([PLAIN, GATED])))
    assert [i.path for i in items] == ["/x"]


def test_nav_bad_cartridge_does_not_hide_others() -> None:
    apps = _apps(x=_FakeApp([], boom=True), y=_FakeApp([NavItem(label_key="apps.y.nav.a", path="/y")]))
    assert [i.path for i in build_nav(_ctx(["admin"]), ["x", "y"], apps)] == ["/y"]


def test_nav_reads_plugin_loader_when_omitted() -> None:
    items = build_nav(_ctx(["admin"]), [])
    assert items == []


def test_nav_survives_missing_plugin_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    import core_platform.main as main_mod

    monkeypatch.delattr(main_mod, "plugin_loader")
    assert build_nav(_ctx(["admin"]), ["x"]) == []


def test_authenticated_context_builds_nav() -> None:
    ui = build_ui_context("en_US", _ctx(["admin"]), allowed_apps=[])
    assert isinstance(ui, UiContext)
    assert ui.nav == []
