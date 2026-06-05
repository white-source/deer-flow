"""Registry for root runs and revision lifecycle operations."""

from __future__ import annotations

import uuid

from deerflow.persistence.run_revision.sql import RevisionRecord, RootRunRecord, RunRevisionRepository
from deerflow.runtime.revisions.schemas import RevisionStatus
from deerflow.runtime.revisions.state_machine import assert_transition_allowed


class RevisionRegistry:
    """Coordinates revision operations and enforces revision state rules."""

    def __init__(self, repository: RunRevisionRepository) -> None:
        self._repo = repository

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _checkpoint_namespace(root_run_id: str, revision_id: str) -> str:
        return f"run:{root_run_id}:rev:{revision_id}"

    async def create_root_run(self, *, thread_id: str, created_by_message_id: str | None) -> RootRunRecord:
        return await self._repo.create_root_run(
            root_run_id=self._new_id("root"),
            thread_id=thread_id,
            created_by_message_id=created_by_message_id,
        )

    async def create_initial_revision(self, root_run_id: str) -> RevisionRecord:
        revision_id = self._new_id("rev")
        record = await self._repo.create_revision(
            revision_id=revision_id,
            root_run_id=root_run_id,
            parent_revision_id=None,
            supersedes_revision_id=None,
            status=RevisionStatus.pending.value,
            execution_mode="foreground",
            checkpoint_namespace=self._checkpoint_namespace(root_run_id, revision_id),
            reason=None,
            is_active=False,
        )
        await self._repo.set_active_revision(root_run_id=root_run_id, revision_id=record.revision_id)
        updated = await self._repo.get_revision(record.revision_id)
        if updated is None:
            raise ValueError(f"revision not found after activation: {record.revision_id}")
        return updated

    async def get_active_revision(self, root_run_id: str) -> RevisionRecord | None:
        return await self._repo.get_active_revision(root_run_id)

    async def transition_revision(self, revision_id: str, nxt_status: str | RevisionStatus) -> RevisionRecord:
        revision = await self._repo.get_revision(revision_id)
        if revision is None:
            raise ValueError(f"revision not found: {revision_id}")

        current = RevisionStatus(revision.status)
        nxt = RevisionStatus(nxt_status)
        assert_transition_allowed(current, nxt)

        await self._repo.update_revision_status(revision_id=revision_id, status=nxt.value)
        updated = await self._repo.get_revision(revision_id)
        if updated is None:
            raise ValueError(f"revision not found after update: {revision_id}")
        return updated

    async def fork_revision(self, *, parent_revision_id: str, reason: str) -> RevisionRecord:
        parent = await self._repo.get_revision(parent_revision_id)
        if parent is None:
            raise ValueError(f"revision not found: {parent_revision_id}")

        if parent.status == RevisionStatus.pending.value:
            await self.transition_revision(parent.revision_id, RevisionStatus.running)
        await self.transition_revision(parent.revision_id, RevisionStatus.superseded)

        revision_id = self._new_id("rev")
        child = await self._repo.create_revision(
            revision_id=revision_id,
            root_run_id=parent.root_run_id,
            parent_revision_id=parent.revision_id,
            supersedes_revision_id=parent.revision_id,
            status=RevisionStatus.pending.value,
            execution_mode=parent.execution_mode,
            checkpoint_namespace=self._checkpoint_namespace(parent.root_run_id, revision_id),
            reason=reason,
            is_active=False,
        )
        await self._repo.set_active_revision(root_run_id=parent.root_run_id, revision_id=child.revision_id)
        updated = await self._repo.get_revision(child.revision_id)
        if updated is None:
            raise ValueError(f"revision not found after activation: {child.revision_id}")
        return updated

    async def switch_active_revision(self, *, thread_id: str, revision_id: str) -> None:
        """Switch active revision for a thread-scoped root run.

        Returns
        -------
        None
            Raises ValueError when revision/root is missing or belongs to another thread.
        """

        revision = await self._repo.get_revision(revision_id)
        if revision is None:
            raise ValueError(f"revision not found: {revision_id}")

        root_run = await self._repo.get_root_run(revision.root_run_id)
        if root_run is None:
            raise ValueError(f"root run not found: {revision.root_run_id}")

        if root_run.thread_id != thread_id:
            raise ValueError("revision not found")

        await self._repo.set_active_revision(
            root_run_id=root_run.root_run_id,
            revision_id=revision_id,
        )
