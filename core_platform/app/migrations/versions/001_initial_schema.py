"""Initial schema migration: employees, attendance_records, outbox_queue, mail models.

Revision ID: 001_initial_schema
Revises: (none — genesis migration)
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op  # type: ignore[import-not-found]
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all initial tables for temperature_marker and mail_organizer."""

    # ── Temperature Marker: employees ─────────────────────────────────────────
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("emp_code", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False, unique=True, index=True),
        sa.Column("assigned_kiosk_id", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("encrypted_face_embedding", sa.Text(), nullable=True),
        sa.Column(
            "created_at_utc",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )

    # ── Temperature Marker: attendance_records ────────────────────────────────
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("correlation_id", sa.String(64), nullable=False, index=True),
        sa.Column("emp_code", sa.String(64), nullable=False, index=True),
        sa.Column("kiosk_id", sa.String(64), nullable=False, index=True),
        sa.Column(
            "checkin_time_utc",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("face_confidence", sa.Float(), nullable=False),
        sa.Column("gps_distance_meters", sa.Float(), nullable=False),
        sa.Column("geofence_verified", sa.Boolean(), nullable=False),
        sa.Column("chiller_temp_c", sa.Float(), nullable=False),
        sa.Column("haccp_compliant", sa.Boolean(), nullable=False),
        sa.Column("haccp_status", sa.String(32), nullable=False),
        sa.Column("ocr_engine_used", sa.String(64), nullable=True, server_default="local_seven_segment"),
        sa.Column(
            "created_at_utc",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )

    # ── Temperature Marker: outbox_queue ──────────────────────────────────────
    op.create_table(
        "outbox_queue",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("correlation_id", sa.String(64), nullable=False, index=True),
        sa.Column("target_gateway", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at_utc",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column("synced_at_utc", sa.DateTime(), nullable=True),
    )

    # ── Mail Organizer: emails ────────────────────────────────────────────────
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("gmail_id", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("thread_id", sa.String(255), nullable=True, index=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("sender", sa.String(255), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("ownership", sa.String(64), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )

    # ── Mail Organizer: drafts ────────────────────────────────────────────────
    op.create_table(
        "drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("gmail_id", sa.String(255), nullable=False, index=True),
        sa.Column("thread_id", sa.String(255), nullable=True),
        sa.Column("recipient", sa.String(255), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )

    # ── Mail Organizer: pm_tasks ──────────────────────────────────────────────
    op.create_table(
        "pm_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("gmail_id", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(32), nullable=True),
        sa.Column("due_date", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING_APPROVAL"),
        sa.Column("destination", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Drop all tables created in this migration."""
    op.drop_table("pm_tasks")
    op.drop_table("drafts")
    op.drop_table("emails")
    op.drop_table("outbox_queue")
    op.drop_table("attendance_records")
    op.drop_table("employees")
