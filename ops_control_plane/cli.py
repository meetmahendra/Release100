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
DevOps Multi-Tenant Control Plane CLI (`ops_control_plane/cli.py`).

Adheres strictly to GEES v2.0:
- Microkernel purity (Control Plane separated from Core Data Plane)
- ASCII-Safe Output (Rule 6: cp1252 / cp437 safe tags: [SUCCESS], [ERROR], [INFO])
- Cryptographic Non-Repudiation (Rule 7: SHA-256 hash chaining verification)
- 100% Type Completeness under `mypy --strict`
"""

import argparse
import json
import sys
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from core_platform.app.identity.models import Tenant, TenantAuditLog, TenantConfig, TenantDomain
from ops_control_plane.devops_vault import DevOpsKeyVault
from ops_control_plane.tenant_lifecycle import GENESIS_HASH, TenantLifecycleManager, compute_audit_hash


def format_table(headers: List[str], rows: List[List[str]]) -> str:
    """Format ASCII table for console display without unicode box characters."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(val)))

    header_line = " | ".join(f"{h:<{col_widths[i]}}" for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    row_lines = [
        " | ".join(f"{str(cell):<{col_widths[i]}}" for i, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join([header_line, sep_line] + row_lines)


def handle_provision(args: argparse.Namespace) -> int:
    """Handle tenant provisioning command."""
    mgr = TenantLifecycleManager()
    try:
        res = mgr.provision_tenant(
            slug=args.slug,
            name=args.name,
            admin_phone=args.admin_phone,
            admin_name=args.admin_name,
            license_tier=args.license_tier,
            max_users=args.max_users,
            storage_region=args.region,
            db_mode=args.db_dialect,
            db_url=args.db_url,
            custom_domain=args.custom_domain,
            performed_by=args.performed_by,
        )
        print(f"[SUCCESS] Tenant '{args.slug}' provisioned successfully.")
        print(f"[INFO] Storage Mode : {res['tenant']['db_mode']}")
        print(f"[INFO] Storage Region: {res['tenant']['storage_region']}")
        print(f"[INFO] Admin Phone   : {res['admin_user']['phone_number']}")
        print(f"[INFO] Audit Hash    : {res['audit_record']['record_hash']}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Provisioning failed: {exc}", file=sys.stderr)
        return 1


def handle_archive(args: argparse.Namespace) -> int:
    """Handle tenant archive / decommissioning command."""
    mgr = TenantLifecycleManager()
    try:
        res = mgr.archive_tenant(slug=args.slug, performed_by=args.performed_by)
        print(f"[SUCCESS] Tenant '{args.slug}' archived successfully.")
        print(f"[INFO] Total Audit Records Exported: {res['audit_records_count']}")
        if args.export_file:
            with open(args.export_file, "w", encoding="utf-8") as f:
                json.dump(res["audit_trail_bundle"], f, indent=2)
            print(f"[INFO] Audit bundle exported to: {args.export_file}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Archiving failed: {exc}", file=sys.stderr)
        return 1


def handle_clone(args: argparse.Namespace) -> int:
    """Handle deep tenant cloning command."""
    mgr = TenantLifecycleManager()
    try:
        res = mgr.deep_clone_tenant(
            source_slug=args.source_slug,
            target_slug=args.target_slug,
            target_name=args.target_name,
            performed_by=args.performed_by,
        )
        print(f"[SUCCESS] Cloned '{args.source_slug}' -> '{args.target_slug}'.")
        print(f"[INFO] Cloned Users Count : {res['cloned_users_count']}")
        print(f"[INFO] Copied Tables Rows : {res['copied_tables']}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Deep-Clone failed: {exc}", file=sys.stderr)
        return 1


def handle_transfer(args: argparse.Namespace) -> int:
    """Handle tenant migration and region transfer command."""
    mgr = TenantLifecycleManager()
    try:
        res = mgr.transfer_tenant(
            slug=args.slug,
            target_db_url=args.target_db_url,
            target_region=args.target_region,
            performed_by=args.performed_by,
        )
        print(f"[SUCCESS] Tenant '{args.slug}' transferred successfully.")
        print(f"[INFO] Target Region: {res['storage_region']}")
        print(f"[INFO] Database URL  : {res['db_connection_url'] or 'Unchanged'}")
        print(f"[INFO] Streamed Data : {res['copied_tables']}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Transfer failed: {exc}", file=sys.stderr)
        return 1


def handle_set_byok(args: argparse.Namespace) -> int:
    """Configure Bring-Your-Own-Key credentials for a tenant."""
    vault = DevOpsKeyVault()
    try:
        vault.configure_tenant_credentials(
            tenant_id=args.slug,
            credential_mode="CUSTOMER_BYOK",
            gemini_api_key=args.gemini_key,
            openai_api_key=args.openai_key,
            waba_access_token=args.waba_token,
            waba_phone_number_id=args.waba_phone_id,
        )
        print(f"[SUCCESS] BYOK credentials configured for tenant '{args.slug}'.")
        print("[INFO] Encryption: AES-256-GCM encrypted in database at rest.")
        print("[INFO] Mode: CUSTOMER_BYOK (Zero fallback to platform keys).")
        return 0
    except Exception as exc:
        print(f"[ERROR] Setting BYOK failed: {exc}", file=sys.stderr)
        return 1


def handle_set_platform_managed(args: argparse.Namespace) -> int:
    """Revert tenant to Platform-Managed key vault credentials."""
    vault = DevOpsKeyVault()
    try:
        vault.configure_tenant_credentials(
            tenant_id=args.slug,
            credential_mode="PLATFORM_MANAGED",
        )
        print(f"[SUCCESS] Reverted tenant '{args.slug}' to PLATFORM_MANAGED keys.")
        print("[INFO] Tenant will use central platform LLM & WhatsApp credentials.")
        return 0
    except Exception as exc:
        print(f"[ERROR] Resetting credentials failed: {exc}", file=sys.stderr)
        return 1


def handle_list_tenants(args: argparse.Namespace) -> int:
    """List all tenants in the system."""
    mgr = TenantLifecycleManager()
    with mgr.session_factory() as session:
        tenants = list(session.scalars(select(Tenant).order_by(Tenant.id)).all())
        if not tenants:
            print("[INFO] No tenants found in registry.")
            return 0

        headers = ["Slug", "Name", "Status", "Tier", "DB Mode", "Region", "Max Users"]
        rows = [
            [
                t.id,
                t.name,
                t.status,
                t.license_tier,
                t.db_mode,
                t.storage_region,
                str(t.max_users),
            ]
            for t in tenants
        ]
        print(format_table(headers, rows))
        return 0


def handle_audit_trail(args: argparse.Namespace) -> int:
    """Display SHA-256 tamper-evident audit history for a tenant."""
    mgr = TenantLifecycleManager()
    with mgr.session_factory() as session:
        stmt = (
            select(TenantAuditLog)
            .where(TenantAuditLog.tenant_id == args.slug)
            .order_by(TenantAuditLog.id.asc())
        )
        logs = list(session.scalars(stmt).all())
        if not logs:
            print(f"[INFO] No audit logs found for tenant '{args.slug}'.")
            return 0

        headers = ["ID", "Action", "Performed By", "Timestamp (UTC)", "Record Hash (Prefix)"]
        rows = [
            [
                str(l.id),
                l.action,
                l.performed_by,
                l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                f"{l.record_hash[:16]}...",
            ]
            for l in logs
        ]
        print(format_table(headers, rows))
        return 0


def handle_verify_audit(args: argparse.Namespace) -> int:
    """Verify SHA-256 cryptographic hash chaining on audit trail."""
    import hashlib

    mgr = TenantLifecycleManager()
    with mgr.session_factory() as session:
        stmt = (
            select(TenantAuditLog)
            .where(TenantAuditLog.tenant_id == args.slug)
            .order_by(TenantAuditLog.id.asc())
        )
        logs = list(session.scalars(stmt).all())
        if not logs:
            print(f"[INFO] No audit logs to verify for '{args.slug}'.")
            return 0

        current_prev = GENESIS_HASH
        for l in logs:
            if l.prev_hash != current_prev:
                print(
                    f"[TAMPER_DETECTED] Chain break at ID={l.id}! "
                    f"Expected prev_hash={current_prev}, Got={l.prev_hash}",
                    file=sys.stderr,
                )
                return 1

            computed_hash = compute_audit_hash(
                prev_hash=l.prev_hash,
                timestamp=l.timestamp,
                action=l.action,
                payload_str=l.payload_json or "{}",
            )
            if computed_hash != l.record_hash:
                print(
                    f"[TAMPER_DETECTED] Content hash mismatch at ID={l.id}! "
                    f"Computed={computed_hash}, Stored={l.record_hash}",
                    file=sys.stderr,
                )
                return 1

            current_prev = l.record_hash

        print(f"[SUCCESS] Verified {len(logs)} audit records for tenant '{args.slug}'. 0 tamper anomalies.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    """Build command line interface parser."""
    parser = argparse.ArgumentParser(
        prog="ops-cli",
        description="Release100 Enterprise Multi-Tenant DevOps Control Plane CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Provision
    p_prov = subparsers.add_parser("provision", help="Provision a new tenant and isolated DB")
    p_prov.add_argument("--slug", required=True, help="Unique tenant identifier (e.g. acme_corp)")
    p_prov.add_argument("--name", required=True, help="Display business name")
    p_prov.add_argument("--admin-phone", required=True, help="Initial admin phone number (E.164)")
    p_prov.add_argument("--admin-name", required=True, help="Initial admin full name")
    p_prov.add_argument("--license-tier", default="ENTERPRISE", help="License tier (STANDARD, ENTERPRISE, DEDICATED)")
    p_prov.add_argument("--max-users", type=int, default=50, help="User seat limit")
    p_prov.add_argument("--region", default="ap-south-1", help="Target cloud / storage region")
    p_prov.add_argument("--db-dialect", default="sqlite", choices=["sqlite", "postgresql"], help="DB storage engine")
    p_prov.add_argument("--db-url", default=None, help="Explicit connection string override")
    p_prov.add_argument("--custom-domain", default=None, help="Custom vanity CNAME (e.g. mail.acme.com)")
    p_prov.add_argument("--performed-by", default="devops_admin", help="Operator identity")
    p_prov.set_defaults(func=handle_provision)

    # 2. Archive
    p_arch = subparsers.add_parser("archive", help="Decommission and archive a tenant")
    p_arch.add_argument("--slug", required=True, help="Tenant identifier to archive")
    p_arch.add_argument("--export-file", default=None, help="File path to save JSON audit export")
    p_arch.add_argument("--performed-by", default="devops_admin", help="Operator identity")
    p_arch.set_defaults(func=handle_archive)

    # 3. Clone
    p_clone = subparsers.add_parser("clone", help="Deep-clone tenant schema, config, and data")
    p_clone.add_argument("--source-slug", required=True, help="Source tenant identifier")
    p_clone.add_argument("--target-slug", required=True, help="New target tenant identifier")
    p_clone.add_argument("--target-name", default=None, help="New target display name")
    p_clone.add_argument("--performed-by", default="devops_admin", help="Operator identity")
    p_clone.set_defaults(func=handle_clone)

    # 4. Transfer
    p_xfer = subparsers.add_parser("transfer", help="Migrate database connection and storage region")
    p_xfer.add_argument("--slug", required=True, help="Tenant identifier to transfer")
    p_xfer.add_argument("--target-db-url", default=None, help="Destination database connection URL")
    p_xfer.add_argument("--target-region", default=None, help="Destination cloud region code")
    p_xfer.add_argument("--performed-by", default="devops_admin", help="Operator identity")
    p_xfer.set_defaults(func=handle_transfer)

    # 5. Set BYOK
    p_byok = subparsers.add_parser("set-byok", help="Configure dedicated customer BYOK credentials")
    p_byok.add_argument("--slug", required=True, help="Tenant identifier")
    p_byok.add_argument("--gemini-key", default=None, help="Google Gemini API key")
    p_byok.add_argument("--openai-key", default=None, help="OpenAI API key")
    p_byok.add_argument("--waba-token", default=None, help="WhatsApp Cloud API Access Token")
    p_byok.add_argument("--waba-phone-id", default=None, help="WhatsApp Phone Number ID")
    p_byok.set_defaults(func=handle_set_byok)

    # 6. Set Platform Managed
    p_plat = subparsers.add_parser("set-platform-managed", help="Revert tenant to central platform keys")
    p_plat.add_argument("--slug", required=True, help="Tenant identifier")
    p_plat.set_defaults(func=handle_set_platform_managed)

    # 7. List Tenants
    p_list = subparsers.add_parser("list-tenants", help="List all registered tenants")
    p_list.set_defaults(func=handle_list_tenants)

    # 8. Audit Trail
    p_audit = subparsers.add_parser("audit-trail", help="Display audit trail for a tenant")
    p_audit.add_argument("--slug", required=True, help="Tenant identifier")
    p_audit.set_defaults(func=handle_audit_trail)

    # 9. Verify Audit
    p_v = subparsers.add_parser("verify-audit", help="Verify SHA-256 hash chaining integrity")
    p_v.add_argument("--slug", required=True, help="Tenant identifier")
    p_v.set_defaults(func=handle_verify_audit)

    return parser


def main() -> None:
    """CLI execution entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    code = args.func(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
