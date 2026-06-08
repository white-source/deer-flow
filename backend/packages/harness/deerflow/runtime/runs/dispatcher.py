"""Global run dispatcher — worker pool and per-thread queue draining."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .manager import RunManager, RunRecord
from .queue import ThreadRunQueue
from .schemas import RunStatus

logger = logging.getLogger(__name__)


def _is_superseded_status(value: Any) -> bool:
    return isinstance(value, str) and value.lower() == "superseded"


def _record_is_superseded(record: RunRecord, launch_ctx: LaunchContext | None) -> bool:
    if _is_superseded_status(record.metadata.get("revision_status")):
        return True
    if launch_ctx is None:
        return False

    configurable = launch_ctx.config.get("configurable")
    if isinstance(configurable, dict) and _is_superseded_status(configurable.get("revision_status")):
        return True

    context = launch_ctx.config.get("context")
    if isinstance(context, dict) and _is_superseded_status(context.get("revision_status")):
        return True

    return False


@dataclass
class LaunchContext:
    """Everything needed to start ``run_agent`` for a deferred run."""

    bridge: Any
    run_ctx: Any
    run_mgr: RunManager
    agent_factory: Any
    graph_input: dict[str, Any]
    config: dict[str, Any]
    stream_modes: list[str]
    stream_subgraphs: bool = False
    interrupt_before: list[str] | str | None = None
    interrupt_after: list[str] | str | None = None


LaunchCallable = Callable[[RunRecord, LaunchContext], Awaitable[None]]


@dataclass
class RunDispatcher:
    """Schedules runs with global concurrency limits and per-thread serialization."""

    workers: int
    queue: ThreadRunQueue
    run_manager: RunManager
    launch: LaunchCallable
    _launch_contexts: dict[str, LaunchContext] = field(default_factory=dict)
    _active_threads: set[str] = field(default_factory=set)
    _thread_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _semaphore: asyncio.Semaphore | None = field(default=None, init=False)
    _started: bool = field(default=False, init=False)
    _on_run_cancelled_external: Callable[[str, str], Awaitable[None]] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(max(1, self.workers))

    async def start(self) -> None:
        """Register the terminal handler so completed runs drain the queue."""
        self.run_manager.set_run_terminal_handler(self.on_run_finished)
        self.run_manager.set_on_run_cancelled(self._on_run_cancelled_bridge)
        self._started = True

    async def stop(self) -> None:
        """Clear the terminal handler on shutdown."""
        self.run_manager.set_run_terminal_handler(None)
        self.run_manager.set_on_run_cancelled(None)
        self._started = False

    def set_on_run_cancelled(
        self,
        handler: Callable[[str, str], Awaitable[None]] | None,
    ) -> None:
        """Register a handler invoked when a run is cancelled."""
        self._on_run_cancelled_external = handler

    async def _on_run_cancelled_bridge(self, thread_id: str, run_id: str) -> None:
        """Bridge: forward RunManager cancel events to the external handler."""
        if self._on_run_cancelled_external is not None:
            await self._on_run_cancelled_external(thread_id, run_id)

    def _thread_lock(self, thread_id: str) -> asyncio.Lock:
        lock = self._thread_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_locks[thread_id] = lock
        return lock

    async def submit(self, record: RunRecord, launch_ctx: LaunchContext) -> None:
        """Store launch context and start execution when the thread is idle."""
        self._launch_contexts[record.run_id] = launch_ctx
        if _record_is_superseded(record, launch_ctx):
            logger.info("Skipping superseded run %s on thread %s", record.run_id, record.thread_id)
            self._launch_contexts.pop(record.run_id, None)
            await self.run_manager.set_status(
                record.run_id,
                RunStatus.interrupted,
                error="Run superseded before dispatch",
            )
            return
        if record.status == RunStatus.queued:
            return

        async with self._thread_lock(record.thread_id):
            if record.thread_id in self._active_threads:
                # When the previous run was cancelled via create_or_reject
                # (interrupt/rollback), its worker hasn't finished cleanup
                # yet. Enqueue the new run so _drain_thread picks it up
                # when the old worker completes, instead of rejecting it.
                if record.multitask_strategy in ("interrupt", "rollback"):
                    await self.queue.enqueue(record.thread_id, record.run_id)
                    await self.run_manager.set_status(record.run_id, RunStatus.queued)
                    return
                logger.warning(
                    "Thread %s already has an active run; run %s was not started",
                    record.thread_id,
                    record.run_id,
                )
                return
            self._active_threads.add(record.thread_id)

        asyncio.create_task(self._execute(record))

    async def on_run_finished(self, thread_id: str, run_id: str) -> None:
        """Drain the next queued run for *thread_id* after *run_id* completes."""
        self._launch_contexts.pop(run_id, None)
        await self._drain_thread(thread_id)

    async def _execute(self, record: RunRecord) -> None:
        assert self._semaphore is not None
        try:
            async with self._semaphore:
                launch_ctx = self._launch_contexts.get(record.run_id)
                if launch_ctx is None:
                    logger.warning("Missing launch context for run %s", record.run_id)
                    return
                logger.info(
                    "Dispatching run %s on thread %s (queue_depth=%d, workers=%d)",
                    record.run_id,
                    record.thread_id,
                    await self.queue.depth(record.thread_id),
                    self.workers,
                )
                await self.launch(record, launch_ctx)
                if record.task is not None:
                    try:
                        await record.task
                    except asyncio.CancelledError:
                        pass
        finally:
            if record.status in (RunStatus.pending, RunStatus.queued):
                await self._release_thread_if_idle(record.thread_id)

    async def _drain_thread(self, thread_id: str) -> None:
        while True:
            next_run_id = await self.queue.dequeue(thread_id)
            if next_run_id is None:
                async with self._thread_lock(thread_id):
                    self._active_threads.discard(thread_id)
                return

            record = await self.run_manager.get(next_run_id)
            if record is None or record.status != RunStatus.queued:
                continue

            launch_ctx = self._launch_contexts.get(next_run_id)
            if launch_ctx is None:
                logger.warning("Missing launch context for queued run %s", next_run_id)
                continue
            if _record_is_superseded(record, launch_ctx):
                logger.info("Skipping queued superseded run %s on thread %s", next_run_id, thread_id)
                self._launch_contexts.pop(next_run_id, None)
                await self.run_manager.set_status(
                    next_run_id,
                    RunStatus.interrupted,
                    error="Queued run superseded before dispatch",
                )
                continue

            async with self._thread_lock(thread_id):
                self._active_threads.add(thread_id)

            await self.run_manager.set_status(next_run_id, RunStatus.pending)
            record.status = RunStatus.pending
            asyncio.create_task(self._execute(record))
            return

    async def _release_thread_if_idle(self, thread_id: str) -> None:
        if not await self.run_manager.has_inflight(thread_id):
            async with self._thread_lock(thread_id):
                if not await self.run_manager.has_inflight(thread_id):
                    self._active_threads.discard(thread_id)

    async def queue_position(self, thread_id: str, run_id: str) -> int | None:
        return await self.queue.position(thread_id, run_id)
