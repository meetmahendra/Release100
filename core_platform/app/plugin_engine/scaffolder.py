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
Standalone Cartridge Scaffolder for Release100 Platform (GEES v2.0).

Generates a 100% decoupled, self-contained Python cartridge project with:
  - Standard pyproject.toml declaring entry points for 'release100.cartridges'
  - BaseApplication plugin implementation with typed lifecycle methods
  - FastAPI UI router and HTML template scaffolding
  - Isolated pytest suite verifying contract compliance
"""

import os
from pathlib import Path
import re
from typing import Dict, Optional


def sanitize_cartridge_name(name: str) -> str:
    """Normalize cartridge name to valid snake_case Python module identifier."""
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower())
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        raise ValueError("Cartridge name must contain alphanumeric characters.")
    return clean


def to_pascal_case(snake_str: str) -> str:
    """Convert snake_case to PascalCase (e.g. 'smart_billing' -> 'SmartBillingPlugin')."""
    return "".join(word.capitalize() for word in snake_str.split("_")) + "Plugin"


def generate_cartridge_project(
    cartridge_name: str,
    output_dir: Path,
    author: str = "Platform Contributor",
    description: Optional[str] = None,
    version: str = "0.1.0",
) -> Dict[str, Path]:
    """Generate a complete, decoupled cartridge project on disk.

    Args:
        cartridge_name: Desired cartridge name (e.g. 'smart_billing' or 'haccp-sensor').
        output_dir: Target directory where the project will be created.
        author: Author or organization name for package metadata.
        description: Brief description of the cartridge capabilities.
        version: Initial semantic version.

    Returns:
        Dict mapping logical file identifiers to created absolute Paths.
    """
    pkg_name = sanitize_cartridge_name(cartridge_name)
    class_name = to_pascal_case(pkg_name)
    display_title = " ".join(word.capitalize() for word in pkg_name.split("_"))
    desc = description or f"Standalone {display_title} Cartridge for Release100 Platform"

    project_root = output_dir / f"cartridge-{pkg_name.replace('_', '-')}"
    src_dir = project_root / "src" / pkg_name
    ui_dir = src_dir / "ui"
    templates_dir = ui_dir / "templates"
    tests_dir = project_root / "tests"

    for d in [src_dir, ui_dir, templates_dir, tests_dir]:
        d.mkdir(parents=True, exist_ok=True)

    created_files: Dict[str, Path] = {}

    # 1. pyproject.toml (Entry Point Registration)
    pyproject_content = f'''[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "release100-cartridge-{pkg_name.replace('_', '-')}"
version = "{version}"
description = "{desc}"
authors = [{{ name = "{author}" }}]
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.100.0",
    "pydantic>=2.0.0",
]

[project.entry-points."release100.cartridges"]
{pkg_name} = "{pkg_name}.plugin:{class_name}"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
'''
    pyproject_file = project_root / "pyproject.toml"
    pyproject_file.write_text(pyproject_content, encoding="utf-8")
    created_files["pyproject"] = pyproject_file

    # 2. README.md
    readme_content = f'''# {display_title} Cartridge

{desc}

## Architecture (GEES v2.0 Decoupled Cartridge Standard)
This cartridge is an independent, pip-installable plugin for the **Release100 Platform**.
It registers itself via Python's standard `release100.cartridges` entry point group.

## Development & Installation
1. Install in editable mode:
   ```bash
   pip install -e .
   ```
2. When Release100 boots, this cartridge is automatically discovered and mounted.

## Running Tests
```bash
pytest tests/ -v
```
'''
    readme_file = project_root / "README.md"
    readme_file.write_text(readme_content, encoding="utf-8")
    created_files["readme"] = readme_file

    # 3. src/<pkg_name>/__init__.py
    init_file = src_dir / "__init__.py"
    init_file.write_text(f'"""{display_title} Cartridge Package."""\n\n__version__ = "{version}"\n', encoding="utf-8")
    created_files["init"] = init_file

    # 4. src/<pkg_name>/plugin.py
    plugin_content = f'''# Copyright 2026 {author}
# Licensed under the Apache License, Version 2.0.

from typing import Any, Dict, List, Optional
from fastapi import APIRouter
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from {pkg_name}.ui.routes import router as ui_router


class {class_name}(BaseApplication):
    """Domain Application Cartridge for {display_title}."""

    app_id: str = "{pkg_name}"
    name: str = "{display_title}"
    version: str = "{version}"
    description: str = "{desc}"
    supported_channels: List[str] = ["whatsapp", "web_kiosk", "mcp_agent"]
    keywords: List[str] = ["{pkg_name.replace('_', ' ')}", "{pkg_name}"]
    dashboard_url: str = "/admin/apps/{pkg_name.replace('_', '-')}/dashboard"

    def get_ui_router(self) -> Optional[APIRouter]:
        """Return the FastAPI router for this cartridge's web shell UI."""
        return ui_router

    def get_workflow(self) -> Optional[Any]:
        """Return the domain workflow executor."""
        return None

    def on_startup(self) -> None:
        """Lifecycle hook called when the platform mounts this cartridge."""
        pass

    def on_shutdown(self) -> None:
        """Lifecycle hook called during graceful platform termination."""
        pass

    def get_health_status(self) -> Dict[str, Any]:
        """Return diagnostic health status."""
        return {{
            "app_id": self.app_id,
            "version": self.version,
            "status": "OPERATIONAL",
        }}

    def get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Declare MCP tools exposed by this cartridge to autonomous agents."""
        return [
            {{
                "name": f"{pkg_name}_status",
                "description": "Query {display_title} health and operational status.",
                "input_schema": {{"type": "object", "properties": {{}}}},
            }}
        ]
'''
    plugin_file = src_dir / "plugin.py"
    plugin_file.write_text(plugin_content, encoding="utf-8")
    created_files["plugin"] = plugin_file

    # 5. src/<pkg_name>/ui/__init__.py
    ui_init = ui_dir / "__init__.py"
    ui_init.write_text('"""UI Routing Package."""\n', encoding="utf-8")

    # 6. src/<pkg_name>/ui/routes.py
    routes_content = f'''# Copyright 2026 {author}
# Licensed under the Apache License, Version 2.0.

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/admin/apps/{pkg_name.replace('_', '-')}", tags=["{display_title}"])


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard() -> str:
    """Render the {display_title} Cartridge Dashboard."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>{display_title} Dashboard</title>
        <style>
            body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 32px; }}
            .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 24px; max-width: 700px; margin: 0 auto; }}
            .badge {{ display: inline-block; background: #10b981; color: #0f172a; padding: 4px 10px; border-radius: 9999px; font-weight: 700; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <span class="badge">DECOUPLED CARTRIDGE</span>
            <h1 style="margin-top: 12px;">{display_title}</h1>
            <p style="color: #94a3b8;">{desc}</p>
            <p><strong>Version:</strong> {version}</p>
            <p><strong>App ID:</strong> <code>{pkg_name}</code></p>
        </div>
    </body>
    </html>
    """
'''
    routes_file = ui_dir / "routes.py"
    routes_file.write_text(routes_content, encoding="utf-8")
    created_files["routes"] = routes_file

    # 7. tests/test_plugin.py
    test_content = f'''# Copyright 2026 {author}
# Licensed under the Apache License, Version 2.0.

from {pkg_name}.plugin import {class_name}


def test_cartridge_initialization() -> None:
    """Verify cartridge instantiates and conforms to BaseApplication contract."""
    plugin = {class_name}()
    assert plugin.app_id == "{pkg_name}"
    assert plugin.version == "{version}"
    assert plugin.name == "{display_title}"
    assert plugin.get_ui_router() is not None
    assert len(plugin.get_mcp_tools()) > 0

    health = plugin.get_health_status()
    assert health["status"] == "OPERATIONAL"
'''
    test_file = tests_dir / "test_plugin.py"
    test_file.write_text(test_content, encoding="utf-8")
    created_files["test"] = test_file

    return created_files
