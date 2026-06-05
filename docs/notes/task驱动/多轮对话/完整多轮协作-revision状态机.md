# DeerFlow 多轮协作二期 - Revision 状态机

> 这份文档只讨论 `revision` 的生命周期，不讨论 thread 容器、不讨论前端布局，也不讨论旧 `ThreadRunQueue` 兼容策略。
> 目标是把“一个 revision 在什么状态下能做什么、会被什么事件推进到下一状态、哪些转换是禁止的”讲清楚，方便后续落代码。

---

## 1. 为什么要单独定义 revision 状态机

完整二期里，真正参与执行、恢复、审批、注入、被 supersede 的对象不是 `thread`，也不是模糊的“run”，而是：

```text
revision
```

如果这里的状态定义不清楚，后续代码会出现三类典型错误：

1. 前端把一个已经被 supersede 的 revision 当成当前活跃对象继续操作
2. 后端允许一个不该恢复的 revision 继续 resume
3. inject / approval / cancel 这些动作命中错误对象，导致状态串线

所以这份状态机不是文档装饰，而是运行时约束。

---

## 2. 状态设计原则

### 2.1 一个状态只表达一个事实

不要用一个字段同时混合：

- 是否正在执行
- 是否在等用户
- 是否还是当前活跃版本
- 是否在前台展示

这里先只定义“revision 的执行生命周期状态”。

前后台展示和优先级属于另一维，后续可以用独立字段表达：

```text
foreground / background / hidden
```

### 2.2 `superseded` 不是 `paused`

两者都“不在继续跑”，但语义完全不同：

- `paused`: 这个 revision 仍可能恢复
- `superseded`: 这个 revision 已经被新 revision 接管，不能再作为主执行链恢复

如果把这两个状态混成一个，后续代码一定会放错权限。

### 2.3 审批等待是一等状态

`awaiting_action` 不能复用 `paused`。

原因是：

- `paused` 是系统/用户主动暂停
- `awaiting_action` 是执行到明确决策门，需要用户给出 approve / reject / redirect

这决定前端展示不同，后端允许的动作也不同。

---

## 3. revision 状态枚举

建议的 revision 生命周期状态如下：

```text
pending
running
awaiting_action
paused
superseded
completed
cancelled
error
```

### 3.1 pending

含义：

- revision 已创建
- 还未真正占用 worker 开始执行

典型来源：

- create root run 后新建首个 revision
- inject 后创建新 revision，但尚未被 scheduler 拉起
- resume 请求已被接受，但尚未真正恢复执行

### 3.2 running

含义：

- revision 正在执行
- 可能正在模型推理、工具执行、checkpoint 写入、事件流发布

这是“活跃执行”状态，不表示它一定是 foreground，只表示它在跑。

### 3.3 awaiting_action

含义：

- revision 执行到明确的用户决策门前暂停
- 当前需要用户 approve / reject / redirect

典型来源：

- 危险工具调用前
- 需要明确人工确认的操作前

### 3.4 paused

含义：

- revision 被主动暂停
- 没有进入终态
- 后续允许恢复

典型来源：

- 用户主动暂停当前任务
- 调度器为了资源策略临时冻结

### 3.5 superseded

含义：

- 这个 revision 已被新 revision 接管
- 它不是当前有效执行版本
- 不应再被直接 resume 到主执行链

典型来源：

- inject 产生新 revision
- redirect 逻辑转为 fork 模式

### 3.6 completed

含义：

- revision 正常执行结束
- 进入终态

### 3.7 cancelled

含义：

- revision 被用户或系统明确取消
- 进入终态

### 3.8 error

含义：

- revision 因异常失败
- 进入终态

---

## 4. 状态机总图

```text
                    +----------------+
                    |    pending     |
                    +----------------+
                             |
                             | scheduler starts execution
                             v
                    +----------------+
                    |    running     |
                    +----------------+
                     |      |      |
                     |      |      |
                     |      |      +------------------------------+
                     |      |                                     |
                     |      | tool approval required              | unrecoverable failure
                     |      v                                     v
                     |  +-------------------+              +---------------+
                     |  | awaiting_action   |              |     error     |
                     |  +-------------------+              +---------------+
                     |      |         |
                     |      |         |
                     |      |         +------------------------------+
                     |      |                                        |
                     |      | redirect / inject creates new revision  | cancel
                     |      v                                        v
                     |  +-------------------+                  +---------------+
                     |  |   superseded      |                  |   cancelled   |
                     |  +-------------------+                  +---------------+
                     |
                     | pause
                     v
              +---------------+
              |    paused     |
              +---------------+
                     |
                     | resume
                     v
              +---------------+
              |    running    |
              +---------------+
                     |
                     | normal completion
                     v
              +---------------+
              |   completed   |
              +---------------+
```

这张图强调的是：

- `superseded` 是单向状态
- `awaiting_action` 和 `paused` 不是一回事
- `completed / cancelled / error` 都是终态

---

## 5. 合法状态转换

### 5.1 `pending -> running`

触发条件：

- scheduler 为该 revision 分配执行资源

说明：

- 这是 revision 真正进入运行时的起点

### 5.2 `running -> awaiting_action`

触发条件：

