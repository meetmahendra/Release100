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
Platform Developer & Operations CLI (`core_platform.cli`).

Adheres strictly to Plan 05 v1.2 and GEES v1.0.
Provides the main entry point for the `release100` console script.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import List, Optional
import zipfile

from core_platform.app.config import settings
from core_platform.app.skills.registry import SkillRegistry
from core_platform.app.telemetry.audit_engine import AuditEngine
from deployment.supervisor.ntp_checker import NTPChecker
from deployment.supervisor.port_checker import PortChecker


def _bootstrap_environment() -> None:
    """Initialize SSL root certificates and environment for standalone execution."""
    try:
        import certifi

        ca_path = certifi.where()
        if os.path.exists(ca_path):
            os.environ.setdefault("SSL_CERT_FILE", ca_path)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
    except Exception:
        pass


_bootstrap_environment()


def command_health() -> int:
    """Query and print local platform health status."""
    print("=" * 70)
    print("  RELEASE100 PLATFORM HEALTH DIAGNOSTIC")
    print("=" * 70)

    clock_ok, clock_msg = NTPChecker.verify_system_clock_sanity()
    ports_ok, ports_msg = PortChecker.verify_platform_ports()

    print(f"System Clock  : {'[OK]' if clock_ok else '[WARN]'} {clock_msg}")
    print(f"TCP Sockets   : {'[OK]' if ports_ok else '[BUSY]'} {ports_msg}")
    print("-" * 70)

    print(f"Tenant / Org  : {settings.ORGANIZATION_NAME} ({settings.TENANT_ID})")
    print(f"Active Kiosk  : {settings.STATION_NAME} [{settings.KIOSK_ID}]")
    print(f"Execution Mode: {settings.EXECUTION_MODE.upper()} (DRY_RUN={settings.DRY_RUN})")
    print(f"Active Cartridges: {', '.join(settings.ENABLED_APPLICATIONS)}")
    print("-" * 70)

    print("COGNITIVE SKILLS HEALTH:")
    skills = SkillRegistry.get_instance().get_all_health_statuses()
    for name, stat in skills.items():
        ready = stat.get("available", False)
        print(f"  - {name:<18} : {'[OPERATIONAL]' if ready else '[OFFLINE]'} {stat}")

    audit_engine = AuditEngine.get_instance()
    print("-" * 70)
    print("COMPLIANCE AUDIT CHAIN:")
    print(f"  Last Sequence Number: #{audit_engine._sequence_counter}")
    print(f"  Last SHA-256 Hash   : {audit_engine._last_hash}")
    print("=" * 70)
    return 0


def command_export_audit() -> int:
    """Package partitioned audit files (.jsonl, .csv, .html) into a Desktop ZIP."""
    audit_dir = Path(settings.AUDIT_DIR)
    if not audit_dir.exists():
        print(f"[WARN] Audit directory {audit_dir} does not exist yet.")
        return 1

    desktop_path = Path.home() / "Desktop"
    if not desktop_path.exists():
        desktop_path = Path(".")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_name = f"Release100_Audit_Export_{settings.KIOSK_ID}_{timestamp}.zip"
    target_zip = desktop_path / zip_name

    file_count = 0
    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(audit_dir):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(audit_dir)
                zipf.write(full_path, arcname=str(rel_path))
                file_count += 1

    print(f"[SUCCESS] Successfully exported {file_count} audit file(s) to:")
    print(f"   {target_zip.resolve()}")
    return 0


def command_build(target: str, dry_run: bool, edition: str = "kiosk") -> int:
    """Validate or execute packaging build."""
    if target == "windows":
        from deployment.packaging_windows.build_installer import WindowsInstallerBuilder

        builder = WindowsInstallerBuilder(edition=edition)
        return builder.build(dry_run=dry_run)

    print("=" * 70)
    print(f"  RELEASE100 PACKAGING HUB: Target={target.upper()} (DryRun={dry_run})")
    print("=" * 70)
    print(f"Build target '{target}' prepared.")
    return 0


def command_seed() -> int:
    """Seed sample active operators for multi-kiosk fleet manual testing."""
    try:
        mod = importlib.import_module("apps.temperature_marker.database.db_service")
        db_cls = getattr(mod, "DatabaseService")
        db = db_cls()
        seeds = [
            ("EMP-1042", "Rajesh Pawar", "+919800011122", "CANEBOT-PUNE-04", "ACTIVE"),
            ("EMP-2088", "Sunil Patil", "+919800022233", "CANEBOT-MUMBAI-08", "ACTIVE"),
            ("EMP-3012", "Kiran Kumar", "+919800033344", "CANEBOT-BLR-02", "ACTIVE"),
            ("EMP-9901", "Amit Sharma", "+919800099999", "CANEBOT-PUNE-04", "PENDING_APPROVAL"),
        ]
        print("=" * 70)
        print("  SEEDING SAMPLE FLEET OPERATORS FOR MANUAL TESTING")
        print("=" * 70)
        for code, name, phone, kiosk, status in seeds:
            db.register_employee(
                emp_code=code,
                full_name=name,
                phone_number=phone,
                assigned_kiosk_id=kiosk,
                status=status,
            )
            print(f"  [SEEDED] {code:<10} | {name:<16} | {phone:<14} | {kiosk:<18} | {status}")
        print("=" * 70)
        print("[SUCCESS] Seeding complete. Ready for manual browser & simulator testing.")
        return 0
    except (ImportError, AttributeError):
        print("[NOTICE] Temperature Marker cartridge is not installed on this system.")
        return 0


