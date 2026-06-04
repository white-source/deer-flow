"""Per-thread FIFO queue for enqueued runs."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ThreadRunQueue:
    """FIFO queue of run IDs waiting to execute on a thread."""

    max_depth: int = 50
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _queues: dict[str, deque[str]] = field(default_factory=dict)

    async def enqueue(self, thread_id: str, run_id: str) -> int:
        async with self._lock:
            dq = self._queues.setdefault(thread_id, deque())
            if len(dq) >= self.max_depth:
                raise OverflowError(f"Thread {thread_id} run queue full (max={self.max_depth})")
            dq.append(run_id)
            return len(dq)

    async def position(self, thread_id: str, run_id: str) -> int | None:
        async with self._lock:
            dq = self._queues.get(thread_id)
            if not dq:
                return None
            try:
                return list(dq).index(run_id) + 1
            except ValueError:
                return None

    async def depth(self, thread_id: str) -> int:
        async with self._lock:
            dq = self._queues.get(thread_id)
            return len(dq) if dq else 0

    async def dequeue(self, thread_id: str) -> str | None:
        async with self._lock:
            dq = self._queues.get(thread_id)
            if not dq:
                return None
            run_id = dq.popleft()
            if not dq:
                self._queues.pop(thread_id, None)
            return run_id

    async def remove(self, thread_id: str, run_id: str) -> bool:
        async with self._lock:
            dq = self._queues.get(thread_id)
            if not dq:
                return False
            try:
                dq.remove(run_id)
            except ValueError:
                return False
            if not dq:
                self._queues.pop(thread_id, None)
            return True
