"""SQLAlchemy-backed persistence for root runs and revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.run_revision.model import RevisionRow, RootRunRow
from deerflow.utils.time import coerce_iso


@dataclass(slots=True)
class RootRunRecord:
    root_run_id: str
    thread_id: str
    created_by_message_id: str | None
    status_summary: str
    foreground_state: str
    latest_revision_id: str | None
    created_at: str
    updated_at: str


@dataclass(slots=True)
class RevisionRecord:
    revision_id: str
    root_run_id: str
    parent_revision_id: str | None
    supersedes_revision_id: str | None
    status: str
    execution_mode: str
    checkpoint_namespace: str
    reason: str | None
    is_active: bool
    created_at: str
    updated_at: str


class RunRevisionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _root_row_to_record(row: RootRunRow) -> RootRunRecord:
        return RootRunRecord(
            root_run_id=row.root_run_id,
            thread_id=row.thread_id,
            created_by_message_id=row.created_by_message_id,
            status_summary=row.status_summary,
            foreground_state=row.foreground_state,
            latest_revision_id=row.latest_revision_id,
            created_at=coerce_iso(row.created_at),
            updated_at=coerce_iso(row.updated_at),
        )

    @staticmethod
    def _revision_row_to_record(row: RevisionRow) -> RevisionRecord:
        return RevisionRecord(
            revision_id=row.revision_id,
            root_run_id=row.root_run_id,
            parent_revision_id=row.parent_revision_id,
            supersedes_revision_id=row.supersedes_revision_id,
            status=row.status,
            execution_mode=row.execution_mode,
            checkpoint_namespace=row.checkpoint_namespace,
            reason=row.reason,
            is_active=row.is_active,
            created_at=coerce_iso(row.created_at),
            updated_at=coerce_iso(row.updated_at),
        )

    async def create_root_run(
        self,
        *,
        root_run_id: str,
        thread_id: str,
        created_by_message_id: str | None,
    ) -> RootRunRecord:
        row = RootRunRow(
            root_run_id=root_run_id,
            thread_id=thread_id,
            created_by_message_id=created_by_message_id,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._root_row_to_record(row)

    async def get_root_run(self, root_run_id: str) -> RootRunRecord | None:
        async with self._sf() as session:
            row = await session.get(RootRunRow, root_run_id)
            if row is None:
                return None
            return self._root_row_to_record(row)

    async def update_root_latest_revision(self, *, root_run_id: str, latest_revision_id: str) -> None:
        async with self._sf() as session:
            result = await session.execute(
                update(RootRunRow)
                .where(RootRunRow.root_run_id == root_run_id)
                .values(
                    latest_revision_id=latest_revision_id,
                    updated_at=datetime.now(UTC),
                )
            )
            if result.rowcount != 1:
                raise ValueError(f"root run not found: {root_run_id}")
            await session.commit()

    async def create_revision(
        self,
        *,
        revision_id: str,
        root_run_id: str,
        parent_revision_id: str | None,
        supersedes_revision_id: str | None,
        status: str,
        execution_mode: str,
        checkpoint_namespace: str,
        reason: str | None,
        is_active: bool,
    ) -> RevisionRecord:
        row = RevisionRow(
            revision_id=revision_id,
            root_run_id=root_run_id,
            parent_revision_id=parent_revision_id,
            supersedes_revision_id=supersedes_revision_id,
            status=status,
            execution_mode=execution_mode,
            checkpoint_namespace=checkpoint_namespace,
            reason=reason,
            is_active=is_active,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._revision_row_to_record(row)

    async def get_revision(self, revision_id: str) -> RevisionRecord | None:
        async with self._sf() as session:
            row = await session.get(RevisionRow, revision_id)
            if row is None:
                return None
            return self._revision_row_to_record(row)

    async def get_active_revision(self, root_run_id: str) -> RevisionRecord | None:
        stmt = select(RevisionRow).where(RevisionRow.root_run_id == root_run_id, RevisionRow.is_active.is_(True)).limit(1)
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return self._revision_row_to_record(row)

    async def set_active_revision(self, *, root_run_id: str, revision_id: str) -> None:
        now = datetime.now(UTC)
        async with self._sf() as session:
            async with session.begin():
                await session.execute(update(RevisionRow).where(RevisionRow.root_run_id == root_run_id).values(is_active=False, updated_at=now))
                activate_result = await session.execute(
                    update(RevisionRow)
                    .where(
                        RevisionRow.root_run_id == root_run_id,
                        RevisionRow.revision_id == revision_id,
                    )
                    .values(is_active=True, updated_at=now)
                )
                if activate_result.rowcount != 1:
                    raise ValueError(f"revision {revision_id} not found under root {root_run_id}")

                root_result = await session.execute(update(RootRunRow).where(RootRunRow.root_run_id == root_run_id).values(latest_revision_id=revision_id, updated_at=now))
                if root_result.rowcount != 1:
                    raise ValueError(f"root run not found: {root_run_id}")

    async def update_revision_status(self, *, revision_id: str, status: str) -> None:
        async with self._sf() as session:
            result = await session.execute(update(RevisionRow).where(RevisionRow.revision_id == revision_id).values(status=status, updated_at=datetime.now(UTC)))
            if result.rowcount != 1:
                raise ValueError(f"revision not found: {revision_id}")
            await session.commit()
