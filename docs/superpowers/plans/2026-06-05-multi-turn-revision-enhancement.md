# Revision Runtime Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement checkpoint inheritance for inject and cancel→revision linkage, covering product scenarios 情况2/3/4.

**Architecture:** Three small, focused changes: (1) `fork_revision()` child inherits parent's checkpoint namespace instead of creating an independent one; (2) `RunManager.cancel()` triggers a callback that transitions the linked revision to `cancelled`; (3) `start_run()` stores `revision_id` in run metadata so the cancel callback can find which revision to update.

**Tech Stack:** Python 3.12+, asyncio, FastAPI, SQLAlchemy (async), pytest

**Note:** The state machine (`state_machine.py`) already defines `running/paused/awaiting_action → cancelled` transitions — no change needed there.

---

## File Map

| File | Responsibility | Change |
|---|---|---|
| `runtime/revisions/registry.py` | Revision lifecycle, `fork_revision()` | 1 line: child inherits parent's `checkpoint_namespace` |
| `runtime/runs/manager.py` | Run lifecycle, `cancel()` | Add `_on_run_cancelled` callback slot + call it in `cancel()` |
| `runtime/runs/dispatcher.py` | Run scheduling, callback wiring | Add `set_on_run_cancelled` + delegate to `RunManager` |
| `app/gateway/services.py` | `start_run()` business logic | Store `revision_id` in run metadata |
| `app/gateway/deps.py` | Runtime bootstrap | Wire cancel→revision callback |
| `tests/test_revision_registry.py` | Registry tests | Update assertion; add inheritance test |
| `tests/test_run_queue.py` | Dispatcher tests | Update `_FakeRunManager` |
| `tests/test_run_queue_http.py` | Dispatcher HTTP tests | Update `_FakeRunManager` |
| `tests/test_worker_langfuse_metadata.py` | Worker test fake | Update `_FakeRunManager` |
| `tests/test_gateway_run_recovery.py` | Recovery test fake | Update `_FakeRunManager` |
| `tests/test_revision_state_machine.py` | State machine tests | Add cancel transition coverage tests |

---

### Task 1: Checkpoint Inheritance — Child Inherits Parent Namespace

**Files:**
- Modify: `backend/packages/harness/deerflow/runtime/revisions/registry.py:87`
- Modify: `backend/tests/test_revision_registry.py:33-34`

- [ ] **Step 1: Update the existing test assertion to match new behavior**

The current test at line 33-34 asserts child has its own namespace. Change it to expect inheritance:

```python
# In test_one_active_revision_per_root_run, change lines 33-34 from:
    assert latest.checkpoint_namespace == f"run:{root.root_run_id}:rev:{r2.revision_id}"

# To:
    assert latest.checkpoint_namespace == r1.checkpoint_namespace
```

Full updated test:

```python
@pytest.mark.asyncio
async def test_one_active_revision_per_root_run(registry: RevisionRegistry):
    root = await registry.create_root_run(thread_id="t1", created_by_message_id="m1")
    r1 = await registry.create_initial_revision(root.root_run_id)
    r2 = await registry.fork_revision(parent_revision_id=r1.revision_id, reason="inject")

    latest = await registry.get_active_revision(root.root_run_id)
    assert latest is not None
    assert latest.revision_id == r2.revision_id
    # Child inherits parent's checkpoint namespace
    assert latest.checkpoint_namespace == r1.checkpoint_namespace
```

- [ ] **Step 2: Add a dedicated checkpoint inheritance test**

```python
@pytest.mark.asyncio
async def test_forked_revision_inherits_parent_checkpoint_namespace(registry: RevisionRegistry):
    """Child revision must share its parent's checkpoint namespace so graph
    execution continues from the parent's last checkpoint rather than starting
    from an empty state."""
    root = await registry.create_root_run(thread_id="t1", created_by_message_id="m1")
    parent = await registry.create_initial_revision(root.root_run_id)

    child = await registry.fork_revision(
        parent_revision_id=parent.revision_id, reason="inject"
    )

    assert child.checkpoint_namespace == parent.checkpoint_namespace
    assert child.parent_revision_id == parent.revision_id
    assert child.supersedes_revision_id == parent.revision_id
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/test_revision_registry.py::test_one_active_revision_per_root_run tests/test_revision_registry.py::test_forked_revision_inherits_parent_checkpoint_namespace -v`

Expected: `test_forked_revision_inherits_parent_checkpoint_namespace` FAILS (child gets its own namespace); `test_one_active_revision_per_root_run` FAILS (assertion mismatch).

- [ ] **Step 4: Implement checkpoint inheritance — 1 line change**

