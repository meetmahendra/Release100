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
Core Platform Middlewares.
"""

from core_platform.app.middleware.tenant_context import (
    TenantContext,
    TenantContextMiddleware,
    get_current_tenant_id,
    set_current_tenant_id,
    reset_tenant_context,
    tenant_scope,
    sync_tenant_scope,
    get_current_cartridge_id,
    set_current_cartridge_id,
    reset_cartridge_context,
    cartridge_scope,
    async_cartridge_scope,
)

__all__ = [
    "TenantContext",
    "TenantContextMiddleware",
    "get_current_tenant_id",
    "set_current_tenant_id",
    "reset_tenant_context",
    "tenant_scope",
    "sync_tenant_scope",
    "get_current_cartridge_id",
    "set_current_cartridge_id",
    "reset_cartridge_context",
    "cartridge_scope",
    "async_cartridge_scope",
]
