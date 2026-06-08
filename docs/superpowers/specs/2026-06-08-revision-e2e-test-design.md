# DeerFlow Revision E2E 测试设计

> 2026-06-08 | 覆盖 5 个产品场景的分层测试方案

## 1. 测试目标

覆盖 5 个产品场景（情况2-6），验证 Talker → Runtime → UI 的完整行为：

| 场景 | 核心行为 | 测试层级 |
|---|---|---|
| 情况2 修改参数 | inject → fork → checkpoint 继承 | Backend E2E + Frontend E2E |
| 情况3 停止任务 | cancel → revision → cancelled | Backend E2E + Frontend E2E |
| 情况4 垫词后打断 | cancel + inject → 继承 checkpoint | Backend E2E + Frontend E2E |
| 情况5 合并任务 | Talker 合并 prompt → inject | 手工测试文档 |
| 情况6 快速响应 | Talker 判断无垫词 → 直接返回 | 手工测试文档 |

## 2. 测试架构

```
┌─────────────────────────────────────────────┐
│  Frontend E2E (Playwright)                    │
│  浏览器驱动，mock intent，测 UI 完整链路        │
│  3 个用例，覆盖情况 2/3/4                      │
├─────────────────────────────────────────────┤
│  Backend E2E (pytest + HTTPX)                 │
│  直接调 Gateway API，测 Runtime 原语正确性      │
│  8 个用例，覆盖情况 2/3/4                      │
├─────────────────────────────────────────────┤
│  手工测试文档                                  │
│  Given-When-Then，记录 Talker 行为预期          │
│  2 个用例，覆盖情况 5/6                        │
└─────────────────────────────────────────────┘
```

### Mock 策略（Frontend E2E）

Talker 的意图识别不经过真实 LLM 调用。通过 `additionalKwargs` 预设 `intent` 和 `activeRevisionId`，直接测试 `resolveRevisionAction()` → API → Runtime → UI 更新 的完整链路。

```typescript
// hooks.ts 已实现的 intent 路由：
// resolveRevisionAction() 从 additionalKwargs 读取 intent
// "inject"  → injectRevision()
// "resume"  → resumeRevision()
// 其他      → 正常流程
```

## 3. Backend E2E 测试设计（pytest + HTTPX）

### 文件结构

```
backend/tests/e2e/
├── conftest.py                        # fixtures
├── test_scenario_2_inject.py          # 情况2
├── test_scenario_3_cancel.py          # 情况3
└── test_scenario_4_interrupt.py       # 情况4
```

### 3.1 conftest.py — 共享 fixtures

```python
import pytest
import httpx
from fastapi import FastAPI
from app.gateway.app import app as gateway_app
from app.gateway.deps import langgraph_runtime
from deerflow.config.app_config import AppConfig

@pytest.fixture
async def app():
    """FastAPI app with revision runtime enabled."""
    # ... setup app with DEER_FLOW_REVISION_RUNTIME_ENABLED=1

@pytest.fixture
async def client(app: FastAPI) -> httpx.AsyncClient:
    """HTTPX async client bound to the test app."""

@pytest.fixture
async def thread_id(client: httpx.AsyncClient) -> str:
    """Create a test thread, return thread_id."""

@pytest.fixture
async def root_run_id(client: httpx.AsyncClient, thread_id: str) -> str:
    """Create a root run for the thread."""

@pytest.fixture
async def initial_revision(client: httpx.AsyncClient, thread_id: str, root_run_id: str) -> dict:
    """Create an initial revision, return revision record."""
```

### 3.2 test_scenario_2_inject.py — 情况2：修改参数

#### 用例 1: `test_inject_creates_child_with_inherited_checkpoint_namespace`

```
Given:  已创建 root_run + initial_revision (revision_id="rev-a")
         父 revision 的 checkpoint_namespace = "run:{root}:rev:rev-a"
When:   POST /api/runs/rev-a/inject  {instruction: "不看上个月，改成本月"}
Then:   HTTP 200
        返回的 superseded_revision_id == "rev-a"
        子 revision checkpoint_namespace == 父 revision checkpoint_namespace
        子 revision parent_revision_id == "rev-a"
        子 revision status == "pending"
```

