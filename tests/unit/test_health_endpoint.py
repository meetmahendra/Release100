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

"""Synthetic Unit Tests for /health Heartbeat API."""

import pytest
from starlette.testclient import TestClient

from core_platform.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide a Starlette/FastAPI TestClient instance."""
    return TestClient(app)


def test_health_endpoint_structure(client: TestClient) -> None:
    """Health endpoint must return 200 with structured JSON metadata."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert "uptime_seconds" in data
    assert "tenant_id" in data
    assert "kiosk_id" in data
    assert "skills" in data
    assert "audit_engine" in data
    assert "cloud_relay" in data
    assert "enabled" in data["cloud_relay"]

    # Verify cognitive skills reported in health payload
    skills = data["skills"]
    assert "geofencing" in skills
    assert "display_ocr" in skills
    assert "face_recognizer" in skills
    assert "image_enhancer" in skills


@pytest.mark.anyio
async def test_main_lifespan() -> None:
    """Test lifespan startup and shutdown context manager."""
    from core_platform.main import lifespan
    async with lifespan(app):
        pass

