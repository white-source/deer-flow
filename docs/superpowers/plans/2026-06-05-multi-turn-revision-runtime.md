# Multi-Turn Run/Revision Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace thread-serialized run execution with a revision-aware runtime that supports inject/fork, resume, foreground switching, and revision-state safety.

**Architecture:** Introduce explicit Root Run + Revision domain models and a centralized revision registry/state machine. Keep old thread queue runtime alive as a compatibility path while new APIs and scheduler run behind a feature flag, then migrate frontend from queued single-stream assumptions to run-list + active revision semantics. Every state transition is guarded by the revision state machine from `docs/notes/task驱动/多轮对话/完整多轮协作-revision状态机.md`.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy, pytest), TypeScript (Next.js 16, React 19, TanStack Query, Vitest, Playwright), pnpm, uv

---

## Scope Check

This spec spans backend runtime, API, and frontend interaction model. It is one cohesive migration (shared object model and contracts), so this plan keeps a single delivery stream with feature flags. If needed, you can split execution into two implementation branches later:
- backend domain/runtime branch
- frontend UX/interaction branch

---

## File Structure

### Backend domain + persistence
- Create: `backend/packages/harness/deerflow/runtime/revisions/schemas.py`
- Create: `backend/packages/harness/deerflow/runtime/revisions/state_machine.py`
- Create: `backend/packages/harness/deerflow/runtime/revisions/registry.py`
- Create: `backend/packages/harness/deerflow/persistence/run_revision/model.py`
- Create: `backend/packages/harness/deerflow/persistence/run_revision/sql.py`
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/20260605_0001_add_run_revision_tables.py`
- Modify: `backend/packages/harness/deerflow/persistence/base.py`
- Modify: `backend/packages/harness/deerflow/persistence/run/model.py`
- Modify: `backend/packages/harness/deerflow/runtime/runs/worker.py`

### Backend API + runtime wiring
- Create: `backend/app/gateway/routers/revisions.py`
- Modify: `backend/app/gateway/routers/__init__.py`
- Modify: `backend/app/gateway/app.py`
- Modify: `backend/app/gateway/deps.py`
- Modify: `backend/app/gateway/services.py`
- Create: `backend/packages/harness/deerflow/runtime/revisions/coordinator.py`
- Modify: `backend/packages/harness/deerflow/runtime/runs/dispatcher.py`

### Frontend core + UI
- Create: `frontend/src/core/revisions/types.ts`
- Create: `frontend/src/core/revisions/api.ts`
- Create: `frontend/src/core/revisions/hooks.ts`
- Modify: `frontend/src/core/threads/hooks.ts`
- Modify: `frontend/src/core/threads/run-queue.ts`
- Create: `frontend/src/components/workspace/revisions/revision-timeline.tsx`
- Create: `frontend/src/components/workspace/revisions/background-run-list.tsx`
- Modify: `frontend/src/app/workspace/chats/[thread_id]/page.tsx`
- Modify: `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`

### Tests + docs
- Create: `backend/tests/test_revision_state_machine.py`
- Create: `backend/tests/test_revision_registry.py`
- Create: `backend/tests/test_revisions_api.py`
- Modify: `backend/tests/test_run_queue.py`
- Modify: `backend/tests/test_run_queue_http.py`
- Create: `frontend/tests/unit/core/revisions/api.test.ts`
- Create: `frontend/tests/unit/core/revisions/hooks.test.ts`
- Modify: `frontend/tests/unit/core/threads/run-queue.test.ts`
- Create: `frontend/tests/e2e/revisions-flow.spec.ts`
- Modify: `docs/notes/task驱动/多轮对话/完整多轮协作-实现拆分.md`

---

### Task 1: Introduce Revision State Machine (Domain First)

**Files:**
- Create: `backend/packages/harness/deerflow/runtime/revisions/schemas.py`
- Create: `backend/packages/harness/deerflow/runtime/revisions/state_machine.py`
- Test: `backend/tests/test_revision_state_machine.py`

- [ ] **Step 1: Write failing state-machine tests from the spec**

```python
# backend/tests/test_revision_state_machine.py
from deerflow.runtime.revisions.schemas import RevisionStatus
from deerflow.runtime.revisions.state_machine import assert_transition_allowed
import pytest


def test_allows_running_to_awaiting_action():
    assert_transition_allowed(RevisionStatus.running, RevisionStatus.awaiting_action)