def command_seed_mail() -> int:
    """Seed sample rules, pending PM tasks, and triaged emails for Mail Organizer testing."""
    try:
        mod = importlib.import_module("apps.mail_organizer.database.db_service")
        db_cls = getattr(mod, "MailDatabaseService")
        db = db_cls()
        print("=" * 70)
        print("  SEEDING SAMPLE DATA FOR AI MAIL & CALENDAR ORGANIZER")
        print("=" * 70)

        r1 = db.add_rule(
            rule_type="vip",
            pattern="ceo@customer-enterprise.com",
            action="tag_vip",
        )
        r2 = db.add_rule(
            rule_type="whitelist",
            pattern="*@internal.io",
            action="tag_project_task",
        )
        print(f"  [SEEDED RULE] ID #{r1.id} : {r1.rule_type} ({r1.pattern})")
        print(f"  [SEEDED RULE] ID #{r2.id} : {r2.rule_type} ({r2.pattern})")

        email1 = db.store_email(
            gmail_id="msg_seed_001",
            thread_id="thread_seed_contract",
            sender="ceo@customer-enterprise.com",
            to_recipients="depali@company.com",
            subject="URGENT: Enterprise SLA Renewal Signature Required",
            body="Please review and sign the attached enterprise SLA amendment before 5 PM today.",
            labels_applied="INBOX, _LLM/@Urgent",
        )
        db.store_classification(
            gmail_id="msg_seed_001",
            category="@Urgent",
            urgency_score=9,
            confidence_score=0.98,
            reasoning="CEO VIP sender requesting urgent contract signature.",
            responsibility_role="PRIMARY_ACTIONEE",
            is_reply_necessary=True,
        )

        email2 = db.store_email(
            gmail_id="msg_seed_002",
            thread_id="thread_seed_promo",
            sender="marketing@vendor-cloud.com",
            to_recipients="depali@company.com",
            subject="Special Offer: 40% Off Annual Database Hosting",
            body="Upgrade your cloud databases this month and save 40% on enterprise subscriptions.",
            labels_applied="_LLM/@Promotions",
        )
        db.store_classification(
            gmail_id="msg_seed_002",
            category="@Promotions",
            urgency_score=1,
            confidence_score=0.96,
            reasoning="Marketing blast newsletter. INBOX label removed per Zero-Deletion standard.",
            responsibility_role="OBSERVER_ONLY",
            is_reply_necessary=False,
        )
        print(f"  [SEEDED EMAIL] {email1.gmail_id} | {email1.subject}")
        print(f"  [SEEDED EMAIL] {email2.gmail_id} | {email2.subject}")

        t1 = db.queue_pm_task(
            summary="Deploy Redis rate limiter on API gateway",
            description="Implement token bucket algorithm on /v1/auth before next sprint cutoff.",
            priority="High",
            due_date="2026-09-20",
            destination="jira",
            project_key="ENG",
        )
        t2 = db.queue_pm_task(
            summary="Update SOC2 compliance audit log encryption key",
            description="Rotate AES-256 keys and verify HMAC-SHA256 signature chain.",
            priority="Critical",
            due_date="2026-09-18",
            destination="linear",
            project_key="SEC",
        )
        print(f"  [SEEDED PM TASK] #{t1.id} : {t1.summary} -> {t1.destination.upper()}")
        print(f"  [SEEDED PM TASK] #{t2.id} : {t2.summary} -> {t2.destination.upper()}")

        print("=" * 70)
        print("[SUCCESS] Mail Organizer seeding complete. Open /admin/apps/mail-organizer/dashboard")
        return 0
    except ImportError:
        print("[NOTICE] Mail Organizer cartridge is not installed on this system.")
        return 0


def command_list_cartridges() -> int:
    """Discover and list all installed application cartridges and their discovery sources."""
    from core_platform.app.plugin_engine.loader import PluginLoader

    loader = PluginLoader()
    descriptors = loader.discover_descriptors()

    print("=" * 75)
    print("  RELEASE100 DISCOVERED APPLICATION CARTRIDGES (GEES v2.0)")
    print("=" * 75)
    if not descriptors:
        print("  [INFO] No application cartridges discovered.")
    else:
        for app_id, desc in descriptors.items():
            src_label = (
                f"ENTRY_POINT ({desc.package_name or 'installed'})"
                if desc.source == "entry_point"
                else f"FILESYSTEM ({desc.target})"
            )
            ver_label = f"v{desc.version}" if desc.version else ""
            print(f"  - {app_id:<22} : [{desc.source.upper()}] {ver_label:<8} -> {src_label}")
    print("=" * 75)
    return 0


