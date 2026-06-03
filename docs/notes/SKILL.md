什么时候用哪个？ 

 用户输入 
     │ 
     ├─ "帮我搜索 X 的最新消息" 
     │   → Tool: web_search（系统自动执行搜索） 
     │ 
     ├─ "帮我深入研究 X 主题，写一份报告" 
     │   → Skill: 先 read_file "deep-research" 加载方法论 
     │   → 然后按照文档手动调用 web_search 多次 
     │   → 最后合成报告 
     │ 
     ├─ "运行这个 Python 脚本" 
     │   → Tool: bash / python（系统执行代码） 
     │ 
     ├─ "分析这个 Excel 文件" 
     │   → Skill: 先 read_file "data-analysis" 加载工作流 
     │   → 然后按文档调用 bash 运行 analyze.py 
     │ 
     ├─ "同时查 X、Y、Z 三个事情" 
     │   → Tool: task（并行子代理，系统自动调度） 
     │ 
     └─ "对比 AWS、Azure、GCP 的定价" 
         → Skill + Tool 组合： 
           1. Skill "deep-research" 告诉你要多渠道搜索 
           2. 调用 task 工具并行查三家 
           3. 合成结果 

 一句话总结 

Tool 是让系统替你干活；Skill 是告诉 LLM 该怎么干活。 Tool 是代码（可执行），Skill 是文档（需阅读后手动执行）。LLM 在回答问题时，可以自由选择这两种方式——遇到简单操作直接调工具，遇到复杂工作流先读 skill 
再按指导执行。

---
Tool vs Skill：根本区别 

 维度         Tool                                                          Skill                                                                                    
 ──────────── ───────────────────────────────────────────────────────────── ─────────────────────────────────────────────────────────────────────────────────────────
 本质         可执行的函数（代码）                                          Markdown 工作流文档（文本）                                                              
 格式         Python 函数 + @tool 装饰器 / BaseTool 子类                    带 frontmatter 的 SKILL.md 文件                                                          
 如何生效     通过 bind_tools() 注册到 LLM 的 tool schema，LLM 可以直接调用 通过 <available_skills> 列表展示给 LLM，LLM 先 read_file 阅读，然后手动执行其中描述的步骤
 执行者       系统/运行时执行代码                                           LLM 自己按照文档描述手动操作                                                             
 能否直接调用 ✅ LLM 直接发 tool_call，系统自动执行                         ❌ LLM 需要读文档后手动调工具来执行每一步                                                
 内容         Python 代码、参数 schema、返回值                              工作流步骤、最佳实践、bash 命令示例、参考链接                                            

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Tool：系统替你执行 

工具是一个可被 LLM 调用的函数。模型返回一个  tool_call ，系统自动执行该函数并返回结果。

 python
 # task_tool.py — 模型只需调用，系统自动执行 
 @tool("task", parse_docstring=True) 
 async def task_tool( 
     runtime: Runtime, 
     description: str, 
     prompt: str, 
     subagent_type: str, 
     tool_call_id: Annotated[str, InjectedToolCallId], 
 ) -> str: 
     """Delegate a task to a specialized subagent...""" 
     # ... 系统自动运行这段代码 

模型视角：

 ▎ 我要查 X → 调用  web_search(query="X")  → 系统执行搜索 → 返回结果

 ▎ 证据：task_tool.py:186-192

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 Skill：LLM 自己照着文档执行 

Skill 是一个Markdown 工作流文档，告诉 LLM 怎么做。模型需要：

 1. 识别场景匹配 →  read_file  加载  SKILL.md 
 2. 阅读工作流步骤
 3. 手动调用底层的  read_file 、 bash 、 web_search  等工具来执行每一步

以  deep-research  skill 为例：

 markdown
 ## Research Methodology 
  
 ### Phase 1: Broad Exploration 
 1. **Initial Survey**: Search for the main topic 
 2. **Identify Dimensions**: From initial results, identify key subtopics 
  
 ### Phase 2: Deep Dive 
 For each dimension identified: 
 - Multiple search queries with different phrasings 
 - Follow interesting threads and cross-references 
  
 ### Phase 3: Synthesis 
 - Cross-reference findings across sources 
 - Identify patterns and gaps 

