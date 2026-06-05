"""add run revision tables

Revision ID: 20260605_0001
Revises:
Create Date: 2026-06-05 00:01:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260605_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "root_runs",
        sa.Column("root_run_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_message_id", sa.String(length=64), nullable=True),
        sa.Column("status_summary", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("foreground_state", sa.String(length=16), nullable=False, server_default="foreground"),
        sa.Column("latest_revision_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("root_run_id"),
    )
    op.create_index(op.f("ix_root_runs_latest_revision_id"), "root_runs", ["latest_revision_id"], unique=False)
    op.create_index(op.f("ix_root_runs_thread_id"), "root_runs", ["thread_id"], unique=False)

    op.create_table(
        "revisions",
        sa.Column("revision_id", sa.String(length=64), nullable=False),
        sa.Column("root_run_id", sa.String(length=64), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=64), nullable=True),
        sa.Column("supersedes_revision_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("execution_mode", sa.String(length=16), nullable=False, server_default="foreground"),
        sa.Column("checkpoint_namespace", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["root_run_id"], ["root_runs.root_run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_revision_id"], ["revisions.revision_id"]),
        sa.ForeignKeyConstraint(["supersedes_revision_id"], ["revisions.revision_id"]),
        sa.PrimaryKeyConstraint("revision_id"),
    )
    op.create_index(op.f("ix_revisions_parent_revision_id"), "revisions", ["parent_revision_id"], unique=False)
    op.create_index(op.f("ix_revisions_root_run_id"), "revisions", ["root_run_id"], unique=False)
    op.create_index(op.f("ix_revisions_supersedes_revision_id"), "revisions", ["supersedes_revision_id"], unique=False)
    op.create_index(
        "uq_revisions_one_active_per_root",
        "revisions",
        ["root_run_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_revisions_one_active_per_root", table_name="revisions")
    op.drop_index(op.f("ix_revisions_supersedes_revision_id"), table_name="revisions")
    op.drop_index(op.f("ix_revisions_root_run_id"), table_name="revisions")
    op.drop_index(op.f("ix_revisions_parent_revision_id"), table_name="revisions")
    op.drop_table("revisions")

    op.drop_index(op.f("ix_root_runs_thread_id"), table_name="root_runs")
    op.drop_index(op.f("ix_root_runs_latest_revision_id"), table_name="root_runs")
    op.drop_table("root_runs")
