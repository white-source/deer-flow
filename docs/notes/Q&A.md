

---------------------------
架构理解题 — 完整解答 

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q1（L1） 

 make_lead_agent(config)  返回的是什么类型？它是在什么时候被调用的——服务启动时，还是每次用户发消息时？ create_agent()  的三个核心参数是什么？

 返回类型 

返回一个 LangGraph  Runnable  图（ langchain.agents.create_agent()  编译后的结果）。该对象实现了  astream()  /  invoke()  接口，可在 LangGraph 运行时中执行。

 ▎ 证据：agent.py:347-351

 调用时机 

每次用户发消息时（每个 run 执行时），不是服务启动时。在  run_agent()  中显式调用  agent_factory(config=runnable_config) 。

 ▎ 证据：worker.py:198-202

 create_agent() 的三个核心参数 

 参数          来源                                                                作用        
 ───────────── ─────────────────────────────────────────────────────────────────── ────────────
 model         create_chat_model(name=..., attach_tracing=False)                   LLM 模型实例
 tools         get_available_tools(...) + filter_tools_by_skill_allowed_tools(...) 可用工具列表
 system_prompt apply_prompt_template(...)                                          系统提示模板

额外还传了  middleware= （中间件链）和  state_schema=ThreadState （状态模式）。

 ▎ 证据：agent.py:347-351

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q2（L1） 

从用户发一条消息到收到第一条 SSE chunk，依次经过哪些模块？列出主要函数调用链（4-5 个关键步骤）。

 ┌──────────────────────────────────────────────────────────────────────────┐ 
 │ ① Gateway 路由层                                                        │ 
 │ app/gateway/routers/thread_runs.py                                       │ 
 │ POST /api/threads/{id}/runs/stream                                       │ 
 │ → 校验 RunCreateRequest，调 start_run()                                  │ 
 ├──────────────────────────────────────────────────────────────────────────┤ 
 │ ② 服务层                                                                │ 
 │ app/gateway/services.py :: start_run()                                   │ 
 │ → RunManager.create_or_reject() 创建记录                                 │ 
 │ → resolve_agent_factory() → make_lead_agent                             │ 
 │ → asyncio.create_task(run_agent(...)) 启动后台                           │ 
 ├──────────────────────────────────────────────────────────────────────────┤ 
 │ ③ 运行时 worker                                                         │ 
 │ runtime/runs/worker.py :: run_agent()                                    │ 
 │ → 设置 RunContext(checkpointer, store, ...)                              │ 
 │ → agent_factory(config) 构建图                                           │ 
 │ → agent.astream(graph_input, ...) 启动图执行                             │ 
 ├──────────────────────────────────────────────────────────────────────────┤ 
 │ ④ 图编译 + 执行                                                         │ 
 │ agents/lead_agent/agent.py :: _make_lead_agent()                         │ 
 │ → create_chat_model() 创建模型                                           │ 
 │ → get_available_tools() + filter_tools...() 加载工具                     │ 
 │ → _build_middlewares() 组装中间件链                                      │ 
 │ → apply_prompt_template() 生成系统提示                                   │ 
 │ → create_agent() 返回 Runnable 图                                        │ 
 ├──────────────────────────────────────────────────────────────────────────┤ 
 │ ⑤ SSE 事件流                                                            │ 
 │ agent.astream() 产出事件 → StreamBridge.publish(run_id, event, data)     │ 
 │ services.py :: sse_consumer() → bridge.subscribe() → 格式化 SSE 帧       │ 
 │ → yield 给 FastAPI StreamingResponse → 客户端收到第一条 SSE chunk        │ 
 └──────────────────────────────────────────────────────────────────────────┘ 

 ▎ 证据：thread_runs.py:1-130、services.py:154-220、worker.py:138-248

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q3（L1） 

Lead Agent 的中间件链有 18 个中间件。其中哪 3 个是「始终启用」的？哪一个是「必须放在最后」的？它们的顺序为什么重要？

 3 个「始终启用」的中间件 