模型执行这个 skill 时不会调用一个叫 "deep-research" 的工具（不存在这个工具），而是：

 1.  web_search("topic overview")  → 获取结果
 2.  web_search("topic subtopic1")  → 深入挖掘
 3.  web_search("topic subtopic2")  → 继续挖掘
 4. 用 thinking 合成结果

 ▎ 证据：skills/public/deep-research/SKILL.md:1-40

----
系统中的 Tool 分布在 4 个目录层级，按类型分 5 大类。下面是完整清单：

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 系统支持的 Tool 完整清单 

 目录结构总览 

 backend/packages/harness/deerflow/tools/ 
 ├── tools.py                          ← 注册中心（get_available_tools） 
 ├── builtins/                         ← 内置工具 
 │   ├── clarification_tool.py         → ask_clarification 
 │   ├── present_file_tool.py          → present_file 
 │   ├── task_tool.py                  → task（子代理并行调度） 
 │   ├── tool_search.py                → tool_search（延迟加载工具） 
 │   ├── view_image_tool.py            → view_image 
 │   ├── setup_agent_tool.py           → setup_agent（自定义 agent 创建） 
 │   ├── update_agent_tool.py          → update_agent（自定义 agent 更新） 
 │   └── invoke_acp_agent_tool.py      → invoke_acp_agent（ACP 协议代理） 
 ├── skill_manage_tool.py              → manage_skills（skill 演化管理） 
 │ 
 deerflow/sandbox/tools.py             ← 沙箱核心工具（文件系统 + bash） 
 deerflow/sandbox/local/list_dir.py    ← list_dir 辅助实现 
 deerflow/community/*/tools.py         ← 社区集成工具（第三方服务） 
 deerflow/mcp/tools.py / cache.py      ← MCP 服务器工具（外部 MCP 协议） 

 ▎  get_available_tools()  是注册中心——它从 config.yaml 加载配置的工具、附加内置工具、MCP 工具、ACP 工具并去重返回。证据：tools.py:50-210

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第一类：沙箱核心工具（Sandbox Tools） 

文件位置： backend/packages/harness/deerflow/sandbox/tools.py 

这些是操作文件系统和执行命令的基础工具，条件启用（取决于 sandbox provider 和安全策略）：

 Tool 名称   函数               作用                         
 ─────────── ────────────────── ─────────────────────────────
 bash        bash_tool()        在 Linux 沙箱中执行 bash 命令
 ls          _ls_tool()         列出目录内容                 
 glob        glob_tool()        递归匹配文件名               
 grep        grep_tool()        在文件内容中搜索文本         
 read_file   read_file_tool()   读取文件内容                 
 write_file  write_file_tool()  写入/覆盖文件                
 str_replace str_replace_tool() 字符串替换编辑               

 ▎ 证据：sandbox/tools.py:1328-1734

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第二类：内置工具（Built-in Tools） 

文件位置： backend/packages/harness/deerflow/tools/builtins/ 

这些是始终可用或条件启用的核心工具：

 Tool 名称         文件                     启用条件                     作用                   
 ───────────────── ──────────────────────── ──────────────────────────── ───────────────────────
 ask_clarification clarification_tool.py    ✅ 始终                      向用户提问澄清         
 present_file      present_file_tool.py     ✅ 始终                      将文件内容展示给用户   
 task              task_tool.py             subagent_enabled=True        启动并行子代理         
 view_image        view_image_tool.py       模型支持 vision              查看图像               
 tool_search       tool_search.py           tool_search.enabled=True     搜索/激活延迟加载的工具
 setup_agent       setup_agent_tool.py      bootstrap 流程               创建自定义 agent       
 update_agent      update_agent_tool.py     自定义 agent 有 agent_name   更新 agent 配置        
 invoke_acp_agent  invoke_acp_agent_tool.py 配置了 ACP agents            调用 ACP 协议代理      
 manage_skills     skill_manage_tool.py     skill_evolution.enabled=True skill 演化管理         

 ▎ 证据：tools/tools.py:20-110

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第三类：社区集成工具（Community Tools） 

文件位置： backend/packages/harness/deerflow/community/*/tools.py 

