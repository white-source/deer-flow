"""ORM models for revision-aware run persistence."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class RootRunRow(Base):
    """Top-level run identity that owns one or more revisions."""

    __tablename__ = "root_runs"

    root_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by_message_id: Mapped[str | None] = mapped_column(String(64))
    status_summary: Mapped[str] = mapped_column(String(32), default="pending")
    foreground_state: Mapped[str] = mapped_column(String(16), default="foreground")
    latest_revision_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class RevisionRow(Base):
    """A single executable revision under a root run."""

    __tablename__ = "revisions"

    revision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    root_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("root_runs.root_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_revision_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("revisions.revision_id"),
        index=True,
    )
    supersedes_revision_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("revisions.revision_id"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    execution_mode: Mapped[str] = mapped_column(String(16), default="foreground")
    checkpoint_namespace: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        Index(
            "uq_revisions_one_active_per_root",
            "root_run_id",
            unique=True,
            sqlite_where=is_active.is_(True),
            postgresql_where=is_active.is_(True),
        ),
    )