文档中标注为"始终开启"的中间件：

 #  中间件                      钩子                                                                  作用                                        
 ── ─────────────────────────── ───────────────────────────────────────────────────────────────────── ────────────────────────────────────────────
 3  DanglingToolCallMiddleware  wrap_model_call                                                       补全悬空的 ToolMessage（模型看到历史前修复）
 5  ToolErrorHandlingMiddleware wrap_tool_call                                                        工具异常 → ToolMessage，让运行继续          
 12 LoopDetectionMiddleware     before_agent, before_model, after_model, wrap_model_call, after_agent 检测并打破重复工具调用循环                  

 ▎ 证据：middleware-execution-flow.md:24-30

 必须放在最后的一个 

 ClarificationMiddleware （#13）

 为什么顺序重要 

LangChain 中间件的执行规则是  after_*  反序执行（列表 N → 0）。 ClarificationMiddleware  在列表末尾，其  wrap_tool_call  是最内层的钩子，因此最先拦截模型输出。当模型返回  ask_clarification  
工具调用时，它立刻返回  Command(goto=END)  中断执行——不需要等其他中间件处理。如果放在前面，其他中间件会先浪费 token 处理一个本应中断的响应。

 ▎ 证据：middleware-execution-flow.md:136-140、agent.py 注释  # ClarificationMiddleware should always be last 

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q4（L2） 

 agent.py  顶部 docstring 声明了一个 tracing invariant。请复述并说明：如果在  _create_summarization_middleware()  里创建 LLM 模型时忘了传  attach_tracing=False ，Langfuse 上会看到什么症状？

 Tracing Invariant 

 ▎ Tracing callbacks（Langfuse, LangSmith）只在 graph 调用根节点 ( _make_lead_agent  中的  build_tracing_callbacks()  追加到  config["callbacks"] ) 附加。每个在此模块内——以及在任何从此图可达的中间件内——的 
    create_chat_model(...)  调用，都必须传  attach_tracing=False 。

四个已知的现场：bootstrap agent、default agent、summarization middleware、 TitleMiddleware  异步路径。

 ▎ 证据：agent.py:4-11

 忘了 attach_tracing=False 的症状 

 1. 重复 span（duplicate spans）—— Langfuse 上同一 LLM 调用显示两次：一个根在 graph 级别，一个根在 model 级别。
 2.  session_id  /  user_id  丢失 —— Langfuse handler 的  propagate_attributes  只在  on_chain_start(parent_run_id=None) （root-level）时触发。当 span 嵌套在 graph 内时，handler 剥离  langfuse_*  键，导致 
    trace 上不显示  session_id  和  user_id 。

 ▎ 证据：agent.py:173-185

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q5（L2） 

 filter_tools_by_skill_allowed_tools()  在什么情况下会裁剪工具列表？什么情况下放行全部？如果新增一个 skill 声明  allowed-tools: [read_file, search_content] ，但其他 skill 
都没有该字段，最终暴露的工具列表是什么？

 裁剪条件 

至少有一个 skill 声明了  allowed_tools （非  None ）。取这些 skill 的  allowed_tools  并集，只保留在此集合中的工具。

 放行全部的条件 

没有任何一个 skill 声明  allowed_tools （全部为  None ）。函数返回  None  → 外层直接返回完整  tools  列表。

 新增一个 skill 声明的结果 