这些是第三方服务对接的工具，通过  config.yaml  中的  tools  字段条件加载：

 Tool 名称    提供方                                                     文件                  作用        
 ──────────── ────────────────────────────────────────────────────────── ───────────────────── ────────────
 web_search   DuckDuckGo / Tavily / Serper / Exa / Firecrawl / InfoQuest */tools.py            网页搜索    
 web_fetch    Jina AI / Exa / Tavily / Firecrawl / InfoQuest             */tools.py            抓取网页内容
 image_search InfoQuest / 独立实现                                       image_search/tools.py 图片搜索    

每种服务商提供一个同名的 tool（如  web_search ），config.yaml 里配置用哪个。配置示例：

 yaml
 tools: 
   - name: web_search 
     use: deerflow.community.tavily.tools:web_search_tool 
     group: search 

 ▎ 证据：community/tavily/tools.py:17-19

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第四类：MCP 工具（MCP Tools） 

文件位置： backend/packages/harness/deerflow/mcp/ 

通过 MCP 协议对接的外部服务器工具。在运行时动态加载和缓存，工具名取决于 MCP 服务器的配置：

 组件      文件          作用                         
 ───────── ───────────── ─────────────────────────────
 cache.py  mcp/cache.py  MCP 工具缓存（按 mtime 刷新）
 client.py mcp/client.py MCP 协议客户端               
 tools.py  mcp/tools.py  MCP 工具适配器               

注册流程在  config.yaml  →  extensions_config.json  → MCP 服务器 → 缓存  get_cached_mcp_tools() 

 ▎ 证据：tools/tools.py:115-160

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第五类：Config 加载工具（Config-loaded Tools） 

文件位置： backend/packages/harness/deerflow/sandbox/tools.py  +  community/*/tools.py 

在  config.yaml  的  tools  字段中按  use:  路径引用。除社区工具外，还包括：

 工具名                           来源     作用          
 ──────────────────────────────── ──────── ──────────────
 任何在 config.yaml 中配置的 use: 动态加载 用户自定义工具

工具分组（通过  tool_groups  配置表指定）可以按组开关，如  database 、 search 、 sandbox  等。

 ▎ 证据：tools/tools.py:50-76

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 总结：4 类 Tool 的启用/加载方式 

 加载途径                         目录                            启用机制 
 ─────────                       ──────────                      ────────── 
 sandbox/tools.py 的 @tool         sandbox/tools.py              条件（取决于 sandbox 类型和安全性） 
 内置 BUILTIN_TOOLS 列表           tools/builtins/               始终 / 条件（vision、subagent 等） 
 社区 tools（config 中 use: 路径） community/*/                  使用 resolve_variable 按名加载 
 MCP 工具                          mcp/                          按 extensions_config 动态加载 
 ACP 代理工具                      tools/builtins/                按 ACP agent 配置启用 


----
了代码后，答案是：不完全是。识别意图 + 匹配 skill 只是其中一条路径，而且不是主路径。DeerFlow 的自主规划是一个多级、分层的机制。

 整体架构 

 用户输入 
     │ 
     ▼ 
 ┌──────────────────────────────────────────────────┐ 
 │ ① 系统提示中的规划指令（全局）                     │ 
 │    CLARIFY → PLAN → ACT                          │ 
 │    思考风格：分解任务 → 识别歧义 → 逐步执行        │ 
 ├──────────────────────────────────────────────────┤ 
     │ 
     ▼ 
 ┌──────────────────────────────────────────────────┐ 
 │ ② 识别是否是 skill 场景           ③ 识别是否需分解 │ 
 │                                  │              │ 
 │ 是 ──→ read_file 加载 skill 内容  │ 否            │ 
 │ 执行 skill 中定义的工作流          │              │ 
 │                                  ▼              │ 
 │                              ④ 判断复杂度        │ 
 │                                  │              │ 
 │                     ┌────────────┼────────────┐ │ 
 │                     ▼            ▼            ▼ │ 
 │               简单任务     复杂可并行     顺序依赖 │ 
 │              直接调工具    task 子代理    手动分步 │ 
 └──────────────────────────────────────────────────┘ 

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第一层：CLARIFY → PLAN → ACT（通用规划框架） 

