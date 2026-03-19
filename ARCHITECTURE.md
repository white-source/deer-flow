# DeerFlow Architecture Analysis

A comprehensive guide to understanding DeerFlow's architectural design, system flows, and key design patterns.

---

## Table of Contents

1. [System Architecture Overview](#system-architecture-overview)
2. [Request/Response Flow](#requestresponse-flow)
3. [Architecture Layers](#architecture-layers)
4. [Core Components](#core-components)
5. [Design Patterns](#design-patterns)
6. [Design Principles](#design-principles)
7. [Key Abstractions](#key-abstractions)
8. [Extension Points](#extension-points)
9. [Configuration Strategy](#configuration-strategy)
10. [Thread & Memory Management](#thread--memory-management)

---

## System Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend Layer                            │
│  (Next.js 16 + React 19 + TypeScript)                           │
│  - UI Components & Pages                                         │
│  - LangGraph Client (WebSocket streaming)                        │
│  - State Management (threads, models, memories)                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            │ HTTP/WebSocket
                            │
┌───────────────────────────┴─────────────────────────────────────┐
│                     API Gateway Layer                            │
│  (FastAPI - port 8001)                                           │
│  - Models, Skills, MCP endpoints                                 │
│  - Custom agents CRUD                                            │
│  - Artifacts, Uploads, Memory                                    │
│  - Channel integrations (Feishu, Slack, Telegram)               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            │ HTTP Reverse Proxy
                            │
┌───────────────────────────┴─────────────────────────────────────┐
│                    nginx Reverse Proxy                           │
│  (Unified endpoint: localhost:2026)                              │
│  - Route /api → Gateway (8001)                                  │
│  - Route /api/runs → LangGraph Server (2024)                    │
│  - Static assets → Frontend (3000)                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                 ┌──────────┴──────────┐
                 │                     │
      ┌──────────▼────────┐  ┌────────▼──────────┐
      │  LangGraph Server │  │  LangGraph Client │
      │  (port 2024)      │  │  WebSocket Stream │
      │  - Agent Runtime  │  │  - Thread mgmt    │
      │  - Execution      │  │  - Message flow   │
      │                   │  │  - State sync     │
      └──────────┬────────┘  └───────────────────┘
                 │
      ┌──────────▼────────────────────┐
      │  DeerFlow Core (Python)        │
      │  - Lead Agent                  │
      │  - Middleware Chain            │
      │  - Tool Execution              │
      │  - Memory System               │
      │  - Sandbox Integration         │
      │  - Subagent Orchestration      │
      └──────────┬─────────────────────┘
                 │
      ┌──────────┴──────────┬──────────┬──────────┐
      │                     │          │          │
   ┌──▼──┐    ┌──────┐  ┌──▼──┐  ┌───▼──┐  (External)
   │LLMs │    │Tools │  │MCP  │  │Sandbox│  - OpenAI
   │     │    │      │  │Svrs │  │       │  - Anthropic
   └─────┘    └──────┘  └─────┘  └───────┘  - Doubao, etc.
```

### Multi-Layer Design

```
┌─────────────────────────────────────────┐
│  Presentation Layer (Frontend)          │
│  - React UI, routing, state management  │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  API Gateway Layer (FastAPI)            │
│  - REST endpoints, request handling     │
│  - Configuration exposure               │
│  - File management (artifacts, uploads) │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  Agent Execution Layer (LangGraph)      │
│  - Graph-based workflow                 │
│  - Middleware chain                     │
│  - State management                     │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  Tool & Sandbox Layer                   │
│  - Tool abstraction & execution         │
│  - Sandbox provider (local, docker)     │
│  - File system access                   │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  External Services & Integrations       │
│  - LLM APIs, MCP servers                │
│  - Container runtimes, IM channels      │
└─────────────────────────────────────────┘
```

---

## Request/Response Flow

### Complete User Message Flow (Happy Path)

#### 1. **Frontend → Message Submission**

```
User Input                    API Client (LangGraph SDK)
    │                                │
    └──→ Input Component           │
         │                          │
         ├─ Attach files (optional) │
         │                          │
         └─→ Workspace Page ────────┼──→ Stream Mode Handler
                                    │
                           createThread() or existing threadId
                                    │
                           runs.stream(threadId, assistantId, {
                             input: { messages: [...] },
                             config: { configurable: {...} },
                             streamMode: "updates"
                           })
                                    │
                           WebSocket Connection
                                    │
```

#### 2. **API Gateway (FastAPI - port 8001)**

The gateway receives requests and exposes several endpoints:

- **`GET /api/models`** → Returns available LLM configurations
- **`GET /api/mcp`** → Returns MCP server configurations  
- **`POST /api/uploads`** → Handles file uploads for threads
- **`GET /api/artifacts/{thread_id}`** → Returns generated artifacts
- **`POST /api/agents`** → Create custom agents with SOUL.md
- **`GET /api/memory`** → Retrieve global memory entries
- **`GET /api/skills`** → Returns enabled skills

**Key Pattern:** Gateway routes `/api/runs/*` requests to `/api/runs/*` via nginx reverse proxy (LangGraph Server).

#### 3. **nginx Reverse Proxy (port 2026)**

```
Client Request (localhost:2026)
    │
    ├─ /api → FastAPI Gateway (8001)
    │   - Models, Skills, MCP, Artifacts, etc.
    │
    ├─ /api/runs → LangGraph Server (2024)
    │   - Thread creation
    │   - Thread runs (streaming)
    │   - State fetching
    │
    └─ / → Frontend (3000)
        - Static assets
        - HTML, CSS, JS
```

#### 4. **LangGraph Server → Lead Agent Invocation**

```
LangGraph Server (port 2024)
    │
    └─→ langgraph.json Configuration
        {
          "graphs": {
            "lead_agent": "deerflow.agents:make_lead_agent"
          },
          "checkpointer": {...}
        }
        │
        └─→ make_lead_agent(config: RunnableConfig)
            │
            ├─ Parse configurable options:
            │  - model_name, thinking_enabled, is_plan_mode
            │  - subagent_enabled, max_concurrent_subagents
            │  - agent_name, reasoning_effort
            │
            ├─ Resolve model config:
            │  - Request override → Agent config → Global default
            │
            ├─ Load & initialize LLM:
            │  - Create chat model from config
            │  - Enable thinking/extended thinking if model supports
            │
            ├─ Build middleware chain:
            │  ├─ ThreadDataMiddleware (creates thread paths)
            │  ├─ UploadsMiddleware (processes uploaded files)
            │  ├─ SummarizationMiddleware (optional, reduces context)
            │  ├─ TodoListMiddleware (for plan mode)
            │  ├─ TitleMiddleware (generates conversation title)
            │  ├─ MemoryMiddleware (queues for long-term memory)
            │  ├─ ViewImageMiddleware (handles vision)
            │  ├─ DeferredToolFilterMiddleware (tool search)
            │  ├─ SubagentLimitMiddleware (limits concurrent tasks)
            │  ├─ LoopDetectionMiddleware (prevents tool loops)
            │  └─ ClarificationMiddleware (asks for clarification)
            │
            ├─ Get available tools:
            │  ├─ Config-based tools
            │  ├─ Built-in tools (ask_clarification, present_file, etc.)
            │  ├─ Subagent tools (if enabled)
            │  ├─ MCP tools (if configured)
            │  └─ Tool search (deferred loading)
            │
            ├─ Create agent:
            │  └─ create_agent(
            │       llm=model,
            │       tools=tools,
            │       prompt_template=prompt,
            │       middlewares=middleware_chain
            │     )
            │
            └─→ Return: Runnable agent graph
```

#### 5. **Lead Agent Execution (Core Loop)**

```
Agent Execution State Machine
    │
    ├─→ "agent" node (LLM + Tool Binding)
    │   │
    │   ├─ Middlewares run before_agent() hook
    │   │  - ThreadDataMiddleware: Create thread directories
    │   │  - UploadsMiddleware: Inject uploaded file content
    │   │  - Other preprocessing middlewares
    │   │
    │   ├─ LLM processes message history + context
    │   │  - System prompt with tool definitions
    │   │  - Conversation history
    │   │  - Available tools
    │   │
    │   ├─ LLM decides: respond or call tool(s)
    │   │  Response: Add AI message with content
    │   │  Tool calls: Add AI message with tool_calls
    │   │
    │   └─ Middlewares run after_agent() hook
    │      - Error handling middleware catches exceptions
    │
    ├─→ "tools" node (Tool Execution)
    │   │
    │   ├─ For each tool call:
    │   │  │
    │   │  ├─ Sandbox Middleware:
    │   │  │  ├─ Resolve tool type (local, container, external)
    │   │  │  ├─ Get/create sandbox instance
    │   │  │  └─ Execute in isolated environment
    │   │  │
    │   │  ├─ Tool Execution:
    │   │  │  ├─ execute_command(bash_command) → Sandbox
    │   │  │  ├─ read_file(path) → Sandbox
    │   │  │  ├─ write_file(path, content) → Sandbox
    │   │  │  └─ list_dir(path) → Sandbox
    │   │  │
    │   │  └─ Result: ToolMessage added to state
    │   │
    │   └─ Loop detection middleware checks for infinite loops
    │
    ├─→ Conditional routing:
    │   │
    │   ├─ If all tools executed successfully → back to "agent"
    │   ├─ If clarification requested → ask user
    │   ├─ If loop detected → terminate with error
    │   └─ If agent says DONE → exit
    │
    └─→ End: Add final message to state
```

#### 6. **Middleware Chain Architecture**

The middleware system follows the **Chain of Responsibility** pattern:

```
Before Agent Execution:
    │
    User Input State
    │
    ├─→ ThreadDataMiddleware.before_agent()
    │   └─ Compute/create thread workspace paths
    │
    ├─→ UploadsMiddleware.before_agent()
    │   └─ Inject uploaded file contents into messages
    │
    ├─→ SandboxMiddleware.before_agent()
    │   └─ Initialize sandbox for tool execution
    │
    ├─→ Other middlewares before_agent()
    │   └─ Preprocessing specific to middleware logic
    │
    └─→ LLM Agent Logic (process & produce response)
         │
         ├─→ ViewImageMiddleware.before_agent()
         │   └─ Inject image details if vision model
         │
         ├─→ ToolErrorHandlingMiddleware.before_agent()
         │   └─ Convert tool exceptions to ToolMessages
         │
         └─→ ClarificationMiddleware.before_agent()
             └─ Ask for missing required parameters

After Agent Execution:
    │
    Response State
    │
    ├─→ LoopDetectionMiddleware.after_agent()
    │   └─ Check for repetitive tool calls
    │
    ├─→ MemoryMiddleware.after_agent()
    │   └─ Queue conversation for memory update
    │
    └─→ Other middlewares after_agent()
        └─ Postprocessing & state modifications
```

#### 7. **State Flow Through ThreadState**

```
ThreadState (LangGraph state schema):
{
  "messages": [
    HumanMessage(...),
    AIMessage(...),           // With tool_calls
    ToolMessage(...),         // Tool execution results
    AIMessage(...)            // Final response
  ],
  
  "sandbox": {                // From SandboxState
    "sandbox_id": "unique_id"
  },
  
  "thread_data": {            // From ThreadDataState
    "workspace_path": "/base/threads/{thread_id}/user-data/workspace",
    "uploads_path": "/base/threads/{thread_id}/user-data/uploads",
    "outputs_path": "/base/threads/{thread_id}/user-data/outputs"
  },
  
  "title": "Generated conversation title",
  
  "artifacts": [              // Merged list
    "/path/to/generated/file1.py",
    "/path/to/generated/file2.md"
  ],
  
  "uploaded_files": [         // User uploads
    { "name": "data.csv", "path": "/uploads_path/data.csv" }
  ],
  
  "viewed_images": {          // Vision model outputs
    "/path/to/image.png": {
      "base64": "...",
      "mime_type": "image/png"
    }
  }
}
```

#### 8. **Response Streaming Back to Frontend**

```
LangGraph Server Streaming
    │
    ├─→ WebSocket: stream_mode="updates"
    │   ├─ Each delta event containing state updates
    │   ├─ Final event with complete state
    │   └─ Events streamed in real-time
    │
    ├─→ Frontend WebSocket Listener
    │   ├─ sanitizeRunStreamOptions() normalizes payload
    │   ├─ Update UI in real-time
    │   ├─ Render messages as they arrive
    │   ├─ Display tool calls & executions
    │   └─ Show artifacts as generated
    │
    └─→ Frontend State Management
        ├─ Update thread context
        ├─ Update message list
        ├─ Update artifacts list
        ├─ Persist to local storage
        └─ Render final UI state
```

---

## Architecture Layers

### 1. **Presentation Layer (Frontend)**

**Location:** `frontend/src/`

**Responsibility:** User interface and interaction management

**Key Components:**
- `app/` - Next.js pages and routing
  - `page.tsx` - Landing page
  - `workspace/` - Main application interface
  - `api/` - Server-side routes (auth, etc.)
- `components/` - Reusable React components
- `core/` - Application logic (not UI)
  - `api/` - LangGraph SDK client wrappers
  - `threads/` - Thread state & CRUD operations
  - `models/` - LLM model management
  - `messages/` - Message handling
  - `memory/` - Global memory UI
  - `tools/` - Tool gallery & management
  - `artifacts/` - Artifact viewer
  - `config/` - Frontend configuration

**Design Pattern:** **Model-View-ViewModel (MVVM)**
- Separation of UI (components) from logic (core)
- API client abstracts LangGraph communication

**Key Files:**
- `env.js` - Environment schema validation with runtime checks
- `core/api/api-client.ts` - LangGraph SDK wrapper with singleton pattern
- `core/api/stream-mode.ts` - WebSocket streaming compatibility layer

---

### 2. **API Gateway Layer (FastAPI)**

**Location:** `backend/app/gateway/`

**Responsibility:** Expose custom endpoints not handled by LangGraph

**Components:**
- `app.py` - FastAPI application factory
- `routers/` - Endpoint implementations
  - `models.py` - List available models
  - `mcp.py` - MCP server configuration
  - `memory.py` - Global memory access
  - `skills.py` - Skill management
  - `artifacts.py` - Artifact retrieval
  - `uploads.py` - File upload handling
  - `agents.py` - Custom agent CRUD (create, list, update, delete)
  - `suggestions.py` - Generate follow-up questions
  - `channels.py` - IM channel integrations

**Design Pattern:** **Facade Pattern**
- Exposes simplified API surface
- Hides complexity of underlying systems
- Handles cross-cutting concerns (configuration, file I/O)

**Key Features:**
```python
# Example: Custom agent CRUD
POST   /api/agents              # Create agent with SOUL.md
GET    /api/agents              # List all custom agents
GET    /api/agents/{name}       # Get agent + SOUL.md
PATCH  /api/agents/{name}       # Update agent config
DELETE /api/agents/{name}       # Delete agent
```

---

### 3. **Agent Execution Layer (LangGraph)**

**Location:** `backend/packages/harness/deerflow/agents/`

**Responsibility:** Graph-based agent execution with middleware pipeline

**Components:**
- `lead_agent/` - Main agent implementation
  - `agent.py` - `make_lead_agent()` factory
  - `prompt.py` - System prompt templates
- `middlewares/` - Pipeline of cross-cutting concerns
- `thread_state.py` - Typed state schema
- `checkpointer/` - Thread state persistence
- `memory/` - Long-term memory system

**Key Design:**
```
Agent = LLM + Tools + Prompt + Middlewares + State

make_lead_agent(config) → RunnableGraph
  ├─ Resolve model from config
  ├─ Build middleware chain (ordered)
  ├─ Load tools (config + builtin + MCP)
  ├─ Create chat model
  ├─ Build agent graph with nodes & edges
  └─ Return runnable LangGraph graph
```

**Graph Structure:**
```
Nodes:
  - "agent": LLM + tool binding
  - "tools": Tool executor

Edges:
  - "agent" → "tools" (if tool_calls)
  - "agent" → END (if no tool_calls)
  - "tools" → "agent" (loop until done)

Conditionals:
  - Check for clarification required
  - Check for loop detection
  - Route based on agent action
```

---

### 4. **Tool & Sandbox Layer**

**Location:** `backend/packages/harness/deerflow/{sandbox,tools}/`

**Responsibility:** Execute tools in isolated sandbox environments

**Components:**
- `sandbox/` - Sandbox abstraction & providers
  - `sandbox.py` - Abstract base class (interface)
  - `sandbox_provider.py` - Factory for sandbox instances
  - `local/` - Local shell execution
  - `middleware.py` - Sandbox integration middleware
- `tools/` - Tool management
  - `tools.py` - `get_available_tools()` loader
  - `builtins/` - Built-in tool implementations
    - `ask_clarification_tool` - Request user input
    - `present_file_tool` - Display file/artifact
    - `task_tool` - Invoke subagent
    - `view_image_tool` - Process images (vision models)
    - `tool_search.py` - Deferred tool loading

**Design Patterns:**

1. **Strategy Pattern** - Sandbox providers:
   ```python
   class Sandbox(ABC):
       @abstractmethod
       def execute_command(command: str) → str
       @abstractmethod
       def read_file(path: str) → str
       @abstractmethod
       def write_file(path: str, content: str) → None
       
   class LocalSandbox(Sandbox):
       # Execute in local shell
       
   class DockerSandbox(Sandbox):
       # Execute in container
   ```

2. **Factory Pattern** - Sandbox provider:
   ```python
   def get_sandbox(config: SandboxConfig) → Sandbox:
       if config.mode == "local":
           return LocalSandbox()
       elif config.mode == "docker":
           return DockerSandbox(image=config.docker.image)
   ```

3. **Proxy Pattern** - Tool wrapper:
   ```python
   Tool = Callable that wraps execute_command()
         with error handling & validation
   ```

---

### 5. **Configuration Layer**

**Location:** `backend/packages/harness/deerflow/config/`

**Responsibility:** Centralized configuration management

**Components:**
- `app_config.py` - Main application configuration
- `model_config.py` - LLM model definitions
- `tool_config.py` - Tool availability & grouping
- `sandbox_config.py` - Sandbox behavior
- `extensions_config.py` - MCP server configs
- `agents_config.py` - Custom agent configs
- `memory_config.py` - Long-term memory settings
- `skills_config.py` - Skill pack configuration
- `paths.py` - Directory structure management

**YAML Structure:**
```yaml
config_version: 2

models:
  - name: "gpt-4"
    use: "langchain_openai:ChatOpenAI"
    model: "gpt-4"
    api_key: "$OPENAI_API_KEY"
    supports_vision: true

sandbox:
  mode: "local"  # or "docker"
  docker:
    image: "sandbox-image:latest"

tools:
  - name: "python_repl"
    group: "execution"
    use: "deerflow.tools.builtins:python_repl"

extensions:
  mcp_servers:
    - name: "web-search"
      command: "npx"
      args: ["@modelcontextprotocol/server-web-search"]

memory:
  enabled: true
  backend: "sqlite"
  path: "./data/memory.db"

skills:
  packs:
    - name: "research"
      enabled: true
```

**Design Pattern:** **Singleton Pattern**
```python
_config_instance = None

def get_app_config() → AppConfig:
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig.from_file("config.yaml")
    return _config_instance
```

---

### 6. **Memory System**

**Location:** `backend/packages/harness/deerflow/agents/memory/`

**Responsibility:** Long-term conversation memory with summarization

**Components:**
- `memory.py` - Memory store interface
- `queue.py` - Asynchronous memory queue
- `updater.py` - Conversation summarizer
- `prompt.py` - Memory retrieval prompts

**Flow:**
```
Conversation
    │
    └─→ MemoryMiddleware.after_agent()
        │
        ├─ Filter messages (user + final AI only, no tool calls)
        ├─ Queue for memory update
        │
        └─→ Memory Queue (Debounced)
            │
            ├─ Batch multiple updates
            ├─ Summarize conversation sections
            │
            └─→ Memory Store
                ├─ Embeddings (for similarity search)
                └─ Summaries (for context injection)
```

**Retrieval in Next Turn:**
```
New Message
    │
    └─→ First message processing
        │
        ├─ Retrieve relevant memories (semantic search)
        ├─ Inject into system context
        │
        └─→ Agent processes enriched context
```

---

### 7. **MCP Integration Layer**

**Location:** `backend/packages/harness/deerflow/mcp/`

**Responsibility:** Model Context Protocol server integration

**Components:**
- `client.py` - MCP client factory
- `cache.py` - Tool caching strategy
- `tools.py` - MCP tool wrapping

**Design:**
```
MCP Servers (configured in config.yaml)
    │
    ├─→ MCP Client (langchain-mcp-adapters)
    │   └─ StdIO, HTTP, or SSE transport
    │
    ├─→ Tool Discovery
    │   └─ Call list_tools()
    │
    ├─→ Tool Caching
    │   └─ Cache in-memory for performance
    │
    └─→ Tool Invocation
        └─ Call_tool(tool_name, args)
```

---

## Core Components

### Lead Agent (`make_lead_agent`)

**Purpose:** Factory function that creates the main agent graph

**Inputs (RunnableConfig):**
```python
config = {
    "configurable": {
        "model_name": "gpt-4",           # LLM override
        "thinking_enabled": True,         # Extended thinking
        "reasoning_effort": "high",       # Claude thinking effort
        "is_plan_mode": False,           # TodoList middleware
        "subagent_enabled": False,       # Enable task tool
        "max_concurrent_subagents": 3,   # Parallel task limit
        "agent_name": "research-agent",  # Custom agent
    }
}
```

**Output:** `RunnableGraph` with:
- State schema (ThreadState)
- Model (LLM instance)
- Tools (function definitions)
- Middlewares (processing pipeline)
- Nodes & edges (graph structure)

### Middleware Chain

**Execution Order (Critical):**

1. **ThreadDataMiddleware** - Must be first (creates paths)
2. **UploadsMiddleware** - After ThreadDataMiddleware (uses paths)
3. **SandboxMiddleware** - Before tool execution
4. **DanglingToolCallMiddleware** - Patches missing tool responses
5. **SummarizationMiddleware** - Reduces context (optional)
6. **TodoListMiddleware** - Plan mode support (optional)
7. **TitleMiddleware** - Generate title after first message
8. **MemoryMiddleware** - After TitleMiddleware (uses title)
9. **ViewImageMiddleware** - For vision models
10. **DeferredToolFilterMiddleware** - Hide deferred tools
11. **SubagentLimitMiddleware** - Limit parallel subagents
12. **LoopDetectionMiddleware** - Detect infinite loops
13. **ClarificationMiddleware** - Must be last

**Each Middleware:**
- Implements `before_agent()` → Process state before LLM
- Implements `after_agent()` → Process state after LLM
- Operates on `ThreadState`
- Can modify messages, add metadata, or reject execution

### Tool System

**Tool Categories:**

1. **Built-in Tools** (always available):
   - `ask_clarification` - Ask user for missing info
   - `present_file` - Display file to user
   - `view_image` - Process image with vision model
   - `task` - Create subagent task (if enabled)

2. **Config Tools** (from `config.yaml`):
   ```yaml
   tools:
     - name: "python_repl"
       group: "execution"
       use: "module.path:function_name"
   ```

3. **MCP Tools** (from MCP servers):
   ```
   MCP Server → Tool Discovery → Wrapped as LangChain Tool
   ```

4. **Deferred Tools** (lazy-loaded with tool_search):
   ```
   Tool Search Tool → Load tools on-demand → Reduces context
   ```

### Sandbox System

**Modes:**

1. **Local Mode** (default):
   - Execute bash commands locally
   - Access to project workspace

2. **Docker Mode:**
   - Execute in container
   - Isolation & reproducibility
   - Configurable image

**Tool Execution in Sandbox:**
```python
# ALL tool execution routes through sandbox abstraction

result = sandbox.execute_command(
    "python /workspace/script.py"
)

content = sandbox.read_file(
    "/workspace/output.txt"
)

sandbox.write_file(
    "/workspace/new_file.txt",
    "content"
)
```

---

## Design Patterns

### 1. **Chain of Responsibility (Middleware)**

**Purpose:** Process requests through pipeline of handlers

**Implementation:**
```python
class Middleware(ABC):
    def before_agent(self, state, runtime) → state_update
    def after_agent(self, state, runtime) → state_update

middlewares = [
    ThreadDataMiddleware(),
    UploadsMiddleware(),
    SandboxMiddleware(),
    # ...
    ClarificationMiddleware()
]

# Each processes in order, passing result to next
```

**Benefits:**
- Easy to add/remove/reorder processing steps
- Each middleware is focused on one concern
- Composable and testable

**Example:** UploadsMiddleware injects file content into messages for downstream processing

### 2. **Strategy Pattern (Sandbox Providers)**

**Purpose:** Encapsulate interchangeable behaviors

**Implementation:**
```python
class Sandbox(ABC):
    @abstractmethod
    def execute_command(command) → str
    @abstractmethod
    def read_file(path) → str

class LocalSandbox(Sandbox):
    def execute_command(command) → str:
        return subprocess.run(command, shell=True)

class DockerSandbox(Sandbox):
    def execute_command(command) → str:
        return docker_client.container.run(image, command)

# Client code:
sandbox = SandboxProvider.get(config.sandbox.mode)
result = sandbox.execute_command("python main.py")
```

**Benefits:**
- Switch providers without changing client code
- Add new sandbox types without modifying existing ones

### 3. **Factory Pattern (Component Creation)**

**Instances:**

```python
# Lead Agent Factory
def make_lead_agent(config) → RunnableGraph:
    model = create_chat_model(model_name, thinking_enabled)
    tools = get_available_tools(groups)
    middlewares = _build_middlewares(config)
    return create_agent(model, tools, middlewares)

# Checkpointer Factory
def make_checkpointer() → BaseCheckpointSaver:
    if config.sqlite:
        return SqliteSaver(db_path)
    elif config.postgres:
        return PostgresSaver(connection_string)

# Sandbox Factory
def get_sandbox(config) → Sandbox:
    if config.mode == "local":
        return LocalSandbox()
    elif config.mode == "docker":
        return DockerSandbox(image=config.image)
```

**Benefits:**
- Centralized object creation
- Consistent initialization
- Easy to swap implementations

### 4. **Singleton Pattern (Global Configuration)**

**Instances:**
```python
_app_config_instance = None

def get_app_config() → AppConfig:
    global _app_config_instance
    if _app_config_instance is None:
        _app_config_instance = AppConfig.from_file()
    return _app_config_instance

# Always same instance across app
config = get_app_config()
config = get_app_config()  # Same object
```

**Benefits:**
- Global access without passing through layers
- Single source of truth for configuration

**Caution:** Can make testing harder → provide config_path override

### 5. **Adapter Pattern (Tool Wrapping)**

**Instance:** MCP tools wrapped as LangChain tools

```python
# MCP returns: {name, description, inputSchema}
# Adapter converts to LangChain StructuredTool

mcp_tool = {
    "name": "search_web",
    "description": "Search the web",
    "inputSchema": {...}
}

adapted_tool = StructuredTool(
    name=mcp_tool["name"],
    description=mcp_tool["description"],
    func=lambda **kwargs: mcp_client.call_tool(**kwargs),
    args_schema=JsonSchema(mcp_tool["inputSchema"])
)
```

**Benefits:**
- Use heterogeneous tool sources with unified interface
- Client code doesn't know about MCP specifics

### 6. **Proxy Pattern (Lazy Tool Loading)**

**Instance:** Tool Search with deferred registry

```python
class DeferredToolRegistry:
    _tools = {}
    
    def register(self, tool):
        self._tools[tool.name] = tool  # Not loaded yet
    
    def get_tool(name):
        if name not in _tools:
            raise ToolNotFound
        if not loaded:
            _tools[name] = load_tool(name)  # Load on demand
        return _tools[name]

# In agent: tool_search presents index to LLM
# LLM selects tool → Load only selected tools
```

**Benefits:**
- Reduce context token cost
- Load tools only when needed
- Support large tool libraries

### 7. **Observer Pattern (WebSocket Streaming)**

**Instance:** LangGraph → Frontend state updates

```
LangGraph Server emits state events
    ↓
    Event: {type: "updates", data: {...}}
    ↓
Frontend WebSocket Listener
    ├─ Parse event
    ├─ Update thread context
    └─ Re-render UI

Represents reactive dataflow
```

**Benefits:**
- Real-time UI updates
- Minimal latency
- Server can push changes

### 8. **State Machine Pattern (Agent Loop)**

**Instance:** Lead agent execution

```
States: "initial" | "agent" | "tools" | "done"

Transitions:
- "initial" → "agent"
- "agent" → {
    "tools" if tool_calls,
    "done" if no_tool_calls
  }
- "tools" → "agent"
- "agent" → "done" (exit signal)

Conditional edges check agent action
Edge conditions deterministically route flow
```

**Benefits:**
- Predictable execution paths
- Explicit state transitions
- Easy to reason about flow

---

## Design Principles

### 1. **Separation of Concerns**

**Principle:** Each component has one clear responsibility

**Examples:**

| Component | Responsibility |
|-----------|-----------------|
| Frontend | User interface & local state |
| Gateway | HTTP API & file management |
| Agent | Decision making & orchestration |
| Middleware | Cross-cutting concerns |
| Sandbox | Tool execution isolation |
| Config | Settings management |

**Application:** Threads never mix presentation & business logic

### 2. **Dependency Injection**

**Principle:** Pass dependencies rather than creating them

**Examples:**

```python
# ❌ Poor: Hard to test, tightly coupled
class Agent:
    def __init__(self):
        self.model = ChatOpenAI()  # Created internally
        self.tools = get_tools()

# ✅ Good: Flexible, testable
class Agent:
    def __init__(self, model, tools, config):
        self.model = model
        self.tools = tools
        self.config = config

# Usage:
model = ChatGPT()
tools = [...]
agent = Agent(model, tools, config)
```

**Benefit:** Easy to mock in tests, swap implementations

### 3. **Single Responsibility Principle (SOLID-S)**

**Principle:** Class should have only one reason to change

**Examples:**

- `ThreadDataMiddleware` - Only responsible for thread paths
- `SandboxMiddleware` - Only responsible for sandbox initialization
- `MemoryMiddleware` - Only responsible for memory queueing

**Violation Example:**
```python
# ❌ Too many responsibilities
class Agent:
    def execute(self):
        self.load_config()
        self.initialize_sandbox()
        self.load_tools()
        self.setup_memory()
        self.run_model()
        self.save_memory()

# ✅ Delegated to factories & middleware
agent = make_lead_agent(config)
agent.invoke()
```

### 4. **Open/Closed Principle (SOLID-O)**

**Principle:** Open for extension, closed for modification

**Examples:**

1. **Middleware System:**
   ```python
   # Can add new middleware without modifying agent
   middlewares.append(CustomMiddleware())
   # Agent is closed for modification but open for extension
   ```

2. **Sandbox Providers:**
   ```python
   # Can add DockerSandbox type without changing existing code
   class CustomSandbox(Sandbox):
       def execute_command(self, cmd):
           # Custom implementation
   ```

3. **Tool System:**
   ```python
   # Add tools via config, no code changes
   tools:
     - use: "custom_module:custom_tool"
   ```

### 5. **Liskov Substitution Principle (SOLID-L)**

**Principle:** Derived classes must be substitutable for base classes

**Example:**
```python
class Sandbox(ABC):
    def execute_command(self, cmd) → str

class LocalSandbox(Sandbox):
    def execute_command(self, cmd) → str:
        # LocalSandbox can replace Sandbox anywhere

class DockerSandbox(Sandbox):
    def execute_command(self, cmd) → str:
        # DockerSandbox can replace Sandbox anywhere

# Client code works with either:
def run_tool(sandbox: Sandbox, cmd: str):
    return sandbox.execute_command(cmd)

run_tool(LocalSandbox(), "python script.py")  # Works
run_tool(DockerSandbox(), "python script.py")  # Works
```

### 6. **Interface Segregation Principle (SOLID-I)**

**Principle:** Clients shouldn't depend on interfaces they don't use

**Example:**
```python
# ❌ Too broad
class FullToolInterface(ABC):
    def execute()
    def validate()
    def serialize()
    def log()
    
# Client needing only execute has unused methods

# ✅ Segregated
class ExecutableTool(ABC):
    @abstractmethod
    def execute(self, **kwargs) → str

# Each tool implements only what it needs
```

### 7. **Dependency Inversion Principle (SOLID-D)**

**Principle:** Depend on abstractions, not concretions

**Example:**
```python
# ❌ Depends on concrete class
def execute_in_sandbox(local_sandbox: LocalSandbox):
    return local_sandbox.execute_command("cmd")

# Client code tightly coupled to LocalSandbox implementation

# ✅ Depends on abstraction
def execute_in_sandbox(sandbox: Sandbox):
    return sandbox.execute_command("cmd")

# Client can pass any Sandbox implementation
```

### 8. **DRY - Don't Repeat Yourself**

**Examples:**

1. **Middleware Ordering** (documented in agent.py):
   - Comments explain exact ordering
   - No duplication of initialization logic

2. **Config Resolution** (model resolution):
   ```python
   # Single function handles all model resolution logic
   def _resolve_model_name(requested: str | None) → str:
       # Request override → Agent config → Global default
   ```

3. **Tool Loading** (get_available_tools):
   - Single source for tool gathering
   - Config tools + built-in tools + MCP tools
   - Deferred tool logic centralized

### 9. **YAGNI - You Aren't Gonna Need It**

**Examples:**

- **Minimal abstractions:** Sandbox abstraction only because multiple implementations exist
- **Optional middleware:** Summary, TodoList only when configured
- **Lazy initialization:** Thread directories created on-demand, not upfront
- **MCP tools cached:** Tools only loaded when MCP servers configured

### 10. **Tell, Don't Ask**

**Principle:** Objects should tell other objects what to do, not ask about their state

**Example:**
```python
# ❌ Asking (violates Tell Don't Ask)
if middleware.has_state(state):
    if middleware.should_process(state):
        result = middleware.process(state)

# ✅ Telling
result = middleware.before_agent(state, runtime)
# Middleware decides internally what to do

# Agent doesn't ask "do you need to run?"
# Agent tells "here's the state, process it"
```

---

## Key Abstractions

### 1. **ThreadState**

**Purpose:** Immutable state container for conversation thread

**Schema:**
```python
class ThreadState(TypedDict):
    # Inherited from AgentState
    messages: Annotated[list[BaseMessage], add_messages]
    
    # Extended state
    sandbox: ThreadDataMiddleware
    thread_data: ThreadDataState
    title: str | None
    artifacts: list[str]  # Merged from middleware
    uploaded_files: list[dict]
    viewed_images: dict[str, ViewedImageData]  # Vision outputs
```

**Design:** Read-only during execution; updated through reducer functions

```python
# Merge function for artifacts (deduplication)
def merge_artifacts(existing, new) → list[str]:
    if existing is None:
        return new or []
    if new is None:
        return existing
    return list(dict.fromkeys(existing + new))  # Dedupe
```

### 2. **AgentState (LangGraph)**

**Purpose:** Base schema for all agent states

**Includes:**
- `messages`: Conversation history (add_messages reducer)
- Custom fields via TypedDict extension

**Reducers:**
- `add_messages` - Append messages
- `merge_artifacts` - Merge & deduplicate
- `merge_viewed_images` - Merge vision outputs

### 3. **RunnableConfig**

**Purpose:** Configuration passed to agent at runtime

**Structure:**
```python
config: RunnableConfig = {
    "configurable": {
        "model_name": str | None,
        "thinking_enabled": bool,
        "reasoning_effort": str | None,
        "is_plan_mode": bool,
        "subagent_enabled": bool,
        "max_concurrent_subagents": int,
        "agent_name": str | None
    },
    "run_id": str,           # From LangGraph
    "thread_id": str,        # From LangGraph
}
```

**Purpose:** Runtime customization without config.yaml changes

### 4. **Sandbox (Abstract)**

**Purpose:** Execute tools in isolated environments

**Interface:**
```python
class Sandbox(ABC):
    def execute_command(cmd: str) → str
    def read_file(path: str) → str
    def list_dir(path: str, max_depth: int) → list[str]
    def write_file(path: str, content: str, append: bool) → None
    def update_file(path: str, content: bytes) → None
```

**Implementations:**
- `LocalSandbox` - Shell execution
- `DockerSandbox` - Container execution
- Extensible for custom providers

### 5. **AgentMiddleware (LangGraph)**

**Purpose:** Cross-cutting concerns in agent execution

**Interface:**
```python
class AgentMiddleware(Generic[StateT]):
    state_schema: Type[StateT]
    
    def before_agent(
        self, 
        state: StateT, 
        runtime: Runtime
    ) → dict | None:
        # Preprocess before LLM
        return state_updates
    
    def after_agent(
        self,
        state: StateT,
        runtime: Runtime
    ) → dict | None:
        # Postprocess after LLM
        return state_updates
```

**Benefits:**
- Orthogonal to main agent logic
- Composable & reorderable
- Easy to unit test

### 6. **AppConfig**

**Purpose:** Central configuration schema

**Source:** YAML file → Python objects → Pydantic validation

**Components:**
```python
class AppConfig(BaseModel):
    models: list[ModelConfig]
    sandbox: SandboxConfig
    tools: list[ToolConfig]
    tool_groups: list[ToolGroupConfig]
    skills: SkillsConfig
    extensions: ExtensionsConfig
    tool_search: ToolSearchConfig
    checkpointer: CheckpointerConfig | None
    memory: MemoryConfig
```

**Features:**
- Environment variable resolution: `api_key: $MY_KEY`
- Reflection-based object instantiation: `use: "module:class"`
- Validation with Pydantic
- Singleton access: `get_app_config()`

---

## Extension Points

### 1. **Custom Middleware**

**How to Add:**

```python
# File: backend/packages/harness/deerflow/agents/middlewares/custom_middleware.py

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

class CustomState(AgentState):
    custom_field: str | None

class CustomMiddleware(AgentMiddleware[CustomState]):
    state_schema = CustomState
    
    def before_agent(self, state: CustomState, runtime: Runtime) → dict | None:
        # Preprocess
        return {"custom_field": "value"}
    
    def after_agent(self, state: CustomState, runtime: Runtime) → dict | None:
        # Postprocess
        return {"custom_field": "updated"}
```

**Register in Agent:**

```python
# In backend/packages/harness/deerflow/agents/lead_agent/agent.py

from deerflow.agents.middlewares.custom_middleware import CustomMiddleware

# In _build_middlewares():
middlewares.append(CustomMiddleware())
```

**Considerations:**
- Ordering matters → document position in chain
- Implement state_schema for type safety
- Keep focused on one concern

### 2. **Custom Tool**

**How to Add:**

```python
# Option 1: Config-based tool
# In config.yaml:
tools:
  - name: "my_tool"
    group: "custom"
    use: "mymodule:my_tool_function"

# Option 2: Built-in tool
# File: backend/packages/harness/deerflow/tools/builtins/my_tool.py

from langchain.tools import Tool, tool

@tool
def my_tool(input: str) -> str:
    """Tool description for LLM."""
    return result

# Register in BUILTIN_TOOLS:
# backend/packages/harness/deerflow/tools/tools.py
BUILTIN_TOOLS = [
    present_file_tool,
    my_tool,  # Add here
    ...
]
```

**Discovery:**
- Config tools: Loaded via `get_available_tools()`
- MCP tools: Discovered from MCP servers
- Built-in: Always included (if enabled)

### 3. **Custom Sandbox Provider**

**How to Add:**

```python
# File: backend/packages/harness/deerflow/sandbox/custom/custom_sandbox.py

from deerflow.sandbox.sandbox import Sandbox

class CustomSandbox(Sandbox):
    def __init__(self, id: str, config: CustomSandboxConfig):
        super().__init__(id)
        self.config = config
    
    def execute_command(self, command: str) → str:
        # Custom implementation
        return output
    
    def read_file(self, path: str) → str:
        # Custom file reading
        return content
    
    # Implement other abstract methods...
```

**Register in Provider:**

```python
# In backend/packages/harness/deerflow/sandbox/sandbox_provider.py

def get_sandbox(sandbox_config: SandboxConfig) → Sandbox:
    if sandbox_config.mode == "local":
        return LocalSandbox(id=sandbox_config.id)
    elif sandbox_config.mode == "docker":
        return DockerSandbox(id=sandbox_config.id)
    elif sandbox_config.mode == "custom":
        return CustomSandbox(
            id=sandbox_config.id,
            config=sandbox_config.custom
        )
```

### 4. **Custom Model Provider**

**How to Add:**

```python
# Option: Use existing LangChain integration
# In config.yaml:
models:
  - name: "my-model"
    use: "langchain_provider:ChatMyModel"
    model: "model-name"
    api_key: "$MY_API_KEY"

# Option: Create custom wrapper
# File: backend/packages/harness/deerflow/models/custom_model.py

from langchain_core.language_models import BaseChatModel

class CustomChatModel(BaseChatModel):
    def _generate(self, messages, **kwargs) → ChatGeneration:
        # Custom generation logic
        pass
```

### 5. **Custom Agent Personality (SOUL.md)**

**How to Add:**

```bash
# Create via API:
curl -X POST http://localhost:2026/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "researcher",
    "description": "Specialized research agent",
    "model": "gpt-4",
    "tool_groups": ["research", "analysis"],
    "soul": "You are a research expert. Focus on..."
  }'

# Or create directory:
mkdir -p backend/data/agents/researcher
cat > backend/data/agents/researcher/SOUL.md << 'EOF'
# Researcher Agent

You are specialized in research...
EOF
```

**Agent-Specific Config:**

```python
# Use at runtime:
config = {
    "configurable": {
        "agent_name": "researcher",
        "is_bootstrap": False
    }
}

# Agent factory loads SOUL.md & applies config
```

### 6. **Custom API Endpoint**

**How to Add:**

```python
# File: backend/app/gateway/routers/custom.py

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["custom"])

@router.get("/custom-endpoint")
async def custom_endpoint():
    """Custom endpoint description."""
    return {"data": "value"}

# Register in gateway:
# File: backend/app/gateway/app.py

from app.gateway.routers import custom

def create_app() → FastAPI:
    app = FastAPI(...)
    
    # Register router
    app.include_router(custom.router)
    
    return app
```

### 7. **Custom Memory Backend**

**How to Add:**

```python
# Implement memory interface:
# backend/packages/harness/deerflow/agents/memory/custom_memory.py

class CustomMemoryStore:
    async def add_summary(self, thread_id: str, summary: str):
        # Store memory
        pass
    
    async def get_summaries(self, thread_id: str) → list[str]:
        # Retrieve memories
        return summaries

# Configure in config.yaml:
memory:
    enabled: true
    backend: "custom"
    backend_class: "deerflow.agents.memory.custom_memory:CustomMemoryStore"
```

---

## Configuration Strategy

### Config Resolution Priority

```
1. Environment Variables
   └─ Specified as: $VARIABLE_NAME
   
2. Runtime ConfigurableOptions
   └─ Passed in RunnableConfig.configurable
   
3. Custom Agent Config
   └─ Loaded from agents/{agent_name}/
   
4. Global Config (config.yaml)
   └─ Loaded at startup
   
5. Defaults
   └─ Hard-coded in schema
```

### Model Resolution Example

```python
def _resolve_model_name(requested_model_name: str | None) → str:
    app_config = get_app_config()
    default = app_config.models[0].name if app_config.models else None
    
    # Priority:
    if requested_model_name:  # Request override
        if config.get_model_config(requested_model_name):
            return requested_model_name
        # Invalid → fall through to default
    
    return default  # Global default
```

### Tool Resolution

```python
def get_available_tools(
    groups: list[str] | None = None,
    subagent_enabled: bool = False,
) → list[BaseTool]:
    config = get_app_config()
    
    # 1. Config tools (filtered by group)
    tools = [t for t in config.tools if not groups or t.group in groups]
    
    # 2. Built-in tools
    builtin = [
        ask_clarification_tool,
        present_file_tool,
    ]
    
    # 3. Subagent tools (if enabled)
    if subagent_enabled:
        builtin.append(task_tool)
    
    # 4. Vision tool (if model supports)
    if model_config.supports_vision:
        builtin.append(view_image_tool)
    
    # 5. MCP tools (if configured)
    mcp_tools = get_cached_mcp_tools() if mcp_enabled else []
    
    # 6. Tool search (if enabled, defers MCP tools)
    if config.tool_search.enabled:
        builtin.append(tool_search_tool)
    
    return config_tools + builtin + mcp_tools
```

---

## Thread & Memory Management

### Thread Lifecycle

```
1. Creation
   ├─ Frontend: Thread ID generated (UUID)
   ├─ LangGraph: Checkpointer saves initial state
   └─ Backend: Thread directory created on-demand
   
2. Message Exchange
   ├─ User message → Thread message list
   ├─ Agent processes → Multiple state updates
   ├─ Tools execute → Tool messages recorded
   └─ Final response → Complete state saved
   
3. Persistence
   ├─ Checkpointer (database or filesystem)
   ├─ Memory system (summaries for future threads)
   └─ Uploads/Artifacts (file system storage)
   
4. Closure
   ├─ User switches thread → State finalized
   ├─ Memory updated → Conversation summarized
   └─ Cleanup (optional) → Temporary files removed
```

### Memory Architecture

```
Conversation in Thread A
    │
    ├─→ MemoryMiddleware.after_agent()
    │   └─ Queue for memory update
    │
    └─→ Memory Queue (Debounced)
        │
        └─→ Memory Summarizer
            ├─ Extract key facts
            ├─ Summarize sections
            └─ Store embeddings
                │
                └─→ Memory Store (SQLite)

New Thread B (different agent)
    │
    └─→ Memory Retrieval
        ├─ Retrieve contextually relevant summaries
        ├─ From any thread in global memory
        └─ Inject into system context
```

### Checkpointer Strategy

**Purpose:** Save & restore thread state

**Implementation:**
```python
# Config:
checkpointer:
    use: "deerflow.agents.checkpointer:make_checkpointer"
    backend: "sqlite"
    path: "./data/threads"

# Or: PostgreSQL
checkpointer:
    backend: "postgres"
    connection_string: "$DATABASE_URL"

# Result:
Threads → Database
  ├─ All messages
  ├─ Full state
  └─ Timestamps for recovery
```

**Benefits:**
- Resume conversations
- Undo/replay capability
- Audit trail

---

## Summary: Architectural Insights

### Key Strengths

1. **Composable Middleware** - Cross-cutting concerns cleanly separated
2. **Tool Abstraction** - Support multiple tool sources (config, builtin, MCP)
3. **Configurable Everything** - YAML-driven, no code changes needed
4. **Sandbox Isolation** - Tool execution doesn't affect main system
5. **Streaming-First** - Real-time response to user
6. **Memory Persistence** - Long-term learning across threads
7. **Custom Agents** - Per-agent personality & configuration

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Middleware Chain | Orthogonal concerns, testable, composable |
| LangGraph | Native graph support, checkpointing, streaming |
| FastAPI Gateway | REST endpoints not handled by LangGraph Server |
| nginx Reverse Proxy | Unified endpoint, load balancing potential |
| Sandbox Abstraction | Support multiple execution environments |
| YAML Config | Non-technical users can configure |
| Singlet Config | Global access, consistent values |
| MCP Integration | Extensibility through standard protocol |

### Extensibility Model

DeerFlow is designed as a **plugin architecture**:

- **New Middleware** → Add to chain
- **New Tools** → Register in config or MCP server
- **New Models** → Add to config, use LangChain integration
- **New Sandbox** → Implement Sandbox interface
- **New API Endpoints** → Add FastAPI router
- **New Memory Backend** → Implement storage interface
- **Custom Agents** → Create with unique personality

All without modifying core code.

---

## Learning Resources

### Starting Points

1. **Request Flow:** Follow [Request/Response Flow](#requestresponse-flow) section
2. **Core Loop:** See [Agent Execution](#5-lead-agent-execution-core-loop)
3. **Middleware:** Read "middleware" comments in `lead_agent/agent.py`
4. **Config:** Study `config.example.yaml` documentation
5. **Testing:** Check `backend/tests/` for example usage

### Key Files to Study

| File | Purpose |
|------|---------|
| `backend/langgraph.json` | Graph entry point |
| `backend/app/gateway/app.py` | Gateway configuration |
| `backend/packages/harness/deerflow/agents/lead_agent/agent.py` | Agent construction |
| `backend/packages/harness/deerflow/config/app_config.py` | Configuration schema |
| `frontend/src/core/api/api-client.ts` | Frontend-backend communication |
| `config.example.yaml` | Configuration example |

### Commands for Exploration

```bash
# Start development environment
make dev

# Check configuration
cat config.yaml | head -50

# View logs
tail -f logs/gateway.log
tail -f logs/langgraph.log

# Test endpoint
curl http://localhost:2026/api/models | jq

# Review middleware ordering
grep -A 20 "ThreadDataMiddleware must be" backend/packages/harness/deerflow/agents/lead_agent/agent.py
```

---

**Document Version:** 1.0  
**Last Updated:** March 2026  
**Applies to:** DeerFlow 2.0+
