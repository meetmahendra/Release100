# -*- mode: python ; coding: utf-8 -*-
# Copyright 2026 Mahendra GURAV
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
PyInstaller Specification for Release100 Kiosk & Retail Edition.
Contains solely the Temperature & Attendance Marker cartridge, Core Platform,
Process Supervisor, and System Tray, strictly omitting Mail Organizer.
"""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import certifi

block_cipher = None

project_root = Path(SPECPATH).parent.parent

datas = [
    (str(project_root / "apps" / "temperature_marker" / "knowledge_graph" / "fleet_roster.json"), "apps/temperature_marker/knowledge_graph"),
    (str(project_root / "apps" / "temperature_marker" / "ui" / "templates"), "apps/temperature_marker/ui/templates"),
    (str(project_root / "core_platform" / "app" / "admin_shell" / "templates"), "core_platform/app/admin_shell/templates"),
    (str(project_root / "deployment" / "desktop_tray" / "assets"), "deployment/desktop_tray/assets"),
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
    "cv2",
    "PIL",
    "pystray",
    "websockets",
    "google.genai",
    "google.genai.types",
    "core_platform.app.ingress.relay_client",
    "core_platform.app.apps_registry",
    "core_platform.app.admin_shell.routes",
    "core_platform.app.diagnostics.web_dashboard",
    "core_platform.app.diagnostics.verifier",
    "core_platform.app.diagnostics.config_backup",
    "apps.temperature_marker.plugin",
    "apps.temperature_marker.workflow",
    "apps.temperature_marker.ui.routes",
    "apps.temperature_marker.database.db_service",
    "apps.temperature_marker.database.models",
    "apps.temperature_marker.downstream.in_house_rest",
    "apps.temperature_marker.downstream.outbox_manager",
    "apps.temperature_marker.skills.display_ocr",
    "apps.temperature_marker.skills.face_recognizer",
    "apps.temperature_marker.skills.geofencing_validator",
    "apps.temperature_marker.skills.haccp_engine",
    "deployment.desktop_tray.main_tray",
    "deployment.desktop_tray.exporter",
    "deployment.supervisor.ntp_checker",
    "deployment.supervisor.port_checker",
    "deployment.supervisor.process_supervisor",
]

hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("pystray")
hiddenimports += collect_submodules("websockets")

a = Analysis(
    [str(project_root / "manage.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["apps.mail_organizer", "tkinter", "matplotlib", "scipy", "notebook", "IPython"],
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
    name="Release100_Kiosk",
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
    name="Release100_Kiosk",
)