```python
@pytest.mark.asyncio
async def test_inject_creates_child_with_inherited_checkpoint_namespace(
    client: httpx.AsyncClient, initial_revision: dict
):
    parent_id = initial_revision["revision_id"]

    response = await client.post(
        f"/api/runs/{parent_id}/inject",
        json={"instruction": "不看上个月，改成本月"},
    )
    assert response.status_code == 200
    body = response.json()
    child_id = body["revision_id"]

    # Verify child inherits parent's checkpoint_namespace
    parent_ns = initial_revision["checkpoint_namespace"]
    # Child is now the active revision
    active_response = await client.get(f"/api/threads/{initial_revision['thread_id']}/active-run")
    active = active_response.json()
    assert active["active_revision_id"] == child_id
    assert active["checkpoint_namespace"] == parent_ns
    assert body["superseded_revision_id"] == parent_id
```

#### 用例 2: `test_inject_supersedes_parent_revision`

```
Given:  root_run + initial_revision (status="running", 可被 supersede)
When:   POST /api/runs/{rev}/inject
Then:   父 revision status == "superseded"
        子 revision status == "pending"
        子 revision supersedes_revision_id == 父 revision_id
```

#### 用例 3: `test_superseded_revision_cannot_be_resumed`

```
Given:  revision 已被 fork_revision() supersede
When:   POST /api/runs/{superseded_rev}/resume
Then:   HTTP 409 (Conflict)
        body.detail 包含 "superseded -> running is not allowed"
```

#### 用例 4: `test_inject_on_unknown_revision_returns_404`

```
Given:  不存在的 revision_id = "rev_nonexistent"
When:   POST /api/runs/rev_nonexistent/inject
Then:   HTTP 404 (Not Found)
```

### 3.3 test_scenario_3_cancel.py — 情况3：停止任务

#### 用例 1: `test_cancel_run_transitions_revision_to_cancelled`

```
Given:  thread + root_run + active revision (status="running")
        创建 run 时 metadata 含 {"revision_id": "rev-a", "root_run_id": "root-1"}
        run status = "running"
When:   POST /api/threads/{tid}/runs/{rid}/cancel
Then:   run status == "interrupted"
        revision status == "cancelled"
```

```python
@pytest.mark.asyncio
async def test_cancel_run_transitions_revision_to_cancelled(
    client: httpx.AsyncClient, thread_id: str, initial_revision: dict
):
    # Create a run with revision metadata
    rev_id = initial_revision["revision_id"]
    root_id = initial_revision["root_run_id"]
    run_response = await client.post(
        f"/api/threads/{thread_id}/runs",
        json={
            "assistant_id": "lead-agent",
            "input": {"messages": [{"role": "user", "content": "查话费"}]},
            "context": {"root_run_id": root_id, "revision_id": rev_id},
        },
    )
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    # Cancel the run
    cancel_response = await client.post(
        f"/api/threads/{thread_id}/runs/{run_id}/cancel"
    )
    assert cancel_response.status_code == 200

    # Verify run status
    run_detail = await client.get(f"/api/threads/{thread_id}/runs/{run_id}")
    assert run_detail.json()["status"] == "interrupted"

    # Verify revision transitioned to cancelled
    rev_detail = await client.get(f"/api/runs/{rev_id}/status")
    assert rev_detail.json()["status"] == "cancelled"
```

#### 用例 2: `test_cancel_queued_run_transitions_revision_to_cancelled`

```
Given:  thread 有 1 个 running run，第 2 个 run queued（metadata 含 revision_id）
When:   cancel queued run
Then:   queued run status == "interrupted"
        对应 revision status == "cancelled"
```

#### 用例 3: `test_cancel_idempotent_returns_success`

