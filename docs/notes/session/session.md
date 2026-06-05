# Session 记录 — 2026-06-04

## 项目背景

**DeerFlow** (Deep Exploration and Efficient Research Flow) 是字节跳动开源的一个超级 Agent 框架（v2.0，全新重写，与 v1.x 无代码共享）。基于 LangGraph + LangChain 构建，提供全栈 AI Agent 能力。

### 技术栈

| 层 | 技术 |
|---|------|
| Agent 引擎 | LangGraph + LangChain (`create_agent`) |
| 后端 | Python FastAPI (port 8001) |
| 前端 | Next.js 16 + TypeScript (port 3000) |
| 反向代理 | Nginx (port 2026) |
| 持久化 | SQLite / PostgreSQL (checkpointer, store) |
| 沙箱 | Local filesystem / Docker (AIO) |

### 核心能力

- **Super Agent**：多工具协作（沙箱 bash/文件、MCP、社区工具、子代理委托）
- **Subagent 系统**：并行任务分解与委派
- **持久记忆**：跨会话 LLM 提取 + 文件存储，per-user 隔离
- **IM 集成**：飞书、Slack、Telegram、微信、钉钉、Discord
- **Skills 系统**：Markdown 定义的可扩展技能
- **MCP 集成**：Model Context Protocol 多服务器管理
- **Context 管理**：Summarization 自动压缩 + Memory 注入
- **可观测性**：LangSmith / Langfuse tracing

### 当前分支

`develop/v0.1-202605`（基于 main，包含多任务并发等最新 feature）

---

## 架构概要

### 分层结构

```
Frontend (Next.js)     →  用户交互界面
    ↓ HTTP/SSE
Gateway API (FastAPI)  →  路由、认证、Run 编排
    ↓ asyncio Task
RunManager / Dispatcher →  Run 生命周期、并发控制、队列
    ↓ agent_factory()
LangGraph Agent Graph  →  make_lead_agent() + 18 个中间件
    ↓ astream()
StreamBridge (SSE)     →  事件流解耦，生产者-消费者
    ↓
Checkpointer (SQLite)  →  对话状态持久化
```

### 核心链路（用户消息 → 响应）

```
POST /api/threads/{id}/runs/stream
  → thread_runs.py:stream_run()
    → services.py:start_run()
      → RunManager.create_or_reject()    # 创建 RunRecord
      → resolve_agent_factory()          # → make_lead_agent
      → normalize_input()                # 消息 → BaseMessage
      → build_run_config()               # RunnableConfig
      → RunDispatcher.submit()           # 提交调度
        → launch_run_task()              # asyncio.create_task
          → worker.py:run_agent()
            → agent.astream()            # LangGraph 流式执行
              → bridge.publish()         # 推事件到 StreamBridge
            → finally: bridge.publish_end()
    → StreamingResponse(sse_consumer())  # SSE 返回前端
```

### 执行模型（当前）

- **任务驱动**：每次用户消息创建一个新 Run，Run 内部完成完整 ReAct loop
- **Run 生命周期**：`pending → running → success/error/interrupted`
- **内部循环**：模型调用 → 工具调用 → 模型调用 → ... → 最终文本（在 `run_agent()` 一个 asyncio task 内完成）
- **用户角色**：被动观察者（SSE 流），只能取消整个 Run

### 中间件链（18 个，按序）

1. ThreadDataMiddleware → 2. UploadsMiddleware → 3. SandboxMiddleware → 4. DanglingToolCallMiddleware → 5. LLMErrorHandlingMiddleware → 6. GuardrailMiddleware → 7. SandboxAuditMiddleware → 8. ToolErrorHandlingMiddleware → 9. SummarizationMiddleware → 10. TodoListMiddleware → 11. TokenUsageMiddleware → 12. TitleMiddleware → 13. MemoryMiddleware → 14. ViewImageMiddleware → 15. DeferredToolFilterMiddleware → 16. SubagentLimitMiddleware → 17. LoopDetectionMiddleware → 18. ClarificationMiddleware

---

## 本 Session 已完成工作

### 1. 代码库全面探索（2026-06-04）

对 deer-flow 进行了深度架构分析，覆盖以下维度：

- **整体架构**：分层结构、模块职责、依赖关系
- **执行生命周期**：从 HTTP 请求 → RunManager → Dispatcher → worker.run_agent() → SSE 响应 的完整路径
- **对话状态管理**：ThreadState schema、checkpointer、thread_meta、run events 持久化
- **中间件系统**：18 个中间件的链式组装和执行顺序
- **前端交互**：useThreadStream()、消息合并、流式渲染、optimistic update

### 2. 多轮对话 vs 单轮对话分析

对比了 Claude Code（多轮对话驱动）与典型 Agent 框架（单轮任务驱动）的核心差异：

| 维度 | Claude Code | 典型 Agent |
|------|------------|-----------|
| 交互范式 | 对话驱动，方向可任意切换 | 任务驱动，一次性完成 |
| 工具调用 | 每轮一个工具调用，用户可见 | 内部循环，一口气执行 |
| 控制权 | 用户可在任何步骤干预 | 执行期间不可干预 |
| 上下文 | 完整历史每次都传 | 每次独立构建 prompt |
| Memory | 文件系统持久化 | 向量数据库 / Buffer |

关键结论：区分单轮/多轮的不是 memory 机制的有无，而是 **Agent Loop 的结构**——开放式对话循环 vs 封闭式任务循环。

### 3. 多轮对话改造计划

输出了完整的架构改造计划（详见 `docs/notes/task驱动/多轮对话改造计划.md`），核心思路：

- **方案**：Hybrid Approach — 保持 LangGraph graph，使用 `interrupt_before=["tools"]` + 新增 step_mode API
- **Phase 1**：后端基础 — RunStatus 新增 `awaiting_action`、捕获 GraphInterrupt、resume_agent()
- **Phase 2**：API 层 — `POST /runs/{id}/resume` 端点、审批/拒绝/重定向
- **Phase 3**：持久上下文 — 消除 Run 完成边界、thread_meta 状态扩展
- **Phase 4**：前端改造 — ToolApprovalCard、useConversationStream hook
- **Phase 5**：渐进迁移 — feature flag step_mode、4 阶段推出

### 4. 相关文档链接

| 文档 | 路径 |
|------|------|
| 多轮对话改造计划 | `docs/notes/task驱动/多轮对话改造计划.md` |
| 多任务并行 | `docs/notes/多任务并行.md` |
| 核心链路 | `docs/notes/核心链路.md` |
| Q&A (架构理解) | `docs/notes/Q&A.md` |
| 中间件 | `docs/notes/中间件.md` |
| 设计模式 | `docs/notes/设计模式与设计原则.md` |
| 技术路线 | `docs/notes/task驱动/多轮对话/技术路线.md` |

---

## 当前状态

- **分支**：`develop/v0.1-202605`
- **最新 commit**：`e4ffe9d4 feature(并发) 单个tread下多个run串行`
- **未提交改动**：多任务并发相关（dispatcher.py, queue.py, manager.py, schemas.py, worker.py 等）
- **下一步**：评审多轮对话改造计划，确认后进入 Phase 1 实现
