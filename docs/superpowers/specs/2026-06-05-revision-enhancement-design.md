# DeerFlow Revision Runtime 增强设计

> 2026-06-05 | 基于 `develop/v0.01-20260605` 已实现的 Revision 架构之上

## 1. 目标

支持 4 个产品场景的原语级覆盖：

| 场景 | 产品描述 | 需要的 Runtime 原语 | 状态 |
|---|---|---|---|
| 情况2 修改参数 | 上月话费 → 改成本月 | inject (增强) | 需改 |
| 情况3 停止任务 | 算了不查了 | cancel (增强) | 需改 |
| 情况4 补充信息 | 我没订过啊 → 重点调整 | inject (复用) | 已有覆盖 |
| 情况5 合并任务 | 话费+流量+增值→合并 | inject (复用) | Talker 层负责合并 |

职责边界：**Talker 做意图识别和 prompt 重组，Runtime 提供 inject / cancel / resume 三个原语**。

## 2. 核心变更

### 2.1 Checkpoint 继承 —— inject 增强

**旧行为**：`fork_revision()` 为 child 生成独立 checkpoint namespace (`run:{root}:rev:{child_id}`)，child 从空 checkpoint 开始执行。

**新行为**：child 直接继承 parent 的 `checkpoint_namespace`，child 的 run 从 parent 的 checkpoint 继续追加。

```
inject 前:
  Rev-A (active), checkpoint_ns = "run:root1:rev:rev-a"
  checkpoint: {msg1, msg2, tool_call, result}

inject 后:
  Rev-A (superseded), checkpoint_ns = "run:root1:rev:rev-a"  ← 元数据保留
  Rev-B (active),    checkpoint_ns = "run:root1:rev:rev-a"  ← 继承，同一个 ns
  checkpoint: {msg1, msg2, tool_call, result, msg3(new), ...}
```

**代码变更** (`registry.py` `fork_revision()` 方法)：

```python
# 旧: 新建独立 namespace
checkpoint_namespace=self._checkpoint_namespace(parent.root_run_id, revision_id)

# 新: 继承 parent 的 namespace
checkpoint_namespace=parent.checkpoint_namespace
```

**影响**：Worker 的 `_resolve_checkpoint_namespace` 无需修改——它本来就是从 config 读 namespace，不管 namespace 是新建的还是继承的。

### 2.2 Cancel 联动 Revision 状态机 —— cancel 增强

**旧行为**：`RunManager.cancel(run_id)` 只改 run 状态为 `interrupted`，revision 状态不变（仍为 `running`），导致前端看到的 revision 状态不准确。

**新行为**：run 被 cancel 后，触发 `on_run_cancelled` 回调 → `RevisionRegistry` 将对应 revision 状态转为 `cancelled`。

**新增状态转移**：

```
running          → cancelled   (执行中被用户停止)
paused           → cancelled   (暂停后用户放弃)
awaiting_action  → cancelled   (审批等待中用户放弃)
```

**回调注册** (`Dispatcher`)：

```python
class RunDispatcher:
    def set_on_run_cancelled(self, handler: Callable[[str, str], Awaitable[None]] | None):
        self._on_run_cancelled = handler

    # 在 RunManager.cancel() 完成后调用
    async def on_run_cancelled(self, thread_id: str, run_id: str):
        if self._on_run_cancelled:
            await self._on_run_cancelled(thread_id, run_id)
```

**Gateway 启动时注入** (`deps.py` `langgraph_runtime()`)：

```python
from app.gateway import services

async def _on_run_cancelled(thread_id: str, run_id: str):
    # 查找 run 对应的 revision，联动状态
    ...

dispatcher.set_on_run_cancelled(_on_run_cancelled)
```

**run→revision 关联**：当前 `start_run()` 中 `revision_id` 未存入 run metadata，需要在创建 run 时写入：

```python
# services.py start_run(), 在 checkpoint_ns 注入之后
if _revision_runtime_enabled() and revision_id:
    body.metadata = body.metadata or {}
    body.metadata.setdefault("revision_id", revision_id)
    body.metadata.setdefault("root_run_id", root_run_id)
```

cancel 回调通过 `run_manager.get(run_id).metadata` 读取 `revision_id`，然后调 `registry.transition_revision(revision_id, "cancelled")`。

### 2.3 Resume —— 不变

`resume` 原语 (`POST /runs/{rev}/resume`) 无需修改：
- 状态机校验 `paused / awaiting_action → running`
- 不涉及 checkpoint namespace 变更

## 3. 情况4（补充信息）的实现路径

```
用户: "我没订过啊"
  → Talker: 识别为补充信息，调 inject(rev, "我没订过啊，重点查凭证")
  → Runtime:
    1. 如果当前 run 正在执行 → cancel(run_id, action=interrupt)
    2. fork_revision() → 继承 checkpoint namespace
    3. 新建 run → 从 checkpoint 继续，graph 看到完整历史
  → graph: 在已有上下文中自然回应补充
```

**不新增 "send" 原语**。已有的 inject 增强（继承 checkpoint namespace）已经覆盖了这个需求。

## 4. 情况5（合并任务）由 Talker 层覆盖

Runtime 不做子 revision、并行 graph、聚合等机制。Talker 判断多输入相关后，可以：

- 将所有子问题重组为一个 prompt
- 调用一次 inject，一次性发入 graph
- graph 内部自然进行多步 tool call

## 5. 后端文件变更清单

| 文件 | 变更 |
|---|---|
| `runtime/revisions/registry.py` | `fork_revision()`: child 继承 parent 的 `checkpoint_namespace` |
| `runtime/revisions/state_machine.py` | 新增 `running/paused/awaiting_action → cancelled` |
| `runtime/runs/dispatcher.py` | 新增 `on_run_cancelled` 回调槽位 |
| `app/gateway/deps.py` | 启动时注入 `on_run_cancelled` → 联动 revision 状态 |
| `app/gateway/services.py` | 可能需要读取 run metadata 中的 revision_id 以建立关联 |
| `tests/test_revision_registry.py` | 新增 checkpoint 继承的测试 |
| `tests/test_revision_state_machine.py` | 新增 cancel 转移的测试 |

## 6. 前端文件变更清单

| 文件 | 变更 |
|---|---|
| `core/threads/hooks.ts` | cancel 成功后刷新 revision 列表 |
| `components/workspace/revisions/revision-timeline.tsx` | 展示 checkpoint 继承链（同一族的 revision 用视觉连线） |

## 7. Feature Flag

沿用 `DEER_FLOW_REVISION_RUNTIME_ENABLED`：
- 关闭时：checkpoint namespace 保持 `""`，无 revision 行为
- 开启时：上述所有增强生效

## 8. 风险与约束

| 风险 | 缓解 |
|---|---|
| fork 时如果 parent 有正在执行的 run，两个 run 同时写同一个 checkpoint namespace → 竞态 | fork 前 cancel parent 的 inflight run（已有 superseded 跳过逻辑保障） |
| checkpoint 继承后，回放时无法区分"哪个 revision 产生了哪段" | revision 元数据保留 parent/supersedes 链，前端可据此展示 |
| cancel → revision 联动需要 run→revision 的映射 | 评估当前 run metadata 是否已有 revision_id；若无，新增字段 |