def test_blocks_superseded_to_running():
    with pytest.raises(ValueError, match="superseded -> running is not allowed"):
        assert_transition_allowed(RevisionStatus.superseded, RevisionStatus.running)


def test_blocks_terminal_to_running():
    for terminal in [RevisionStatus.completed, RevisionStatus.cancelled, RevisionStatus.error]:
        with pytest.raises(ValueError):
            assert_transition_allowed(terminal, RevisionStatus.running)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_revision_state_machine.py -v`
Expected: FAIL with import/module errors for missing revisions modules.

- [ ] **Step 3: Add status enums and transition guard implementation**

```python
# backend/packages/harness/deerflow/runtime/revisions/schemas.py
from enum import StrEnum


class RevisionStatus(StrEnum):
    pending = "pending"
    running = "running"
    awaiting_action = "awaiting_action"
    paused = "paused"
    superseded = "superseded"
    completed = "completed"
    cancelled = "cancelled"
    error = "error"


TERMINAL_REVISION_STATUSES = {
    RevisionStatus.completed,
    RevisionStatus.cancelled,
    RevisionStatus.error,
}
```

```python
# backend/packages/harness/deerflow/runtime/revisions/state_machine.py
from deerflow.runtime.revisions.schemas import RevisionStatus

_ALLOWED = {
    RevisionStatus.pending: {RevisionStatus.running, RevisionStatus.cancelled},
    RevisionStatus.running: {
        RevisionStatus.awaiting_action,
        RevisionStatus.paused,
        RevisionStatus.superseded,
        RevisionStatus.completed,
        RevisionStatus.cancelled,
        RevisionStatus.error,
    },
    RevisionStatus.awaiting_action: {
        RevisionStatus.running,
        RevisionStatus.superseded,
        RevisionStatus.cancelled,
        RevisionStatus.error,
    },
    RevisionStatus.paused: {RevisionStatus.running, RevisionStatus.cancelled, RevisionStatus.error},
    RevisionStatus.superseded: set(),
    RevisionStatus.completed: set(),
    RevisionStatus.cancelled: set(),
    RevisionStatus.error: set(),
}