In `registry.py`, change `fork_revision()` line 87 from:

```python
            checkpoint_namespace=self._checkpoint_namespace(parent.root_run_id, revision_id),
```

To:

```python
            checkpoint_namespace=parent.checkpoint_namespace,
```

Full updated `fork_revision()` method (lines 70-95):

```python
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
            checkpoint_namespace=parent.checkpoint_namespace,
            reason=reason,
            is_active=False,
        )
        await self._repo.set_active_revision(root_run_id=parent.root_run_id, revision_id=child.revision_id)
        updated = await self._repo.get_revision(child.revision_id)
        if updated is None:
            raise ValueError(f"revision not found after activation: {child.revision_id}")
        return updated
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/test_revision_registry.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd backend
git add packages/harness/deerflow/runtime/revisions/registry.py tests/test_revision_registry.py
git commit -m "feat: child revision inherits parent checkpoint namespace on fork

fork_revision() now passes parent.checkpoint_namespace to the child
instead of generating a new independent namespace. This means the
child's graph execution continues from the parent's last checkpoint
rather than starting from an empty state.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Store revision_id in Run Metadata

**Files:**
- Modify: `backend/app/gateway/services.py:370-380`

- [ ] **Step 1: Add metadata injection in start_run()**

After the checkpoint namespace injection block (lines 376-380), store `revision_id` and `root_run_id` in run metadata so the cancel callback can find the associated revision.

In `services.py`, replace lines 376-380 from:

```python
    if _revision_runtime_enabled() and isinstance(root_run_id, str) and root_run_id and isinstance(revision_id, str) and revision_id:
        config.setdefault("configurable", {}).setdefault(
            "checkpoint_ns",
            build_checkpoint_namespace(root_run_id, revision_id),
        )
```

To:

```python
    if _revision_runtime_enabled() and isinstance(root_run_id, str) and root_run_id and isinstance(revision_id, str) and revision_id:
        config.setdefault("configurable", {}).setdefault(
            "checkpoint_ns",
            build_checkpoint_namespace(root_run_id, revision_id),
        )
        # Store revision coordinates in run metadata so cancel callbacks
        # can locate and transition the associated revision.
        body.metadata = body.metadata or {}
        body.metadata.setdefault("revision_id", revision_id)
        body.metadata.setdefault("root_run_id", root_run_id)