系统提示明确告诉模型：

 **WORKFLOW PRIORITY: CLARIFY → PLAN → ACT** 
 1. FIRST: Analyze the request - identify unclear/ambiguous/missing 
 2. SECOND: If clarification needed, call ask_clarification IMMEDIATELY 
 3. THIRD: Only after all clarifications resolved, proceed with planning and execution 

这不是通过匹配 skill 来规划，而是让 LLM 自主分析任务、识别歧义、规划执行路径。模型自己决定先问清楚再动手。prompt.py:430-445

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第二层：Skill 是被动加载的，不是自动匹配的 

对比你的假设和实际代码：

 你的假设                                        实际情况                                                            
 ─────────────────────────────────────────────── ────────────────────────────────────────────────────────────────────
 "识别意图 → 自动匹配 skill → 执行 skill 工作流" Skill 不会自动执行，只是作为 <available_skills> 列表展示在系统提示中
 模型会自动知道该用哪个 skill                    模型需要在 thinking 中识别场景，手动 read_file 加载 skill 内容      

关键代码——系统的 skill 提示节：

 <skill_system> 
 You have access to skills that provide optimized workflows for specific tasks. 
  
 **Progressive Loading Pattern:** 
 1. When a user query matches a skill's use case, immediately call `read_file` on the skill's main file 
 2. Read and understand the skill's workflow and instructions 
 3. Load referenced resources only when needed during execution 
 4. Follow the skill's instructions precisely 
  
 <available_skills> 
     <skill> 
         <name>code-review</name> 
         <description>Guidelines for reviewing code changes</description> 
         <location>/mnt/skills/code-review/SKILL.md</location> 
     </skill> 
     ... 
 </available_skills> 
 </skill_system> 

 ▎ 证据：prompt.py:609-623

Skill 是一个"先读后执行"的参考文档，不是插件。模型先看描述，如果觉得匹配就主动  read_file  加载内容，然后按其中的工作流执行。

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第三层：任务分解 —— task 工具（子代理） 

对于复杂任务，系统提示指导模型主动分解：

 - **DECOMPOSITION CHECK: Can this task be broken into 2+ parallel sub-tasks? 
   If YES, COUNT them. NEVER launch more than N task calls in one response.** 

模型在 thinking 阶段自己决定：

 1. 计数：列出所有子任务，"我有 N 个子任务"
 2. 分批：如果 N > 最大并发数，规划批次
 3. 执行：并行调用  task  工具启动子代理
 4. 合成：所有结果回来后合成

 ▎ 证据：prompt.py:275-362

这是纯 LLM 自主规划，不是 skill 匹配。

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 第四层：直接工具执行 

对于简单任务，系统提示明确指示不要用 skill 也不要 task：

 ❌ DO NOT use subagents (execute directly) when: 
 - Task cannot be decomposed: If you can't break it into 2+ meaningful parallel sub-tasks 
 - Ultra-simple actions: Read one file, quick edits, single commands 

模型直接调用  read_file 、 edit_file 、 bash  等工具完成任务。

 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

 总结：三阶段自主规划流程 

 阶段一：分析 
   用户输入 → 模型 in-context thinking 
   ├─ 识别歧义/缺失信息 → ask_clarification（先问清楚） 
   ├─ 识别 skill 场景   → read_file 加载 skill 内容，按工作流执行 
   └─ 否则 → 进入阶段二 
  
 阶段二：分解 
   ├─ 无法分解（1步完成） → 直接调工具 
   ├─ 可并行分解（2+独立子任务） → task 工具分批执行 
   └─ 顺序依赖 → 手动分步执行（模型自己控制回合） 
  
 阶段三：执行 
   调用工具或子代理 → 收集结果 → 合成最终回答 

所以核心回答是：自主规划主要依赖 LLM 的 in-context reasoning（系统提示中明确的 CLARIFY → PLAN → ACT 规则和分解指令），不是"识别意图后匹配 skill"。Skill 只是辅助资源，需要模型自己判断并  read_file  
主动加载。真正的工作流编排发生在模型的 thinking 过程中，由模型自己决定用哪条路径。