```
Given:  run 已经是 interrupted 状态
When:   再次 POST /api/threads/{tid}/runs/{rid}/cancel
Then:   HTTP 200（幂等）
        不触发额外的 revision 状态变更
```

#### 用例 4: `test_cancel_run_without_revision_metadata_graceful`

```
Given:  run metadata 不含 revision_id（旧代码创建的 run）
When:   cancel
Then:   run 正常 cancelled
        不报错（handler 中找不到 revision_id 时静默跳过）
```

### 3.4 test_scenario_4_interrupt.py — 情况4：垫词后打断

#### 用例 1: `test_interrupt_cancels_current_and_forks_new`

```
Given:  root_run + revision (status="running") + inflight run
        用户的 checkpoint 中有历史消息 {msg1, tool_call, result}
When:   1. POST /api/threads/{tid}/runs/{rid}/cancel
        2. POST /api/runs/{rev}/inject {instruction: "我没订过啊，重点查凭证"}
Then:   原 revision → superseded
        子 revision → pending
        子 revision checkpoint_ns == 原 revision checkpoint_ns
```

```python
@pytest.mark.asyncio
async def test_interrupt_cancels_current_and_forks_new(
    client: httpx.AsyncClient, thread_id: str, initial_revision: dict
):
    rev_id = initial_revision["revision_id"]
    parent_ns = initial_revision["checkpoint_namespace"]

    # Create and cancel a run
    run_response = await client.post(
        f"/api/threads/{thread_id}/runs",
        json={
            "assistant_id": "lead-agent",
            "input": {"messages": [{"role": "user", "content": "8块是什么费用"}]},
            "context": {
                "root_run_id": initial_revision["root_run_id"],
                "revision_id": rev_id,
            },
        },
    )
    run_id = run_response.json()["run_id"]
    await client.post(f"/api/threads/{thread_id}/runs/{run_id}/cancel")

    # Fork a new revision (simulating Talker injecting "我没订过啊")
    inject_response = await client.post(
        f"/api/runs/{rev_id}/inject",
        json={"instruction": "我没订过啊，重点查凭证"},
    )
    assert inject_response.status_code == 200
    child = inject_response.json()

    # Verify checkpoint inheritance
    assert child["superseded_revision_id"] == rev_id
    assert initial_revision["checkpoint_namespace"] == parent_ns
```

#### 用例 2: `test_interrupt_preserves_checkpoint_context`

```
Given:  revision checkpoint 中有历史消息
When:   cancel + inject fork 新 revision（继承同一 checkpoint_namespace）
Then:   checkpoint 中仍能读到历史消息（通过 aget_tuple 验证）
```

## 4. Frontend E2E 测试设计（Playwright）

### 文件结构

```
frontend/tests/e2e/
├── revisions-scenario-2.spec.ts      # 情况2
├── revisions-scenario-3.spec.ts      # 情况3
└── revisions-scenario-4.spec.ts      # 情况4
```

### 4.1 Mock 策略

Talker 意图识别不经过真实 LLM。在测试中，通过以下方式绕过 LLM：

```typescript
// 方式：page.evaluate 直接调用 hooks 中的 revision actions
// 或者在网络层拦截 /api/langgraph/... 请求并返回预设 intent

// 更简单的做法：在前端 hooks 测试中已经验证了 resolveRevisionAction()
// 路由正确性。E2E 层直接验证 API 调用 → UI 更新链。

// 具体做法：通过 page.evaluate 触发 intent 路由，跳过 LLM 调用
await page.evaluate(({ intent, revisionId }) => {
  // 直接触发 window.__test_triggerRevisionAction(intent, revisionId)
}, { intent: "inject", revisionId: "rev-a" });
```

#### 测试辅助工具

前端需暴露一个测试 helper（仅 dev/test 环境）：

```typescript
// frontend/src/core/revisions/test-helpers.ts
// 挂载到 window.__test_triggerRevisionAction(intent, revisionId)
// 用于 Playwright E2E 测试跳过 LLM 调用
```