最终工具列表被裁剪为  {read_file, search_content} 。因为：

 · skill A 声明了  allowed_tools  →  has_explicit_declaration = True 
 · 其他 skill  allowed_tools = None  → 代码走  continue ，不贡献任何工具
 ·  allowed = {"read_file", "search_content"} 
 · 最终只保留这两个工具

 ▎ 证据：tool_policy.py:10-40、tool_policy.py:25-26

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q6（L2） 

 RunManager.create_or_reject()  的  multitask_strategy  有哪些可选值？默认值是什么？如果 SSE 流没结束时用户又发一条消息，默认行为是什么？要实现「打断当前回答，开始新的」，应该怎么处理？

 可选值 

 策略        行为                                              状态     
 ─────────── ───────────────────────────────────────────────── ─────────
 "reject"    线程有 inflight run → 抛 ConflictError（409）     ✅ 默认值
 "interrupt" 取消 inflight run（设置 abort_event），创建新 run ✅ 实现  
 "rollback"  取消 inflight run + 回滚 checkpoint 到 run 前状态 ✅ 实现  
 "enqueue"   在 schema 中声明，运行时不支持 → 501              ❌ 未实现

 ▎ 证据：manager.py:505-568

 默认值 

 "reject" 。来自  RunRecord.multitask_strategy = "reject"  和  create_or_reject  的默认参数。

 SSE 流未结束时用户发新消息 

返回 HTTP 409 Conflict，消息被拒绝。

 实现「打断当前回答，开始新的」 

客户端传  multitask_strategy: "interrupt" 。服务端：

 1. 找到该 thread 全部  inflight  run（ status in (pending, running) ）
 2. 设置  abort_action = "interrupt" 
 3. 调用  abort_event.set()  → worker 的  record.abort_event.is_set()  为 True → 退出循环
 4. 旧 run 标记  RunStatus.interrupted 
 5. 新 run 开始执行

如需撤销旧 run 副作用（已写入的对话），用  "rollback"  替代。

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q7（L3） 

为系统提示增加  <team_context>  块，内容来自  config.yaml  新字段  team_info 。需改哪几个文件？哪些函数？提示：注意缓存问题。

 修改文件 

文件    : config.yaml
修改内容: 新增 team_info: "Our team is ..." 字段

文件    : deerflow/config/app_config.py
修改内容: AppConfig 类新增 team_info: str = Field(default="")

文件    : deerflow/agents/lead_agent/prompt.py
修改内容: ① SYSTEM_PROMPT_TEMPLATE 插入 {team_context} 占位符<br>② apply_prompt_template() 中新增 _build_team_context_section(app_config)<br>③ 结果传给 .format(team_context=...)

 修改函数 

 ·  apply_prompt_template()  —— 调用新构建函数，传给模板
 ·  AppConfig.from_file()  —— 自动通过 Pydantic 读取，无需额外代码

 缓存问题 

当前系统提示完全静态编译，注释明确说明："Memory and current date are injected per-turn via DynamicContextMiddleware…keeping this prompt identical across users and sessions for maximum prefix-cache reuse" 
prompt.py:808-812。

 · 如果  team_info  全局固定：直接加入模板 ✅ 不会破坏缓存
 · 如果  team_info  每个用户不同：应改为在  DynamicContextMiddleware  中用  <system-reminder>  注入，避免缓存碎片化

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q8（L3） 

新增  RateLimitMiddleware ，在 LLM 调用前检查用户请求频率。

 1. 插入位置 

在  ClarificationMiddleware  之前、 SafetyFinishReasonMiddleware  之后：

 … → SafetyFinishReasonMiddleware → [RateLimitMiddleware] → ClarificationMiddleware 