```

Note: This code runs BEFORE `run_mgr.create_or_reject()` (line 334), but `body.metadata` is passed at line 338. Since `body.metadata` is mutated in place before `create_or_reject()` is called, the revision fields will be present in the created `RunRecord.metadata`.

Wait — let's verify the ordering. Looking at `start_run()`:

1. Line 333-342: `run_mgr.create_or_reject(..., metadata=body.metadata or {}, ...)` — record is created HERE
2. Line 376-380: checkpoint_ns injection happens AFTER create_or_reject

So the metadata injection at lines 376-380 is too late — the record already exists! The `body.metadata` mutation after `create_or_reject()` won't update the record.

Let me restructure the plan for this task:

- [ ] **Step 1 (revised): Move revision metadata injection BEFORE create_or_reject()**

We need to inject `revision_id` into `body.metadata` before `run_mgr.create_or_reject()` is called at line 334.

In `services.py`, insert the metadata injection block BEFORE the `create_or_reject()` call. The checkpoint_ns injection can remain where it is (it modifies `config`, not `body.metadata`).

Current code order (lines 316-342):

```python
    body_context = getattr(body, "context", None) or {}
    model_name = body_context.get("model_name")

    # ... model validation ...

    try:
        record = await run_mgr.create_or_reject(
            thread_id,
            body.assistant_id,
            on_disconnect=disconnect,
            metadata=body.metadata or {},
            kwargs={"input": body.input, "config": body.config},
            multitask_strategy=body.multitask_strategy,
            model_name=model_name,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except UnsupportedStrategyError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
```

We need to add the metadata injection between the model validation and the `create_or_reject()` call. Here's the change:

```python
    body_context = getattr(body, "context", None) or {}
    model_name = body_context.get("model_name")

    # ... model validation (lines 319-331) remains unchanged ...

    # Store revision coordinates in run metadata before record creation
    # so cancel callbacks can locate and transition the associated revision.
    context = getattr(body, "context", None) or {}
    root_run_id = context.get("root_run_id")
    revision_id = context.get("revision_id")
    if _revision_runtime_enabled() and isinstance(root_run_id, str) and root_run_id and isinstance(revision_id, str) and revision_id:
        body.metadata = body.metadata or {}
        body.metadata.setdefault("revision_id", revision_id)
        body.metadata.setdefault("root_run_id", root_run_id)

    try:
        record = await run_mgr.create_or_reject(
            thread_id,
            body.assistant_id,
            on_disconnect=disconnect,
            metadata=body.metadata or {},
            kwargs={"input": body.input, "config": body.config},
            multitask_strategy=body.multitask_strategy,
            model_name=model_name,
        )
    except ConflictError as exc:
        ...
```

And then the existing checkpoint_ns injection block (lines 373-380) also needs `root_run_id`/`revision_id` — but those are already extracted at line 373-374. We're just adding a second extraction earlier. To avoid duplicate extraction, move the extraction up:

**Actually, let me take a cleaner approach.** Move the `context` / `root_run_id` / `revision_id` extraction to before `create_or_reject()`, inject metadata there, and reuse the same variables for the checkpoint_ns injection later.

Here's the complete change in `services.py`:

**Before (lines 316-342, then 373-380):**
```python
    body_context = getattr(body, "context", None) or {}
    model_name = body_context.get("model_name")

    # ... model validation ...

    try:
        record = await run_mgr.create_or_reject(
            thread_id,
            body.assistant_id,
            on_disconnect=disconnect,
            metadata=body.metadata or {},
            ...
        )
```

And later (lines 373-380):
```python
    context = getattr(body, "context", None) or {}
    root_run_id = context.get("root_run_id")
    revision_id = context.get("revision_id")
    if _revision_runtime_enabled() and isinstance(root_run_id, str) and root_run_id and isinstance(revision_id, str) and revision_id:
        config.setdefault("configurable", {}).setdefault(
            "checkpoint_ns",
            build_checkpoint_namespace(root_run_id, revision_id),
        )
```

**After:**
```python
    body_context = getattr(body, "context", None) or {}
    model_name = body_context.get("model_name")

    # ... model validation (unchanged) ...

    # Resolve revision coordinates early so they can be injected into
    # both run metadata (for cancel linkage) and graph config (for
    # checkpoint namespace isolation).
    context = getattr(body, "context", None) or {}
    root_run_id = context.get("root_run_id")
    revision_id = context.get("revision_id")
    if _revision_runtime_enabled() and isinstance(root_run_id, str) and root_run_id and isinstance(revision_id, str) and revision_id:
        body.metadata = body.metadata or {}
        body.metadata.setdefault("revision_id", revision_id)
        body.metadata.setdefault("root_run_id", root_run_id)

    try:
        record = await run_mgr.create_or_reject(
            thread_id,
            body.assistant_id,
            on_disconnect=disconnect,
            metadata=body.metadata or {},
            kwargs={"input": body.input, "config": body.config},
            multitask_strategy=body.multitask_strategy,
            model_name=model_name,
        )
```

And then remove the duplicate `context` / `root_run_id` / `revision_id` extraction from the checkpoint_ns block (lines 373-374), leaving only:

```python
    # Revision runtime compatibility (feature-flagged)
    if _revision_runtime_enabled() and isinstance(root_run_id, str) and root_run_id and isinstance(revision_id, str) and revision_id:
        config.setdefault("configurable", {}).setdefault(
            "checkpoint_ns",
            build_checkpoint_namespace(root_run_id, revision_id),
        )
```

- [ ] **Step 2: Verify no existing tests break**

Run: `cd backend && make test`

Expected: All existing tests pass (no new failures introduced by moving the extraction).

- [ ] **Step 3: Commit**

```bash
cd backend
git add app/gateway/services.py
git commit -m "feat: store revision_id in run metadata for cancel linkage

Move revision coordinate extraction before create_or_reject() so
revision_id and root_run_id are stored in RunRecord.metadata. This
enables the cancel callback to look up the associated revision and
transition its status.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Cancel → Revision Linkage

**Files:**
- Modify: `backend/packages/harness/deerflow/runtime/runs/manager.py:126-139,487-524`
- Modify: `backend/packages/harness/deerflow/runtime/runs/dispatcher.py:58-83,119-122`
- Modify: `backend/app/gateway/deps.py:176-200`
- Modify: `backend/tests/test_run_queue.py`
- Modify: `backend/tests/test_run_queue_http.py`
- Modify: `backend/tests/test_worker_langfuse_metadata.py`
- Modify: `backend/tests/test_gateway_run_recovery.py`
- Modify: `backend/tests/test_revision_state_machine.py`

- [ ] **Step 1: Add `_on_run_cancelled` callback to RunManager**

Follow the exact same pattern as `_run_terminal_handler` (lines 126, 128-133, 135-139).

In `manager.py`, add the field after line 126:

```python
        self._run_terminal_handler: Callable[[str, str], Awaitable[None]] | None = None
        self._on_run_cancelled: Callable[[str, str], Awaitable[None]] | None = None
```

Add setter after `set_run_terminal_handler` (after line 133):

```python
    def set_on_run_cancelled(
        self,
        handler: Callable[[str, str], Awaitable[None]] | None,
    ) -> None:
        """Register a callback invoked after a run is cancelled."""
        self._on_run_cancelled = handler
```

Add the notify method after `notify_run_terminal` (after line 139):

```python
    async def _notify_run_cancelled(self, thread_id: str, run_id: str) -> None:
        """Invoke the registered cancel handler, if any."""
        handler = self._on_run_cancelled
        if handler is not None:
            await handler(thread_id, run_id)
```

- [ ] **Step 2: Call the callback in RunManager.cancel()**

In `cancel()` (lines 487-524), add the callback invocation after the successful cancel at line 523. The updated `cancel()`:

```python
    async def cancel(self, run_id: str, *, action: str = "interrupt") -> bool:
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return False
            if record.status == RunStatus.interrupted:
                return True
            if record.status == RunStatus.queued:
                if self._queue is not None:
                    await self._queue.remove(record.thread_id, run_id)
                record.status = RunStatus.interrupted
                record.updated_at = _now_iso()
                await self._persist_status(record, RunStatus.interrupted)
                logger.info("Run %s cancelled while queued", run_id)
                await self._notify_run_cancelled(record.thread_id, run_id)
                return True
            if record.status not in (RunStatus.pending, RunStatus.running):
                return False
            record.abort_action = action
            record.abort_event.set()
            if record.task is not None and not record.task.done():
                record.task.cancel()
            record.status = RunStatus.interrupted
            record.updated_at = _now_iso()
        await self._persist_status(record, RunStatus.interrupted)
        logger.info("Run %s cancelled (action=%s)", run_id, action)
        await self._notify_run_cancelled(record.thread_id, run_id)
        return True
```

- [ ] **Step 3: Add cancel callback wiring to RunDispatcher**

In `dispatcher.py`, add a handler slot and wire it in `start()`.

Add field after `_started` (line 70):

```python
    _started: bool = field(default=False, init=False)
    _on_run_cancelled_external: Callable[[str, str], Awaitable[None]] | None = field(
        default=None, init=False
    )
```

Add setter method:

```python
    def set_on_run_cancelled(
        self,
        handler: Callable[[str, str], Awaitable[None]] | None,
    ) -> None:
        """Register a handler invoked when a run is cancelled.
        
        The handler receives (thread_id, run_id) and is called after the
        run transitions to interrupted state.
        """
        self._on_run_cancelled_external = handler
```

Add internal bridge method:

```python
    async def _on_run_cancelled_bridge(self, thread_id: str, run_id: str) -> None:
        """Bridge: forward RunManager cancel events to the external handler."""
        if self._on_run_cancelled_external is not None:
            await self._on_run_cancelled_external(thread_id, run_id)
```

Update `start()` to register the bridge:

```python
    async def start(self) -> None:
        """Register the terminal handler so completed runs drain the queue."""
        self.run_manager.set_run_terminal_handler(self.on_run_finished)
        self.run_manager.set_on_run_cancelled(self._on_run_cancelled_bridge)
        self._started = True
```

Update `stop()` to clear the handler:

```python
    async def stop(self) -> None:
        """Clear the terminal handler on shutdown."""
        self.run_manager.set_run_terminal_handler(None)
        self.run_manager.set_on_run_cancelled(None)
        self._started = False
```

- [ ] **Step 4: Wire cancel → revision transition in deps.py**

In `deps.py` `langgraph_runtime()`, after the dispatcher is created and started (lines 176-183), add the cancel handler:

```python
        app.state.run_dispatcher = RunDispatcher(
            workers=4,
            queue=run_queue,
            run_manager=app.state.run_manager,
            launch=services.launch_run_task,
        )
        await app.state.run_dispatcher.start()

        # Wire run cancellation → revision state transition for the
        # revision runtime feature flag.
        revision_registry = getattr(app.state, "revision_registry", None)
        if revision_registry is not None:

            async def _on_run_cancelled(thread_id: str, run_id: str) -> None:
                record = await app.state.run_manager.get(run_id)
                if record is None:
                    return
                revision_id = (record.metadata or {}).get("revision_id")
                if not revision_id:
                    return
                try:
                    await revision_registry.transition_revision(
                        revision_id, "cancelled"
                    )
                except ValueError:
                    # Revision may already be in a terminal state or not
                    # found — log and move on.
                    logger.warning(
                        "Failed to transition revision %s to cancelled "
                        "(run %s cancelled on thread %s)",
                        revision_id,
                        run_id,
                        thread_id,
                        exc_info=True,
                    )

            app.state.run_dispatcher.set_on_run_cancelled(_on_run_cancelled)
```

- [ ] **Step 5: Add cancel transition tests to state machine test file**

```python
@pytest.mark.parametrize(
    "current",
    [
        RevisionStatus.running,
        RevisionStatus.paused,
        RevisionStatus.awaiting_action,
    ],
)
def test_non_terminal_to_cancelled_allowed(current: RevisionStatus):
    """User-initiated cancel should be allowed from running/paused/awaiting_action."""
    assert_transition_allowed(current, RevisionStatus.cancelled)


def test_pending_to_cancelled_allowed():
    """Cancel before first run starts should be allowed."""
    assert_transition_allowed(RevisionStatus.pending, RevisionStatus.cancelled)
```

- [ ] **Step 6: Update FakeRunManagers in test files to have the new method**

In each of these files, add `set_on_run_cancelled` method to the `_FakeRunManager`:

**`tests/test_run_queue.py`:**

```python
    def set_on_run_cancelled(self, *_args, **_kwargs) -> None:
        return None
```

**`tests/test_run_queue_http.py`:**

```python
    def set_on_run_cancelled(self, *_args, **_kwargs) -> None:
        return None
```

**`tests/test_worker_langfuse_metadata.py`:**

```python
    def set_on_run_cancelled(self, *_args, **_kwargs) -> None:
        return None
```

**`tests/test_gateway_run_recovery.py`:**

```python
    def set_on_run_cancelled(self, *_args, **_kwargs) -> None:
        return None
```

- [ ] **Step 7: Run full backend test suite**

Run: `cd backend && make test`

Expected: All tests pass.

- [ ] **Step 8: Run lint**

Run: `cd backend && make lint`

Expected: No lint errors.

- [ ] **Step 9: Commit**

```bash
cd backend
git add \
  packages/harness/deerflow/runtime/runs/manager.py \
  packages/harness/deerflow/runtime/runs/dispatcher.py \
  app/gateway/deps.py \
  tests/test_run_queue.py \
  tests/test_run_queue_http.py \
  tests/test_worker_langfuse_metadata.py \
  tests/test_gateway_run_recovery.py \
  tests/test_revision_state_machine.py
git commit -m "feat: cancel run transitions linked revision to cancelled

Add on_run_cancelled callback chain: RunManager.cancel() notifies
RunDispatcher, which delegates to a gateway-injected handler that
looks up the revision_id from run metadata and transitions the
revision to cancelled status.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Full Verification

**Files:** (none — verification only)

- [ ] **Step 1: Run backend full verification**

```bash
cd backend && make lint && make test
```

Expected: All lint checks pass, all tests pass.

- [ ] **Step 2: Run frontend verification**

```bash
cd frontend && pnpm lint && pnpm typecheck && pnpm build
```

Expected: All lint checks pass, typecheck passes, build succeeds.

- [ ] **Step 3: Final review of diff**

```bash
git diff develop/v0.01-20260605 --stat
git diff develop/v0.01-20260605
```

Review the complete diff for correctness and completeness.

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Covered By |
|---|---|
| 2.1 Checkpoint Inheritance | Task 1 |
| 2.2 Cancel → Revision Linkage | Tasks 2 + 3 |
| 2.3 Resume (unchanged) | N/A (no changes needed) |
| 3. 情况4 实现路径 | Covered by Task 1 (inject with inheritance) |
| 4. 情况5 Talker 层 | N/A (no runtime changes) |
| 5. Backend file checklist | All files covered in Tasks 1-3 |
| 6. Frontend file checklist | Deferred (cosmetic — timeline chain display) |
| 7. Feature Flag | No changes needed (existing flag guards) |
| 8. Risk: fork race condition | Mitigated by existing superseded skip logic |
| 8. Risk: cancel → revision mapping | Covered by Task 2 (revision_id in metadata) |

### 2. Placeholder Scan

No placeholders found. All steps have concrete code, exact file paths, and expected outputs.

### 3. Type Consistency

- `Callable[[str, str], Awaitable[None]]` — consistent across `RunManager`, `RunDispatcher`, and `deps.py`
- `revision_id` / `root_run_id` keys — consistent between `services.py` (write) and `deps.py` (read)
- `set_on_run_cancelled` — same signature on both `RunManager` and `RunDispatcher`
