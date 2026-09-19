# -*- mode: python ; coding: utf-8 -*-
# Copyright 2026 Mahendra GURAV
# Licensed under Apache License 2.0

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

import certifi

project_root = Path(SPECPATH).parent.parent

datas = [
    (str(project_root / "apps" / "temperature_marker" / "knowledge_graph" / "canebot_fleet_roster.json"), "apps/temperature_marker/knowledge_graph"),
    (str(project_root / "apps" / "temperature_marker" / "ui" / "templates"), "apps/temperature_marker/ui/templates"),
    (str(project_root / "apps" / "mail_organizer" / "ui" / "templates"), "apps/mail_organizer/ui/templates"),
    (certifi.where(), "certifi"),
]

hiddenimports = [
    "certifi",
    "ssl",
    "httpx",
    "httpcore",
    "fastapi",
    "starlette",
    "jinja2",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "cryptography",
    "geopy",
    "numpy",
    "pystray",
    "PIL",
    "websockets",
    "langgraph",
    "langgraph.graph",
    "google.genai",
    "google.genai.types",
    "core_platform.app.ingress.relay_client",
    "apps.temperature_marker.workflow",
    "apps.temperature_marker.ui.routes",
    "apps.mail_organizer.workflow",
    "apps.mail_organizer.ui.routes",
]
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("pystray")
hiddenimports += collect_submodules("websockets")
hiddenimports += collect_submodules("langgraph")

a = Analysis(
    [str(project_root / "manage.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Release100",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Release100",
)
