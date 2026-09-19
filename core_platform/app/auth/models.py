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
Auth Domain Models.

Defines the SecurityContext produced by all authentication strategies.
All downstream components (RBAC, routing, audit) consume SecurityContext.
"""

from typing import List
from pydantic import BaseModel, Field


class SecurityContext(BaseModel):
    """Authenticated principal context produced by all auth strategies.

    Consumed by the RBAC filter, semantic router, and audit engine to
    enforce per-tenant, per-role access control.
    """

    principal_id: str = Field(description="Unique identifier for the authenticated principal")
    tenant_id: str = Field(default="default_tenant", description="Multi-tenant identifier")
    user_roles: List[str] = Field(
        default_factory=list,
        description="Role list: e.g. ['operator', 'admin']",
    )
    permitted_apps: List[str] = Field(
        default_factory=list,
        description="App cartridges this principal may access",
    )
    auth_strategy: str = Field(
        default="unknown",
        description="Strategy used: phone_biometric | local_jwt | api_key",
    )
    is_authenticated: bool = Field(default=False)

    @property
    def is_admin(self) -> bool:
        """Return True when the principal holds the admin role."""
        return "admin" in self.user_roles

    @classmethod
    def unauthenticated(cls) -> "SecurityContext":
        """Return a minimal unauthenticated SecurityContext."""
        return cls(
            principal_id="anonymous",
            is_authenticated=False,
            auth_strategy="none",
        )

    @classmethod
    def system(cls) -> "SecurityContext":
        """Return a trusted system-level context for internal service calls."""
        return cls(
            principal_id="system",
            tenant_id="system",
            user_roles=["admin"],
            permitted_apps=["temperature_marker", "mail_organizer"],
            auth_strategy="system",
            is_authenticated=True,
        )