位置最后 →  wrap_model_call  /  before_model  最内层执行 → LLM 调用前最早拦截。 before_model  适合限制"本轮是否允许 LLM 调用"； wrap_tool_call  适合限制工具调用频率。

 2. 测试文件 

 · 文件名： tests/test_rate_limit_middleware.py 
 · 测试模式：使用 mock LLM（FakeToolCallingModel），不是 real API

 3. FakeToolCallingModel 构造代码 

 python
 from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel 
 from langchain_core.messages import AIMessage 
 from langchain_core.runnables import Runnable 
 from typing import Any 
  
  
 class FakeToolCallingModel(FakeMessagesListChatModel): 
     """FakeMessagesListChatModel + no-op bind_tools for create_agent.""" 
  
     def bind_tools( 
         self, 
         tools: Any, 
         *, 
         tool_choice: Any = None, 
         **kwargs: Any, 
     ) -> Runnable: 
         return self 

 ▎ 证据：tests/_agent_e2e_helpers.py:20-30

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q9（L3） 

 config.yaml  中哪些字段修改后不需要重启？哪些必须重启？判断依据是什么？新增「实时生效」字段， AppConfig  哪里改、哪里不改？

 不需要重启的字段（热加载） 

 get_app_config()  每次调用都检查文件 mtime，变化自动重载：

 字段                           说明                                            
 ────────────────────────────── ────────────────────────────────────────────────
 log_level                      每个请求重新读取                                
 models                         新增 model 立即可用                             
 tools / tool_groups            工具列表即时生效                                
 skills                         skill 配置即时生效                              
 title / summarization / memory 通过 _apply_singleton_configs() 同步到模块级单例
 token_usage                    配置开关即时生效                                

 ▎ 证据：app_config.py:360-389

 必须重启的字段 

 字段                                   原因                                                            
 ────────────────────────────────────── ────────────────────────────────────────────────────────────────
 database                               DB 连接池启动时初始化                                           
 checkpointer                           切换后端需要重启；虽然有 reset_checkpointer() 但运行时切换有风险
 stream_bridge                          SSE 事件总线应在启动时固定                                      
 任何 @lru_cache / 模块导入时捕获的配置 闭包中缓存的引用无法热更新                                      

 ▎ 证据：app_config.py:204-211

 判断依据 

消费方读取路径：如果都用  get_app_config()  → 热加载有效；如果模块导入时或闭包中捕获 → 需重启。

 新增「实时生效」字段 

 · 需要改：消费方代码中  get_app_config().team_info 
 · 不需要改： AppConfig  已有  model_config = ConfigDict(extra="allow") ，允许未声明的额外字段；也不需要在  _apply_singleton_configs  中注册

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Q10（L4） 

实现「Agent 工作流编排」—— 定义一系列顺序步骤，上一步输出传下一步，各步可用不同 model/config。

 1. 整体方案 

方案：新的 agent type（新 agent 工厂） + 配套工具。

 否决的方案          理由                                                                                                             
 ─────────────────── ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 ❌ 新工具           工作流不是原子操作，是执行上下文                                                                                 
 ❌ Skill            Skill 是提示模板 + 工具白名单，不具备执行语义                                                                    
 ❌ 改现有 task 工具 task 是并发子代理调度，不是顺序管道                                                                              
 ✅ 新 agent type    类似 bootstrap agent 的独立图：独立的 state_schema（WorkflowState：步骤列表、当前步、变量映射表）和 middleware 链

工作流编排本质是一个步骤序列状态机，正好对应 LangGraph 节点编排能力。

 2. 最少改哪些文件 

 文件                                改动                                                                  
 ─────────────────────────────────── ──────────────────────────────────────────────────────────────────────
 agents/workflow_agent/agent.py 🆕   make_workflow_agent() 工厂：定义 WorkflowState、create_agent()、中间件
 agents/workflow_agent/prompt.py 🆕  工作流执行专用提示模板，说明变量引用语法 ${{step1.output}}            
 tools/builtins/workflow_tools.py 🆕 run_workflow_step、define_workflow 等内置工具                         
 agents/lead_agent/agent.py          get_available_tools() 新工作流工具（如需 lead agent 触发工作流）      
 runtime/runs/worker.py              resolve_agent_factory 注册新的 agent_type 分发                        

 3. 会破坏现有 invariant 吗？ 

 Invariant         影响    理由                                                                                      
 ───────────────── ─────── ──────────────────────────────────────────────────────────────────────────────────────────
 Tracing invariant ✅ 不会 只要新工厂中所有 create_chat_model() 传 attach_tracing=False                              
 Skill tool policy ✅ 不会 工作流 agent 管理自己内部工具；若通过 lead agent 触发，start_workflow 工具本身需在白名单中

主要风险：WorkflowState 的变量传递需要类似  ThreadState  的  reducer （如  merge_artifacts  去重），防止并发步骤的变量写入竞态。现有 reducer 模式可直接复用。
