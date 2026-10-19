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
Unit & Topology Verification Tests for TrueNAS SCALE (ElectricEel-24.10.0.2) Deployment.

# [CODE-MARKER: TN-TEST-01]
Verifies:
1. Domain-agnostic per-role and per-cartridge DB URL resolution in PlatformSettings.
2. Paradigm A (Shared DB default) vs Paradigm C (Dedicated per-cartridge DB override) in PluginLoader.
3. MailDatabaseService and TemperatureDatabaseService dynamic engine rebinding (on_bind_engine).
4. TrueNAS SCALE Docker Compose YAML topology, 568:568 permissions, and GHCR workflow matrix parity.
"""

from pathlib import Path
from typing import Any
import pytest
import yaml

from core_platform.app.config import PlatformSettings, settings
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.plugin_engine.loader import PluginLoader


def test_platform_settings_shared_vs_dedicated_db_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify PlatformSettings resolves shared DATABASE_URL by default and per-role/per-cartridge URLs when set."""
    monkeypatch.delenv("CARTRIDGE_DB_URL_MAIL_ORGANIZER", raising=False)
    monkeypatch.delenv("MAIL_ORGANIZER_DATABASE_URL", raising=False)
    monkeypatch.delenv("CARTRIDGE_DB_URL_TEMPERATURE_MARKER", raising=False)

    cfg_default = PlatformSettings(
        DATABASE_URL="postgresql+psycopg2://user:pass@postgres-shared:5432/release100",
    )
    assert cfg_default.resolve_primary_db_url() == "postgresql+psycopg2://user:pass@postgres-shared:5432/release100"
    assert cfg_default.resolve_cartridge_db_url("mail_organizer") is None
    assert cfg_default.resolve_cartridge_db_url("temperature_marker") is None

    # Role-specific primary DB override (ops_control and core)
    cfg_ops = PlatformSettings(
        CONTAINER_ROLE="ops_control",
        DATABASE_URL="postgresql+psycopg2://user:pass@postgres-shared:5432/release100",
        OPS_DATABASE_URL="postgresql+psycopg2://ops:pass@postgres-ops:5432/release100_ops",
    )
    assert cfg_ops.resolve_primary_db_url() == "postgresql+psycopg2://ops:pass@postgres-ops:5432/release100_ops"

    # Per-cartridge override via CARTRIDGE_DATABASE_URLS dict
    cfg_dict = PlatformSettings(
        DATABASE_URL="postgresql+psycopg2://user:pass@postgres-shared:5432/release100",
        CARTRIDGE_DATABASE_URLS={
            "mail_organizer": "postgresql+psycopg2://mail:pass@postgres-mail:5432/release100_mail",
        },
    )
    assert (
        cfg_dict.resolve_cartridge_db_url("mail-organizer")
        == "postgresql+psycopg2://mail:pass@postgres-mail:5432/release100_mail"
    )
    assert cfg_dict.resolve_cartridge_db_url("temperature_marker") is None

    # Per-cartridge override via environment variable CARTRIDGE_DB_URL_<APP_ID>
    monkeypatch.setenv("CARTRIDGE_DB_URL_TEMPERATURE_MARKER", "sqlite:///logs/dedicated_temp.db")
    assert cfg_default.resolve_cartridge_db_url("temperature_marker") == "sqlite:///logs/dedicated_temp.db"


