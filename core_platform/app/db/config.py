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
Database Configuration Models for Pluggable Polyglot Data Layer.

Adheres strictly to GEES v2.0 Pillar 4 (Zero-Hardcoding) & Pillar 5 (Type Discipline).
"""

from typing import Dict, Optional
from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """Configuration contract for database connection factories."""

    database_url: str = Field(
        default="sqlite:///logs/platform_data.db",
        description="SQLAlchemy database connection URL (sqlite, postgresql, mysql, etc.)",
    )
    pool_size: int = Field(
        default=20,
        description="Number of connections to retain in the connection pool for SQL servers",
    )
    max_overflow: int = Field(
        default=10,
        description="Max overflow connections allowed beyond pool_size",
    )
    pool_timeout_seconds: int = Field(
        default=30,
        description="Timeout in seconds when acquiring connection from pool",
    )
    pool_recycle_seconds: int = Field(
        default=3600,
        description="Recycle connections older than this duration to prevent stale handles",
    )
    echo: bool = Field(
        default=False,
        description="When True, SQLAlchemy logs generated SQL statements",
    )
    connect_args: Dict[str, object] = Field(
        default_factory=dict,
        description="Driver-specific connection arguments",
    )