### 4.2 revisions-scenario-2.spec.ts — 情况2：修改参数

#### 用例：修改参数后创建新 revision 并展示结果

```
Given:  页面在 /workspace/chats/{thread_id}
        已有 revision timeline 显示 "rev-a" (status: running)
When:   触发 inject intent → 前端调用 POST /api/runs/rev-a/inject
        → 创建新 run（checkpoint_ns 继承）
        → 流式返回结果
Then:   消息列表显示"本月话费"相关结果
        Revision Timeline 中 "rev-b" 为 active
        旧 revision "rev-a" 显示 superseded
```

```typescript
import { test, expect } from "@playwright/test";

test("修改参数后 revision timeline 更新为新 active", async ({ page }) => {
  // Given: 导航到 thread 页面
  await page.goto("/workspace/chats/thread-test-1");

  // 等待 revision timeline 渲染
  await expect(page.locator('[data-testid="revision-timeline"]')).toBeVisible();

  // When: 模拟 Talker 识别 intent="inject"，触发 inject API
  await page.evaluate(() => {
    // 触发 injectAction
    window.__test_triggerRevisionAction("inject", "rev-a");
  });

  // Then: Timeline 更新
  await expect(page.locator('[data-testid="active-revision-badge"]'))
    .toContainText("Active");

  // 旧 revision 不再 active
  const oldRev = page.locator('[data-testid="revision-item-rev-a"]');
  await expect(oldRev).toContainText("superseded");
});
```

### 4.3 revisions-scenario-3.spec.ts — 情况3：停止任务

#### 用例：取消任务后 revision 状态显示 cancelled

```
Given:  页面有 running revision + inflight run
        Chat 区域显示"正在查询"流式状态
When:   触发 cancel intent → 前端调 cancel API
Then:   Revision Timeline 中该 revision 显示 "cancelled"
        确认垫词"好的，还有什么需要帮助的"出现
        输入框恢复可用
```

```typescript
test("取消任务后 revision 显示 cancelled 并展示确认消息", async ({ page }) => {
  await page.goto("/workspace/chats/thread-test-1");

  // When: 模拟 cancel intent
  await page.evaluate(() => {
    window.__test_triggerRevisionAction("cancel", "rev-a");
  });

  // Then: Revision 状态更新
  const revItem = page.locator('[data-testid="revision-item-rev-a"]');
  await expect(revItem).toContainText("cancelled");

  // 确认消息出现
  await expect(page.locator('[data-testid="chat-messages"]'))
    .toContainText("好的");

  // 输入框恢复可用
  await expect(page.locator('[data-testid="chat-input"]')).toBeEnabled();
});
```

### 4.4 revisions-scenario-4.spec.ts — 情况4：垫词后打断

#### 用例：流式输出中途打断后创建新任务并返回调整结果

```
Given:  页面正在流式接收结果（已有部分输出"查到费用类型了：8元是增值业务"）
When:   用户补充"我没订过啊"
        → Talker 识别 intent="inject"
        → 前端调 inject API（cancel 当前 + fork 新 revision）
        → 新 run 返回聚焦"凭证查询"的结果
Then:   Timeline 中显示新 revision 为 active
        消息列表同时显示：旧的部分结果 + 新的调整后结果
        新结果包含"订购凭证""App 页面确认办理"等关键词
```

```typescript
test("流式输出中途注入后返回调整结果", async ({ page }) => {
  await page.goto("/workspace/chats/thread-test-1");

  // Given: 等待流式输出到达部分结果
  await expect(page.locator('[data-testid="chat-messages"]'))
    .toContainText("8元是增值业务");

  // When: 模拟补充信息 → inject intent
  await page.evaluate(() => {
    window.__test_triggerRevisionAction("inject", "rev-a");
  });

  // Then: Timeline 更新为新 revision
  await expect(page.locator('[data-testid="active-revision-badge"]'))
    .toContainText("Active");

  // 调整后的结果出现
  await expect(page.locator('[data-testid="chat-messages"]'))
    .toContainText("订购凭证");
  await expect(page.locator('[data-testid="chat-messages"]'))
    .toContainText("App页面确认办理");
});
```