def command_create_cartridge(name: str, output_dir: str, author: str, description: str) -> int:
    """Scaffold a new standalone, decoupled cartridge project."""
    from core_platform.app.plugin_engine.scaffolder import generate_cartridge_project

    target_path = Path(output_dir).resolve()
    print("=" * 75)
    print(f"  SCAFFOLDING NEW DECOUPLED CARTRIDGE: {name}")
    print(f"  Target Directory: {target_path}")
    print("=" * 75)

    created = generate_cartridge_project(
        cartridge_name=name,
        output_dir=target_path,
        author=author,
        description=description if description else None,
    )

    for key, path in created.items():
        print(f"  [CREATED] {key:<12} -> {path}")

    print("=" * 75)
    print("[SUCCESS] Cartridge generated successfully!")
    print("To install in editable mode for the platform:")
    print(f"  cd {created['pyproject'].parent}")
    print("  pip install -e .")
    print("=" * 75)
    return 0


def command_run(
    mode: str = "headless",
    host: str = "0.0.0.0",
    port: int = 8002,
    apps: Optional[str] = None,
) -> int:
    """Launch Release100 platform host and admin web shell."""
    import uvicorn

    if apps is not None:
        if apps.lower() in ("none", "empty", "[]", "zero"):
            selected_apps: List[str] = []
        else:
            selected_apps = [a.strip() for a in apps.split(",") if a.strip()]
        settings.ENABLED_APPLICATIONS = selected_apps
        os.environ["ENABLED_APPLICATIONS"] = json.dumps(selected_apps)

    print("=" * 70)
    print(f"  LAUNCHING RELEASE100 PLATFORM HOST (Mode={mode.upper()})")
    print(f"  Active Cartridges  : {settings.ENABLED_APPLICATIONS or '[NONE - Pure Microkernel]'}")
    print(f"  Admin Web Shell: http://127.0.0.1:{port}/admin/apps/temperature-marker/fleet")
    print(f"  1-Click Geolocation: http://127.0.0.1:{port}/loc")
    print(f"  Health Diagnostic  : http://127.0.0.1:{port}/health")
    print("=" * 70)

    from core_platform.main import app

    if mode == "tray":
        import threading
        from deployment.desktop_tray.main_tray import DesktopTrayApp

        server_thread = threading.Thread(
            target=lambda: uvicorn.run(app, host=host, port=port, log_level="info"),
            daemon=True,
        )
        server_thread.start()

        tray_app = DesktopTrayApp()
        tray_app.run()
        return 0

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def main() -> None:
    """CLI dispatcher."""
    parser = argparse.ArgumentParser(
        description="Release100 Developer & Operations CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    subparsers.add_parser("health", help="Run local platform health diagnostics")
    subparsers.add_parser("export-audit", help="Zip audit logs (.jsonl, .csv, .html) to Desktop")
    subparsers.add_parser("list-cartridges", help="Discover and display all installed/filesystem cartridges")

    create_parser = subparsers.add_parser("create-cartridge", help="Scaffold a new decoupled cartridge package")
    create_parser.add_argument("--name", required=True, help="Cartridge snake_case identifier (e.g. smart_billing)")
    create_parser.add_argument("--output-dir", default=".", help="Target directory to create project")
    create_parser.add_argument("--author", default="Platform Contributor", help="Author name")
    create_parser.add_argument("--description", default="", help="Cartridge description")

    subparsers.add_parser("seed", help="Seed sample operators for manual testing")
    subparsers.add_parser("seed-mail", help="Seed sample data for Mail Organizer testing")

    run_parser = subparsers.add_parser("run", help="Launch platform orchestrator and web shell")
    run_parser.add_argument("--mode", choices=["headless", "tray"], default="headless", help="Execution mode")
    run_parser.add_argument("--host", default="0.0.0.0", help="Host interface")
    run_parser.add_argument("--port", type=int, default=8002, help="Port number")
    run_parser.add_argument(
        "--apps",
        default=None,
        help="Comma-separated list of cartridges to load (e.g. 'temperature_marker', 'mail_organizer', or 'none')",
    )

    build_parser = subparsers.add_parser("build", help="Build deployment artifacts")
    build_parser.add_argument("--target", choices=["windows", "docker", "linux"], default="windows")
    build_parser.add_argument("--edition", choices=["kiosk", "all"], default="kiosk", help="Platform edition to package")
    build_parser.add_argument("--dry-run", action="store_true", help="Validate specs without compiling")

    args = parser.parse_args()

    if args.command == "health":
        sys.exit(command_health())
    elif args.command == "export-audit":
        sys.exit(command_export_audit())
    elif args.command == "list-cartridges":
        sys.exit(command_list_cartridges())
    elif args.command == "create-cartridge":
        sys.exit(command_create_cartridge(name=args.name, output_dir=args.output_dir, author=args.author, description=args.description))
    elif args.command == "seed":
        sys.exit(command_seed())
    elif args.command == "seed-mail":
        sys.exit(command_seed_mail())
    elif args.command == "run":
        sys.exit(command_run(mode=args.mode, host=args.host, port=args.port, apps=args.apps))
    elif args.command == "build":
        sys.exit(command_build(target=args.target, dry_run=args.dry_run, edition=args.edition))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
