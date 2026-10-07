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
Core Platform Multi-Tenant Identity & User Management Module.
"""

from core_platform.app.identity.magic_link import (
    build_magic_link_url,
    generate_magic_link_token,
    verify_magic_link_token,
)
from core_platform.app.identity.models import PlatformUser
from core_platform.app.identity.service import (
    UserIdentityService,
    get_user_identity_service,
    normalize_phone_number,
)

__all__ = [
    "PlatformUser",
    "UserIdentityService",
    "get_user_identity_service",
    "normalize_phone_number",
    "generate_magic_link_token",
    "verify_magic_link_token",
    "build_magic_link_url",
]

