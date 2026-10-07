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

"""Typed UI contracts shared by core and cartridges (Plan 11, T06).

``NavItem`` and ``StatusInfo`` are declared by cartridges through
``BaseApplication`` hooks; ``Breadcrumb`` is used by the shell. Labels are catalog
keys, never display text.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

Tone = Literal["neutral", "success", "warning", "danger", "info"]


class Breadcrumb(BaseModel):
    """One breadcrumb element in the top bar."""

    model_config = ConfigDict(frozen=True)

    label_key: str
    path: Optional[str] = None


class NavItem(BaseModel):
    """One sidebar entry declared by core or a cartridge."""

    model_config = ConfigDict(frozen=True)

    label_key: str
    path: str
    required_action: Optional[str] = None  # entitlement action id; the gate decides visibility
    group_key: Optional[str] = None  # catalog key of the sidebar section heading, if any
    label_text: Optional[str] = None  # runtime display name (for example an application name)


class StatusInfo(BaseModel):
    """Presentation data for one status code (never colour alone, see D17)."""

    model_config = ConfigDict(frozen=True)

    code: str
    tone: Tone
    icon: str  # glyph name such as "check", "clock", "alert"
    label_key: str
