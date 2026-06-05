"""Tests for revision registry persistence and lifecycle rules."""

from __future__ import annotations

import pytest

from deerflow.persistence.run_revision.sql import RunRevisionRepository
from deerflow.runtime.revisions.registry import RevisionRegistry


@pytest.fixture
async def registry(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'revision_registry.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))

    repo = RunRevisionRepository(get_session_factory())
    try:
        yield RevisionRegistry(repo)
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_one_active_revision_per_root_run(registry: RevisionRegistry):
    root = await registry.create_root_run(thread_id="t1", created_by_message_id="m1")
    r1 = await registry.create_initial_revision(root.root_run_id)
    r2 = await registry.fork_revision(parent_revision_id=r1.revision_id, reason="inject")

    latest = await registry.get_active_revision(root.root_run_id)
    assert latest is not None
    assert latest.revision_id == r2.revision_id
    assert latest.checkpoint_namespace == f"run:{root.root_run_id}:rev:{r2.revision_id}"


@pytest.mark.asyncio
async def test_superseded_cannot_resume(registry: RevisionRegistry):
    root = await registry.create_root_run(thread_id="t1", created_by_message_id="m1")
    r1 = await registry.create_initial_revision(root.root_run_id)
    await registry.fork_revision(parent_revision_id=r1.revision_id, reason="inject")

    with pytest.raises(ValueError, match="superseded -> running is not allowed"):
        await registry.transition_revision(r1.revision_id, "running")


@pytest.mark.asyncio
async def test_create_initial_revision_returns_active_record(registry: RevisionRegistry):
    root = await registry.create_root_run(thread_id="t1", created_by_message_id="m1")
    r1 = await registry.create_initial_revision(root.root_run_id)
    assert r1.is_active is True


@pytest.mark.asyncio
async def test_set_active_revision_rejects_cross_root(registry: RevisionRegistry):
    root1 = await registry.create_root_run(thread_id="t1", created_by_message_id="m1")
    root2 = await registry.create_root_run(thread_id="t2", created_by_message_id="m2")
    r1 = await registry.create_initial_revision(root1.root_run_id)
    _ = await registry.create_initial_revision(root2.root_run_id)

    with pytest.raises(ValueError, match="not found under root"):
        await registry._repo.set_active_revision(
            root_run_id=root2.root_run_id,
            revision_id=r1.revision_id,
        )