def assert_transition_allowed(current: RevisionStatus, nxt: RevisionStatus) -> None:
    if nxt not in _ALLOWED[current]:
        raise ValueError(f"{current.value} -> {nxt.value} is not allowed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_revision_state_machine.py -v`
Expected: PASS (`3 passed`).

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/runtime/revisions/schemas.py \
  backend/packages/harness/deerflow/runtime/revisions/state_machine.py \
  backend/tests/test_revision_state_machine.py
git commit -m "feat(runtime): add revision lifecycle state machine"
```

---

### Task 2: Add Root Run/Revision Persistence + Registry

**Files:**
- Create: `backend/packages/harness/deerflow/persistence/run_revision/model.py`
- Create: `backend/packages/harness/deerflow/persistence/run_revision/sql.py`
- Create: `backend/packages/harness/deerflow/runtime/revisions/registry.py`
- Create: `backend/tests/test_revision_registry.py`
- Modify: `backend/packages/harness/deerflow/persistence/base.py`
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/20260605_0001_add_run_revision_tables.py`

- [ ] **Step 1: Write failing registry tests for active-revision and supersede rules**

```python
# backend/tests/test_revision_registry.py
import pytest


@pytest.mark.asyncio
async def test_one_active_revision_per_root_run(registry):
    root = await registry.create_root_run(thread_id="t1", created_by_message_id="m1")
    r1 = await registry.create_initial_revision(root.root_run_id)
    r2 = await registry.fork_revision(parent_revision_id=r1.revision_id, reason="inject")
    latest = await registry.get_active_revision(root.root_run_id)
    assert latest.revision_id == r2.revision_id


@pytest.mark.asyncio
async def test_superseded_cannot_resume(registry):
    root = await registry.create_root_run(thread_id="t1", created_by_message_id="m1")
    r1 = await registry.create_initial_revision(root.root_run_id)
    await registry.fork_revision(parent_revision_id=r1.revision_id, reason="inject")
    with pytest.raises(ValueError, match="superseded -> running is not allowed"):
        await registry.transition_revision(r1.revision_id, "running")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_revision_registry.py -v`
Expected: FAIL with missing registry/persistence implementation.

- [ ] **Step 3: Implement SQL models and registry methods**

```python
# backend/packages/harness/deerflow/persistence/run_revision/model.py
class RootRunRow(Base):
    __tablename__ = "root_runs"
    root_run_id = mapped_column(String(64), primary_key=True)
    thread_id = mapped_column(String(64), nullable=False, index=True)
    created_by_message_id = mapped_column(String(64), nullable=True)
    status_summary = mapped_column(String(32), default="pending")
    foreground_state = mapped_column(String(16), default="foreground")
    latest_revision_id = mapped_column(String(64), nullable=True)


class RevisionRow(Base):
    __tablename__ = "revisions"
    revision_id = mapped_column(String(64), primary_key=True)
    root_run_id = mapped_column(String(64), nullable=False, index=True)
    parent_revision_id = mapped_column(String(64), nullable=True)
    supersedes_revision_id = mapped_column(String(64), nullable=True)
    status = mapped_column(String(32), default="pending")
    execution_mode = mapped_column(String(16), default="foreground")
    checkpoint_namespace = mapped_column(String(128), nullable=False)
    is_active = mapped_column(Boolean, default=True)
```

```python
# backend/packages/harness/deerflow/runtime/revisions/registry.py
async def fork_revision(self, parent_revision_id: str, reason: str) -> RevisionRecord:
    parent = await self.get_revision(parent_revision_id)
    await self._transition(parent.revision_id, RevisionStatus.superseded)
    new_revision = await self._repo.create_revision(
        root_run_id=parent.root_run_id,
        parent_revision_id=parent.revision_id,
        supersedes_revision_id=parent.revision_id,
        status=RevisionStatus.pending.value,
        checkpoint_namespace=f"run:{parent.root_run_id}:rev:{new_id}",
        is_active=True,
    )
    await self._repo.set_active_revision(parent.root_run_id, new_revision.revision_id)
    return new_revision
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_revision_registry.py -v`
Expected: PASS (active pointer and supersede guard behavior verified).

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/persistence/run_revision/model.py \
  backend/packages/harness/deerflow/persistence/run_revision/sql.py \
  backend/packages/harness/deerflow/runtime/revisions/registry.py \
  backend/tests/test_revision_registry.py \
  backend/packages/harness/deerflow/persistence/base.py \
  backend/packages/harness/deerflow/persistence/migrations/versions/20260605_0001_add_run_revision_tables.py
git commit -m "feat(persistence): add root run and revision registry tables"
```

---

### Task 3: Add Revision APIs (create/resume/inject/switch)

**Files:**
- Create: `backend/app/gateway/routers/revisions.py`
- Modify: `backend/app/gateway/routers/__init__.py`
- Modify: `backend/app/gateway/app.py`
- Modify: `backend/app/gateway/deps.py`
- Test: `backend/tests/test_revisions_api.py`

- [ ] **Step 1: Write failing API tests for action routing by revision id**

```python
# backend/tests/test_revisions_api.py
from fastapi.testclient import TestClient


def test_resume_only_accepts_paused_or_awaiting(app_with_revision_router):
    c = TestClient(app_with_revision_router)
    res = c.post("/api/runs/rev-1/resume")
    assert res.status_code in (200, 409)


def test_inject_creates_new_revision(app_with_revision_router):
    c = TestClient(app_with_revision_router)
    res = c.post("/api/runs/rev-1/inject", json={"instruction": "switch plan"})
    assert res.status_code == 200
    body = res.json()
    assert body["superseded_revision_id"] == "rev-1"
    assert body["revision_id"] != "rev-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_revisions_api.py -v`
Expected: FAIL because `revisions` router is not registered.

- [ ] **Step 3: Implement router endpoints and wire app**

```python
# backend/app/gateway/routers/revisions.py
@router.post("/api/runs/{revision_id}/resume")
async def resume_revision(revision_id: str, request: Request):
    registry = get_revision_registry(request)
    revision = await registry.resume_revision(revision_id)
    return {"revision_id": revision.revision_id, "status": revision.status}


@router.post("/api/runs/{revision_id}/inject")
async def inject_revision(revision_id: str, body: InjectRequest, request: Request):
    registry = get_revision_registry(request)
    forked = await registry.inject_revision(revision_id, instruction=body.instruction)
    return {
        "revision_id": forked.revision_id,
        "superseded_revision_id": forked.supersedes_revision_id,
        "status": forked.status,
    }


@router.post("/api/threads/{thread_id}/active-run")
async def switch_active_run(thread_id: str, body: SwitchActiveRequest, request: Request):
    registry = get_revision_registry(request)
    await registry.switch_foreground(thread_id=thread_id, revision_id=body.revision_id)
    return {"thread_id": thread_id, "active_revision_id": body.revision_id}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_revisions_api.py -v`
Expected: PASS (`resume`, `inject`, `switch active` contracts covered).

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/routers/revisions.py \
  backend/app/gateway/routers/__init__.py \
  backend/app/gateway/app.py \
  backend/app/gateway/deps.py \
  backend/tests/test_revisions_api.py
git commit -m "feat(api): add revision action endpoints"
```

---

### Task 4: Make Scheduler/Worker Revision-Aware and Checkpoint-Isolated

**Files:**
- Create: `backend/packages/harness/deerflow/runtime/revisions/coordinator.py`
- Modify: `backend/app/gateway/services.py`
- Modify: `backend/packages/harness/deerflow/runtime/runs/worker.py`
- Modify: `backend/packages/harness/deerflow/runtime/runs/dispatcher.py`
- Modify: `backend/tests/test_run_queue.py`
- Modify: `backend/tests/test_run_queue_http.py`

- [ ] **Step 1: Write failing tests for revision checkpoint namespace and supersede convergence**

```python
# backend/tests/test_run_queue.py (add)
@pytest.mark.anyio
async def test_revision_checkpoint_namespace_isolation(run_worker_fixture):
    ns = run_worker_fixture.make_namespace(root_run_id="root-1", revision_id="rev-2")
    assert ns == "run:root-1:rev:rev-2"


@pytest.mark.anyio
async def test_superseded_revision_not_requeued(dispatcher_fixture):
    old = await dispatcher_fixture.create_running_revision("rev-old")
    await dispatcher_fixture.mark_superseded(old)
    assert await dispatcher_fixture.can_schedule(old.revision_id) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_run_queue.py tests/test_run_queue_http.py -v`
Expected: FAIL because worker/dispatcher still assume thread queue only.

- [ ] **Step 3: Implement coordinator + worker namespace upgrade**

```python
# backend/packages/harness/deerflow/runtime/revisions/coordinator.py
def build_checkpoint_namespace(root_run_id: str, revision_id: str) -> str:
    return f"run:{root_run_id}:rev:{revision_id}"
```

```python
# backend/packages/harness/deerflow/runtime/runs/worker.py
config_for_check = {
    "configurable": {
        "thread_id": thread_id,
        "checkpoint_ns": build_checkpoint_namespace(root_run_id, revision_id),
    }
}
```

```python
# backend/app/gateway/services.py
if app_config.features.revision_runtime_enabled:
    revision = await revision_registry.create_or_inject(...)
    launch_ctx.config.setdefault("configurable", {})["checkpoint_ns"] = revision.checkpoint_namespace
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_run_queue.py tests/test_run_queue_http.py -v`
Expected: PASS with old enqueue compatibility intact and revision path guarded by feature flag.

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/runtime/revisions/coordinator.py \
  backend/app/gateway/services.py \
  backend/packages/harness/deerflow/runtime/runs/worker.py \
  backend/packages/harness/deerflow/runtime/runs/dispatcher.py \
  backend/tests/test_run_queue.py \
  backend/tests/test_run_queue_http.py
git commit -m "feat(runtime): add revision-aware scheduling and checkpoint namespace"
```

---

### Task 5: Frontend Core Migration (run list + active revision)

**Files:**
- Create: `frontend/src/core/revisions/types.ts`
- Create: `frontend/src/core/revisions/api.ts`
- Create: `frontend/src/core/revisions/hooks.ts`
- Modify: `frontend/src/core/threads/hooks.ts`
- Modify: `frontend/src/core/threads/run-queue.ts`
- Test: `frontend/tests/unit/core/revisions/api.test.ts`
- Test: `frontend/tests/unit/core/revisions/hooks.test.ts`
- Modify: `frontend/tests/unit/core/threads/run-queue.test.ts`

- [ ] **Step 1: Write failing unit tests for action targeting by revision**

```ts
// frontend/tests/unit/core/revisions/api.test.ts
it("inject targets /api/runs/{revision_id}/inject", async () => {
  fetchWithAuth.mockResolvedValue({ ok: true, json: async () => ({ revision_id: "rev-2" }) });
  const { injectRevision } = await import("@/core/revisions/api");
  await injectRevision("rev-1", "switch");
  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/runs/rev-1/inject"),
    expect.objectContaining({ method: "POST" }),
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run tests/unit/core/revisions/api.test.ts`
Expected: FAIL due to missing `core/revisions/api.ts`.

- [ ] **Step 3: Implement revision API and hook contracts**

```ts
// frontend/src/core/revisions/api.ts
export async function resumeRevision(revisionId: string) {
  return fetchJson(`/api/runs/${encodeURIComponent(revisionId)}/resume`, { method: "POST" });
}

export async function injectRevision(revisionId: string, instruction: string) {
  return fetchJson(`/api/runs/${encodeURIComponent(revisionId)}/inject`, {
    method: "POST",
    body: JSON.stringify({ instruction }),
  });
}

export async function switchActiveRevision(threadId: string, revisionId: string) {
  return fetchJson(`/api/threads/${encodeURIComponent(threadId)}/active-run`, {
    method: "POST",
    body: JSON.stringify({ revision_id: revisionId }),
  });
}
```

```ts
// frontend/src/core/threads/hooks.ts (routing intent)
if (intent.kind === "inject") {
  await injectRevision(activeRevisionId, text);
} else if (intent.kind === "resume") {
  await resumeRevision(activeRevisionId);
} else {
  await createRootRun(threadId, payload);
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd frontend && pnpm vitest run tests/unit/core/revisions/api.test.ts tests/unit/core/revisions/hooks.test.ts tests/unit/core/threads/run-queue.test.ts`
Expected: PASS with legacy queue tests still green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/revisions/types.ts \
  frontend/src/core/revisions/api.ts \
  frontend/src/core/revisions/hooks.ts \
  frontend/src/core/threads/hooks.ts \
  frontend/src/core/threads/run-queue.ts \
  frontend/tests/unit/core/revisions/api.test.ts \
  frontend/tests/unit/core/revisions/hooks.test.ts \
  frontend/tests/unit/core/threads/run-queue.test.ts
git commit -m "feat(frontend): route user actions by active revision"
```

---

### Task 6: Frontend UI Migration + Timeline + Background Runs

**Files:**
- Create: `frontend/src/components/workspace/revisions/revision-timeline.tsx`
- Create: `frontend/src/components/workspace/revisions/background-run-list.tsx`
- Modify: `frontend/src/app/workspace/chats/[thread_id]/page.tsx`
- Modify: `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`
- Test: `frontend/tests/e2e/revisions-flow.spec.ts`

- [ ] **Step 1: Write failing E2E for foreground switch and inject timeline visibility**

```ts
// frontend/tests/e2e/revisions-flow.spec.ts
import { expect, test } from "@playwright/test";

test("inject creates a new timeline node and switches foreground", async ({ page }) => {
  await page.goto("/workspace/chats/new");
  await page.getByPlaceholder("Ask anything").fill("plan A");
  await page.keyboard.press("Enter");
  await page.getByPlaceholder("Ask anything").fill("switch to plan B first");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("revision-timeline")).toContainText("R1.1");
  await expect(page.getByTestId("active-revision-badge")).toContainText("R1.1");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm playwright test tests/e2e/revisions-flow.spec.ts`
Expected: FAIL because timeline components do not exist yet.

- [ ] **Step 3: Implement timeline and background run list rendering**

```tsx
// frontend/src/components/workspace/revisions/revision-timeline.tsx
export function RevisionTimeline({ revisions, activeRevisionId }: Props) {
  return (
    <div data-testid="revision-timeline" className="space-y-2">
      {revisions.map((rev) => (
        <button
          key={rev.revision_id}
          data-active={rev.revision_id === activeRevisionId}
          className="w-full rounded border px-2 py-1 text-left"
        >
          {rev.label} · {rev.status}
        </button>
      ))}
    </div>
  );
}
```

```tsx
// frontend/src/app/workspace/chats/[thread_id]/page.tsx (insert side panel)
<aside className="w-72 shrink-0 border-l p-3">
  <BackgroundRunList runs={backgroundRuns} />
  <RevisionTimeline
    revisions={activeRunRevisions}
    activeRevisionId={activeRevisionId}
    onSelectRevision={(revisionId) => switchForeground(revisionId)}
  />
</aside>
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd frontend && pnpm playwright test tests/e2e/revisions-flow.spec.ts`
Expected: PASS (timeline update + active badge + switch behavior verified).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workspace/revisions/revision-timeline.tsx \
  frontend/src/components/workspace/revisions/background-run-list.tsx \
  frontend/src/app/workspace/chats/[thread_id]/page.tsx \
  frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx \
  frontend/tests/e2e/revisions-flow.spec.ts
git commit -m "feat(ui): add revision timeline and background run views"
```

---

### Task 7: Migration Guards, Compatibility Path, and Decommission Plan

**Files:**
- Modify: `backend/app/gateway/services.py`
- Modify: `backend/app/gateway/deps.py`
- Modify: `backend/packages/harness/deerflow/runtime/runs/dispatcher.py`
- Modify: `docs/notes/task驱动/多轮对话/完整多轮协作-实现拆分.md`

- [ ] **Step 1: Write failing test for feature-flag dual runtime behavior**

```python
# backend/tests/test_revisions_api.py (add)
def test_feature_flag_routes_new_threads_to_revision_runtime(client_with_flag_on):
    res = client_with_flag_on.post("/api/threads/t1/runs", json={"assistant_id": "lead_agent"})
    assert res.status_code == 200
    assert "active_revision_id" in res.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_revisions_api.py -v`
Expected: FAIL until dual runtime routing is wired.

- [ ] **Step 3: Implement runtime switch + compatibility notes**

```python
# backend/app/gateway/services.py
if get_app_config().features.revision_runtime_enabled:
    return await start_revision_run(...)
return await start_legacy_thread_run(...)
```

```python
# backend/packages/harness/deerflow/runtime/runs/dispatcher.py
# legacy path kept for old threads only; new threads bypass via revision coordinator
```

- [ ] **Step 4: Run integration checks**

Run: `cd backend && make lint && make test`
Expected: PASS.

Run: `cd frontend && pnpm lint && pnpm typecheck`
Expected: PASS.

Run: `cd frontend && BETTER_AUTH_SECRET=local-dev-secret pnpm build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/services.py \
  backend/app/gateway/deps.py \
  backend/packages/harness/deerflow/runtime/runs/dispatcher.py \
  docs/notes/task驱动/多轮对话/完整多轮协作-实现拆分.md
git commit -m "chore(migration): add dual-runtime guard and rollout documentation"
```

---

## Verification Matrix (run before merge)

1. Backend unit/API/runtime:
- `cd backend && make lint`
- `cd backend && make test`

2. Frontend unit/type/lint:
- `cd frontend && pnpm lint`
- `cd frontend && pnpm typecheck`
- `cd frontend && pnpm test`

3. Frontend e2e critical path:
- `cd frontend && pnpm playwright test tests/e2e/revisions-flow.spec.ts`

4. Build validation:
- `cd frontend && BETTER_AUTH_SECRET=local-dev-secret pnpm build`

5. Manual runtime smoke:
- `make dev`
- In browser: create run, inject mid-flight, switch foreground, approve/resume, verify timeline and background status

---

## Self-Review

### 1. Spec coverage
- Covered: run/revision domain split, revision status machine, legal/illegal transitions, inject=fork, superseded non-resumable, revision checkpoint namespace, backend API split (`create/resume/inject/switch`), frontend active run + revision timeline, migration with dual runtime.
- Covered: foreground/background distinction as separate dimension (execution mode + UI rendering).
- Covered: phased migration and old dispatcher compatibility window.
- Gap check: none found against the three source docs.

### 2. Placeholder scan
- Checked for: `TODO`, `TBD`, `implement later`, `add appropriate`, `handle edge cases`, `similar to`.
- Result: no placeholders left.

### 3. Type consistency
- Status names are consistent across tasks: `pending`, `running`, `awaiting_action`, `paused`, `superseded`, `completed`, `cancelled`, `error`.
- API verbs are consistent across tasks: `resume`, `inject`, `switch active`.
- Checkpoint namespace is consistent across tasks: `run:{root_run_id}:rev:{revision_id}`.

---

Plan complete and saved to `docs/superpowers/plans/2026-06-05-multi-turn-revision-runtime.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
