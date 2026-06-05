# DeerFlow 多轮协作二期 Session 记录（2026-06-05）

## 1. 会话目标

- 将 DeerFlow 从 thread 串行运行时推进到 run/revision 驱动模型。
- 已执行到 Task 6（UI + e2e）与 Task 7（迁移守卫）阶段。

## 2. 已实现（代码层）

### Backend

- 引入 revision 状态机：`pending/running/awaiting_action/paused/superseded/completed/cancelled/error`。
- 新增 root run / revision 持久化模型、仓储与 registry。
- 新增 revisions API：
  - `POST /api/runs/{revision_id}/resume`
  - `POST /api/runs/{revision_id}/inject`
  - `POST /api/threads/{thread_id}/active-run`
- 运行时升级：
  - worker 支持读取 revision checkpoint namespace。
  - dispatcher 对 superseded 任务跳过并标记 `interrupted`，避免阻塞队列。
- 迁移守卫：`start_run` 中 revision checkpoint namespace 逻辑受
  `DEER_FLOW_REVISION_RUNTIME_ENABLED` 控制。

### Frontend

- 新增 revision API/hooks（resume/inject/switch active）。
- 发送消息路径支持识别 revision intent，并走 inject/resume 分支。
- 新增 UI 组件：
  - revision timeline
  - background run list
- 两个 chat 页面新增右侧 revision/background 面板。
- e2e（revisions-flow）补齐并修正：
  - 兼容 `/api/langgraph/runs/stream` 与 `/api/langgraph/threads/*/runs/stream`
  - values 顶层注入 `revisions` / `active_revision_id`，保证与页面消费对齐。
- 修复 `frontend/src/core/threads/hooks.ts` 中 Message 类型推断问题（避免 Next/TS 启动失败）。

## 3. 已完成验证（局部）

- `cd backend && uv run pytest tests/test_revision_state_machine.py -v` ✅
- `cd backend && uv run pytest tests/test_revision_registry.py -v` ✅
- `cd backend && uv run pytest tests/test_revisions_api.py -v` ✅
- `cd backend && uv run pytest tests/test_run_queue.py tests/test_run_queue_http.py -v` ✅
- `cd frontend && pnpm vitest run tests/unit/core/revisions/api.test.ts tests/unit/core/revisions/hooks.test.ts tests/unit/core/threads/revision-intent.test.ts` ✅
- `cd frontend && CI=1 pnpm playwright test tests/e2e/revisions-flow.spec.ts --reporter=line` ✅

## 4. 当前待收口项

- 全量验证尚未执行：
  - `cd backend && make lint && make test`
  - `cd frontend && pnpm lint && pnpm typecheck`
  - `cd frontend && BETTER_AUTH_SECRET=local-dev-secret pnpm build`
- 最终变更审阅（按严重级别输出 findings）待执行。

## 5. 已知风险/注意点

- 迁移目前是“checkpoint namespace 级别守卫”，尚非完整双运行时分流器。
- revision registry 中多步业务写入仍是分步骤提交（非单事务封装）。
- 前端 chat 页面当前使用 `useMemo` 派生 timeline/background 数据；后续如需进一步对齐仓库约定，可评估抽取 selector。

## 6. 续做顺序（中断恢复指南）

1. 先跑全量收口验证命令。
2. 若失败，优先修复与本次变更直接相关问题并重跑原命令。
3. 全通过后做最终变更审阅（重点：行为回归、兼容性、测试缺口、迁移风险）。
