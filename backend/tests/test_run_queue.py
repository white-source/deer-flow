"""Tests for thread run queue and enqueue multitask strategy."""

from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.dispatcher import LaunchContext
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.queue import ThreadRunQueue
from deerflow.runtime.runs.schemas import RunStatus


def test_run_status_includes_queued():
    assert RunStatus.queued == "queued"
    assert "queued" in {s.value for s in RunStatus}


@pytest.mark.anyio
async def test_enqueue_returns_position():
    q = ThreadRunQueue(max_depth=10)
    assert await q.enqueue("thread-a", "run-1") == 1
    assert await q.enqueue("thread-a", "run-2") == 2
    assert await q.enqueue("thread-b", "run-1") == 1
    assert await q.position("thread-a", "run-2") == 2
    assert await q.position("thread-b", "run-1") == 1


@pytest.mark.anyio
async def test_dequeue_fifo_per_thread():
    q = ThreadRunQueue(max_depth=10)
    await q.enqueue("thread-a", "run-1")
    await q.enqueue("thread-a", "run-2")
    assert await q.dequeue("thread-a") == "run-1"
    assert await q.dequeue("thread-a") == "run-2"
    assert await q.dequeue("thread-a") is None


@pytest.mark.anyio
async def test_max_depth_raises():
    q = ThreadRunQueue(max_depth=2)
    await q.enqueue("t", "r1")
    await q.enqueue("t", "r2")
    with pytest.raises(OverflowError):
        await q.enqueue("t", "r3")


@pytest.mark.anyio
async def test_enqueue_second_run_becomes_queued():
    queue = ThreadRunQueue(max_depth=10)
    mgr = RunManager(queue=queue)

    first = await mgr.create_or_reject("thread-1", multitask_strategy="enqueue")
    first.status = RunStatus.running

    second = await mgr.create_or_reject("thread-1", multitask_strategy="enqueue")
    assert second.status == RunStatus.queued
    assert await queue.position("thread-1", second.run_id) == 1


@pytest.mark.anyio
async def test_enqueue_first_run_is_pending():
    queue = ThreadRunQueue(max_depth=10)
    mgr = RunManager(queue=queue)

    record = await mgr.create_or_reject("thread-1", multitask_strategy="enqueue")
    assert record.status == RunStatus.pending


@pytest.mark.anyio
async def test_dispatcher_runs_queued_runs_serially_per_thread():
    from deerflow.runtime.runs.dispatcher import RunDispatcher

    queue = ThreadRunQueue(max_depth=10)
    mgr = RunManager(queue=queue)
    launched: list[str] = []
    launch_events: list[asyncio.Event] = []

    async def fake_launch(record, _ctx):
        async def _run() -> None:
            launched.append(record.run_id)
            record.status = RunStatus.running
            event = asyncio.Event()
            launch_events.append(event)
            await event.wait()
            record.status = RunStatus.success
            await mgr.notify_run_terminal(record.thread_id, record.run_id)

        record.task = asyncio.create_task(_run())

    dispatcher = RunDispatcher(workers=2, queue=queue, run_manager=mgr, launch=fake_launch)
    await dispatcher.start()

    try:
        first = await mgr.create_or_reject("thread-1", multitask_strategy="enqueue")
        await dispatcher.submit(first, LaunchContext(
            bridge=None,
            run_ctx=None,
            run_mgr=mgr,
            agent_factory=None,
            graph_input={},
            config={},
            stream_modes=["values"],
        ))

        second = await mgr.create_or_reject("thread-1", multitask_strategy="enqueue")
        assert second.status == RunStatus.queued
        await dispatcher.submit(second, LaunchContext(
            bridge=None,
            run_ctx=None,
            run_mgr=mgr,
            agent_factory=None,
            graph_input={},
            config={},
            stream_modes=["values"],
        ))

        await asyncio.sleep(0.05)
        assert launched == [first.run_id]

        launch_events[0].set()
        await asyncio.sleep(0.1)

        assert launched == [first.run_id, second.run_id]
    finally:
        for event in launch_events:
            event.set()
        await dispatcher.stop()