- 命中需要审批的工具调用
- 命中明确用户决策门

说明：

- 必须伴随 checkpoint 持久化
- 必须发布可被前端消费的审批事件

### 5.3 `awaiting_action -> running`

触发条件：

- 用户 approve
- 或后端将某些 resume 命令标准化为继续执行

说明：

- 必须从原 revision checkpoint 恢复

### 5.4 `awaiting_action -> superseded`

触发条件：

- 用户 reject + redirect
- 用户 inject 新意图并要求改计划

说明：

- 这里不应该原地改写旧 revision
- 正确动作是：创建新 revision，并把旧 revision 置为 `superseded`

### 5.5 `running -> paused`

触发条件：

- 用户主动暂停
- 调度器主动挂起

说明：

- 这是可恢复状态

### 5.6 `paused -> running`

触发条件：

- 用户 resume
- 调度器恢复执行

### 5.7 `running -> completed`

触发条件：

- revision 正常完成

说明：

- 这是成功终态

### 5.8 `running -> cancelled`

触发条件：

- 用户 cancel
- 系统强制停止

### 5.9 `awaiting_action -> cancelled`

触发条件：

- 用户在审批卡片上直接取消该任务

### 5.10 `paused -> cancelled`

触发条件：

- 用户不再恢复，直接终止任务

### 5.11 `running / awaiting_action / paused -> error`

触发条件：

- checkpoint 恢复失败
- tool / worker / runtime 异常
- 内部状态不一致

说明：

- 一旦进 `error`，该 revision 进入终态

---

## 6. 禁止状态转换

下面这些转换建议直接禁止，并在服务层返回明确错误。

### 6.1 `superseded -> running`

原因：

- superseded 说明这个 revision 已被新 revision 接管
- 再恢复会制造“双活”或时间线错乱

正确做法：

- 如果真要回退，也应通过显式“基于旧 revision 再 fork 一个新 revision”完成

### 6.2 `completed -> running`

原因：

- completed 是终态

正确做法：

- 如需继续任务，应创建新 revision 或新 root run

### 6.3 `cancelled -> running`

原因：

- cancelled 表示用户已明确终止

### 6.4 `error -> running`

原因：

- error 终态不能被静默恢复

正确做法：

- 需要显式重试路径，并通常通过新 revision 表达

### 6.5 `awaiting_action -> paused`

默认不推荐支持。

原因：

- 语义混淆：到底是“等待明确审批”，还是“普通暂停”

建议：

- 要么仍保持 `awaiting_action`
- 要么用户显式 cancel / redirect

---

## 7. 动作与状态的映射

### 7.1 approve

前置状态：

- `awaiting_action`

结果：

- `awaiting_action -> running`

### 7.2 reject

前置状态：

- `awaiting_action`

结果建议二选一：

- 如果 reject 等价于终止该路径：`awaiting_action -> cancelled`
- 如果 reject 同时给出新方向：旧 revision `-> superseded`，并创建新 revision

### 7.3 inject

前置状态：

- `running`
- `awaiting_action`
- `paused`

结果：

- 不原地修改旧 revision
- 创建新 revision
- 旧 revision 进入 `superseded`

### 7.4 pause

前置状态：

- `running`

结果：

- `running -> paused`

### 7.5 resume

前置状态：

- `paused`
- `awaiting_action`（语义上更接近 continue / approve）

结果：

- `-> running`

### 7.6 cancel

前置状态：

- `pending`
- `running`
- `awaiting_action`
- `paused`

结果：

- `-> cancelled`

---

## 8. 和前后台状态的关系

虽然这份文档不负责定义前后台状态机，但代码里要注意两个维度不要混淆。

例如：

```text
revision_status = running
visibility_state = background
```

这是合法的，表示：

- revision 确实在执行
- 但它不是当前前台主交互对象

同理：

```text
revision_status = awaiting_action
visibility_state = foreground
```

表示：

- 当前正等待用户处理审批卡片
- 这仍是用户眼前的主任务

不要尝试用单一状态枚举同时表达这两件事。

---

## 9. 后端落代码建议

### 9.1 服务层守卫

所有动作在真正执行前，都应先检查 revision 当前状态是否合法。

例如：

- `resume` 只能命中 `paused` / `awaiting_action`
- `inject` 不能命中 `completed` / `cancelled` / `error` / `superseded`
- `approve` 只能命中 `awaiting_action`

### 9.2 registry 负责状态变更事实

不要让：

- worker 改一部分状态
- scheduler 改另一部分状态
- router 再偷偷改一部分状态

建议统一由 registry / run manager 层收口合法状态转换。

### 9.3 前端只消费明确状态，不猜测

前端不要再根据：

- 有没有 token 在流动
- 当前 thread 是否 loading

去猜当前对象状态。

应该直接消费 revision 状态。

---

## 10. 一句话总结

revision 状态机最重要的三条纪律是：

1. `awaiting_action`、`paused`、`superseded` 必须分开
2. `superseded` 之后不能直接回到 `running`
3. `inject` 不是原地改旧 revision，而是创建新 revision

只要这三条守住，后续 approval、resume、inject、foreground/background 这几条复杂链路就有机会在代码里收敛，而不是互相踩状态。