## 5. 手工测试文档（情况5/6）

### 5.1 情况5：用户连续输入，Talker 合并任务

```
测试编号: MANUAL-001
场景描述: 用户连续输入 3 个相关问题，Talker 合并为 1 个任务一次性查询
前置条件:
  - DEER_FLOW_REVISION_RUNTIME_ENABLED=1
  - Talker 已实现意图合并逻辑
  - 页面在 /workspace/chats/{thread_id}

操作步骤:
  Step 1: 输入 "我这个月话费怎么这么高？"，发送
  Step 2: 等待 Talker 返回垫词
  Step 3: 输入 "还有流量也帮我看一下"，发送
  Step 4: 等待 Talker 处理
  Step 5: 输入 "顺便看看有没有什么乱七八糟的增值业务"，发送

预期结果:
  - Talker 识别这 3 条输入意图相关
  - Talker 输出合并垫词："我把这几个问题合并一起查：话费变高原因、流量使用情况、增值业务订购情况"
  - Talker 调用 1 次 inject（将合并后的 prompt 注入 graph）
  - graph 内部并行查询话费+流量+增值
  - 最终返回归因结果，围绕"话费为什么高"统一说明
  - Revision Timeline 中只有 1 个 active revision（不产生多个 fork）
```

### 5.2 情况6：快速响应任务，无垫词

```
测试编号: MANUAL-002
场景描述: Talker 判断任务可以快速完成，跳过垫词直接返回结果
前置条件:
  - Talker 已实现快速响应判断逻辑
  - 页面在 /workspace/chats/{thread_id}

操作步骤:
  Step 1: 输入 "你有啥功能"
  Step 2: 观察 UI 行为

预期结果:
  - Talker 判断该问题可快速响应
  - 不调用 reply_quick 垫词 Tool（无"好的，正在..."消息）
  - 快速返回能力介绍结果
  - 整个流程 < 5 秒（包含 LLM 推理时间）
```

## 6. 执行与验证

### 运行命令

```bash
# Backend E2E
cd backend
DEER_FLOW_REVISION_RUNTIME_ENABLED=1 PYTHONPATH=. uv run pytest tests/e2e/ -v

# Frontend E2E
cd frontend
pnpm exec playwright test tests/e2e/revisions-*.spec.ts

# 全部验证
cd backend && make test && cd ../frontend && pnpm lint && pnpm typecheck && pnpm build
```

### 测试数据隔离

- Backend E2E：使用独立 SQLite 数据库（`tmp_path` fixture），每次测试自动清理
- Frontend E2E：使用 mock API handler（`/mock/api/*`），不依赖真实后端

## 7. testid 清单

实施测试前，前端组件需要添加以下 `data-testid`：

| 组件 | data-testid | 用途 |
|---|---|---|
| Chat 输入框 | `chat-input` | 输入消息 |
| Chat 发送按钮 | `chat-submit` | 发送消息 |
| Chat 取消按钮 | `chat-cancel-button` | 取消任务 |
| Chat 消息列表 | `chat-messages` | 验证消息内容 |
| Revision Timeline 容器 | `revision-timeline` | 验证 timeline 渲染 |
| Active Revision 标记 | `active-revision-badge` | 验证 active revision |
| 单个 Revision 项 | `revision-item-{revision_id}` | 验证具体 revision 状态 |

## 8. 风险与约束

| 风险 | 缓解 |
|---|---|
| Frontend E2E 依赖后端真实 API（如 inject/cancel endpoint） | Playwright 测试中用 mock API handler，或在 CI 中同时启动 backend |
| Talker 逻辑可能变更导致 mock 策略失效 | `resolveRevisionAction()` 签名保持稳定，通过单元测试守卫 |
| 情况5/6 无自动化断言 | 手工测试文档作为 Talker 验收标准，Talker 单元测试另建 |