def test_plugin_loader_binds_dedicated_cartridge_db_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify PluginLoader uses Paradigm C when CARTRIDGE_DB_URL_<APP_ID> is set and Paradigm A otherwise."""
    shared_db_path = tmp_path / "shared_platform.db"
    dedicated_mail_db_path = tmp_path / "dedicated_mail.db"

    shared_url = f"sqlite:///{shared_db_path.as_posix()}"
    dedicated_mail_url = f"sqlite:///{dedicated_mail_db_path.as_posix()}"

    monkeypatch.setattr(settings, "DATABASE_URL", shared_url)
    monkeypatch.setattr(settings, "CORE_DATABASE_URL", None)
    monkeypatch.setenv("CARTRIDGE_DB_URL_MAIL_ORGANIZER", dedicated_mail_url)
    monkeypatch.delenv("CARTRIDGE_DB_URL_TEMPERATURE_MARKER", raising=False)

    DatabaseManager.reset_instance()
    try:
        db_mgr = DatabaseManager.get_instance(database_url=shared_url)
        loader = PluginLoader(enabled_apps=["mail_organizer", "temperature_marker"])
        loaded = loader.load_all()

        assert "mail_organizer" in loaded
        assert "temperature_marker" in loaded

        # Mail Organizer should be bound to its dedicated custom factory (Paradigm C)
        custom_mail_factory = db_mgr.get_custom_factory("mail_organizer")
        assert custom_mail_factory is not None
        mail_app: Any = loaded["mail_organizer"]
        assert mail_app.db_service.engine is custom_mail_factory.get_engine()
        assert dedicated_mail_db_path.is_file()

        # Temperature Marker has no dedicated DB override, so it shares the primary engine (Paradigm A)
        assert db_mgr.get_custom_factory("temperature_marker") is None
        temp_app: Any = loaded["temperature_marker"]
        assert temp_app.db_service.engine is db_mgr.get_engine()
        assert shared_db_path.is_file()
        assert mail_app.db_service.engine is not temp_app.db_service.engine
    finally:
        DatabaseManager.reset_instance()


def test_truenas_compose_and_ghcr_pipeline_manifests() -> None:
    """Verify TrueNAS SCALE ElectricEel-24.10.0.2 Compose stack, Dockerfile targets, and GHCR workflow."""
    repo_root = Path(__file__).resolve().parents[2]

    compose_path = repo_root / "deployment" / "truenas" / "docker-compose.truenas.yml"
    env_example_path = repo_root / "deployment" / "truenas" / ".env.truenas.example"
    setup_script_path = repo_root / "deployment" / "truenas" / "setup_truenas_datasets.sh"
    dockerfile_path = repo_root / "deployment" / "docker" / "Dockerfile"
    workflow_path = repo_root / ".github" / "workflows" / "publish-packages.yml"

    assert compose_path.is_file(), "Missing deployment/truenas/docker-compose.truenas.yml"
    assert env_example_path.is_file(), "Missing deployment/truenas/.env.truenas.example"
    assert setup_script_path.is_file(), "Missing deployment/truenas/setup_truenas_datasets.sh"

    compose_data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose_data.get("services", {})
    expected_services = {
        "postgres-shared",
        "release100-core",
        "release100-ops",
        "app-mail-organizer",
        "app-temperature-marker",
        "cloudflared",
        "postgres-mail",
        "postgres-temp",
    }
    assert expected_services.issubset(set(services.keys()))

    # Verify TrueNAS SCALE ElectricEel apps UID/GID (568:568) on stateful services
    for svc_name in ("postgres-shared", "release100-core", "release100-ops", "app-mail-organizer", "app-temperature-marker"):
        assert services[svc_name].get("user") == "568:568", f"Service {svc_name} must run as TrueNAS apps UID/GID 568:568"

    # Verify Dockerfile defines all multi-target stages
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
    for stage_name in (
        "AS base-runtime",
        "AS core-runtime",
        "AS ops-control",
        "AS cartridge-mail-organizer",
        "AS cartridge-temperature-marker",
        "AS runtime",
    ):
        assert stage_name in dockerfile_text, f"Missing stage '{stage_name}' in deployment/docker/Dockerfile"

    # Verify GitHub Actions workflow preserves Job 1 (build-and-publish) and defines Job 2 (build-and-push-ghcr-images)
    workflow_data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = workflow_data.get("jobs", {})
    assert "build-and-publish" in jobs, "Existing wheel publishing job must be preserved"
    assert "build-and-push-ghcr-images" in jobs, "GHCR image builder job must be present"
    matrix_items = jobs["build-and-push-ghcr-images"]["strategy"]["matrix"]["include"]
    matrix_targets = {item["target"] for item in matrix_items}
    assert matrix_targets == {
        "core-runtime",
        "ops-control",
        "cartridge-mail-organizer",
        "cartridge-temperature-marker",
    }
