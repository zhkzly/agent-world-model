# Invocation control-plane recovery redesign — design

## 1. 目标、边界与已证实事实

引入一个统一的 **Invocation Control Plane（ICP）**，包裹现有
`InvocationBackend`。它只负责一次真实调用的物理生命周期：准入、可安全记录的
lifecycle、取消、已声明物理 wall 的执行、终态归一化、恢复和重试/回退的证据路由。

它不拥有业务语义。节点叶子仍拥有冻结 Prompt/input 投影、Runtime Skill、语义校验和
语义修复简报；`WorkRuntime` + Repair/Budget ledger 仍是唯一可以授权下一逻辑尝试的
组件。这不是用更硬的输出合同替代 Agent，也不是重写 WorldSpec、Candidate 或 Judge。

本重构满足 backend spec 对控制面重构的证据门槛：已有两个独立真实 Codex 坏例。

| 真实坏例 | 实际边界 | 已证实 | 未证实、不可据此修改 |
| --- | --- | --- | --- |
| CandidateBuild infrastructure retry | Scheduler → Builder → `CodexSdkBackend` → worker/app-server | 启动后约 26 秒停止安全 telemetry；worker/app-server 活过冻结 900s 物理 wall；无候选写入、无终态；正常中断后 Work head 仍为 `running` | Builder Prompt、Runtime Skill 或候选语义有错 |
| `codex_challenger_solver` audit | `RoutedInvocationBackend` → 同一 Codex worker/app-server 族 | 出现同样 local-wait / 无可用传输 / audit 状态永久 `running` | Candidate workspace 特有问题 |
| 已关闭 provider 失败 | CandidateBuild terminal-feedback diagnostic | `internalServerError` 曾明确表示临时 Provider 容量，应走不同 policy | 无进度 worker 等于 Provider 容量 |
| sandboxed live-agent orphan | `InvocationControlStore.reconcile_owner_loss` → host PID namespace | 已结束的 sandbox owner 留下 `owner_pid=5`；仅以数值 PID 探测会被宿主同号进程误判为活着。随后真实 Grok 调用有 14 次 Provider progress 并正常 completed | Grok 路由不可用，或 Candidate Prompt/Skill 有错 |
| 已终态 Verifier batch | frozen graph test guard | 精确 closure 已有 terminal evidence，guard 正确拒绝重复调用 | 此次 ICP 改动已被证明 |

前两个坏例首先支持 **adapter / worker lifecycle / owner settlement /
observability** 归因，削弱 Prompt/input、Runtime Skill、Candidate workspace 作为第一改动
方向。Grok 非法结构化输出、物理输出上限、provider 暂时容量是不同终态，不能统一叫 retry。

## 2. 当前责任分裂与根因

| 当前位置 | 已有优点 | 暴露出的缺口 |
| --- | --- | --- |
| `agent_world/invocation/codex_sdk.py` | 隔离 worker、进程组清理、父侧 deadline、terminal result | 只把 worker stdout 的 SDK notification 当 progress；没有安全的 worker spawn/payload/app-server/thread/turn/local-wait/cleanup lifecycle，真实 over-wall 未收敛为 terminal |
| `direct_llm.py` | 有 local heartbeat，且不伪装成 Provider progress | 协议是 adapter 内部实现，Codex 没有共同接口 |
| `routing.py` | 单一 transport 路由与并发准入 | 没有 durable physical attempt、settlement 或 policy owner |
| `work_runtime.py:357` | `reconcile_abandoned_operation` 能写完整 OperationRun → ValidationReport → FeedbackEvaluation | 主要由下一次 `DirectWorkRunner` 启动时调用（`direct_runner.py:997`），被中断的 test/audit 当下仍可永久 running |
| `SchedulerLeafExecutor` | 捕获普通 `CancelledError` 并终态化 | 当前 tests 只证明同一 Python task 的 cancel，不证明 CLI/worker/app-server 跨进程信号 |
| `WorkScheduler.dispatch_one` | 先打开 durable WorkAttempt 再调用 leaf | 只显式收口 `BudgetExceeded`，缺少统一、shielded 的 owner-loss/cancellation 收口 |
| `control/test_node.py` | 有 `_settle_cancelled_diagnostic_dispatch` | 真实 PTY/worker 证明它不能是唯一收口者 |
| `invocation/audit.py` | 启动时写安全 current/run record | cancellation re-raise 后只关闭 telemetry，audit JSON 没有非-running 终态 |
| Builder / legacy Designer / Judge loops | 各自能翻译领域结果 | timeout、retry、session、cancel 逻辑散落，形成多个物理调用控制面 |

根因不是“少一个 60 秒超时”。源文档明确禁止把 first-progress/first-write 变成任意短
death clock。缺的是：

1. 已声明的物理 wall 必须对活着但无终态的 worker/app-server 真正可执行；
2. 外部取消/owner loss 必须走幂等终态化；
3. local lifecycle 必须可见、但绝不能冒充 Provider progress；
4. 所有 caller 先获得同一种可归因 terminal fact，再决定 Prompt、Skill、code、feedback、
   repair、retry 或 fallback。

## 3. 目标架构

~~~mermaid
flowchart LR
  N["Node leaf / Builder / Judge / Audit"] --> O["Invocation ownership<br/>Operation 或诊断 lane"]
  O --> I["Invocation Control Plane<br/>lifecycle + classify + settle"]
  I --> R["Transport router"]
  R --> C["Codex SDK worker adapter"]
  R --> D["Direct LLM adapter"]
  C --> L["safe lifecycle sink"]
  D --> L
  L --> T["Telemetry + compact scene"]
  L --> S["Durable Invocation Control Store"]
  I --> P["Policy decision"]
  P --> W["WorkRuntime / RepairLedger<br/>唯一的新尝试授权"]
  W --> F["recipient-specific feedback"]
~~~

### 3.1 API 与 ownership

`InvocationControlPlane` 实现既有 `InvocationBackend` protocol，并包裹
`RoutedInvocationBackend`；`app.py` 只在 composition root 构造一次。业务代码永远拿到
ICP，而不是裸 Codex/Direct adapter。

增加只对控制面可见的 typed `InvocationOwnership`：

~~~text
owner_kind: work_operation | diagnostic_audit | standalone_component
owner_id / operation_run_id: opaque stable identifiers
scope/run/coordinate: only safe hashes or IDs
envelope_digest: declared turn/session/wall envelope
settlement_capability: work_runtime | audit_record | component_result
~~~

它不是 Prompt，不进入 provider request、普通 Artifact、模型 feedback 或 private session。
`InvocationRequest.metadata` 仍只是兼容性的观测信息，不能成为 retry authority。

对应的 `InvocationLifecycleSink` 有两条严格不同的流：

~~~text
local(phase, closed safe counters)
provider_progress(activity class only)
terminal(classification, safe code)
~~~

### 3.2 Durable physical-attempt state

新增与 `WorkControlStore` 并列的原子 `InvocationControlStore`。它是 live recovery
事实，不是语义 Artifact，也不保存 transcript。每一个 physical invocation 有一条
redacted record：

~~~text
queued → admitted → profile_verified
      → worker_spawned / direct_dispatched
      → local_waiting
      → provider_progress*                 # 仅真实 Provider event
      → terminal_received | cancel_requested | declared_wall_expired | owner_lost
      → cleanup_running → settled
~~~

record 只含：哈希 identity/owner/profile/route、当前 phase、时间、是否有真实 Provider
progress、最近 local heartbeat、envelope digest、closed terminal code、最终 Work/audit
projection pointer。禁止 Prompt/response、endpoint/credential、thread id、SQLite path、
workspace private state。

Linux owner 另外记录一个不可逆的 process-birth digest（boot id、PID 和 `/proc` start
ticks 的哈希），而不是把 PID 当作身份。reconciliation 只有在当前 digest 完全匹配时才
保留 active；无该字段的旧记录保守收敛为 `owner_process_interrupted`，因为它们不能证明
当前的同号 PID 就是原 owner。

transition 使用 CAS 并幂等：Ctrl-C、worker exit、wall expiry、恢复扫描竞态时只会有一个
settlement winner；其余读到同一 terminal record，不制造第二次 retry 或第二次预算消费。

### 3.3 Adapter lifecycle 和 declared wall

两个 transport 保留自己的协议，但都向 ICP 发送同一类本地事实：

| Adapter | 必须产生的 local 事实 | Provider progress 的唯一来源 |
| --- | --- | --- |
| Codex | worker spawned、payload written、`sdk_session_open`、`thread_start/resume`、`turn_start`、`turn_stream`、parent waiting、worker exit、cleanup outcome | 已校验 worker SDK event |
| Direct | request dispatched、await response、stream opened、await event、client close outcome | Provider stream event |

Codex worker wire protocol 增加有界的 lifecycle message type，和现有 event/terminal message
分开。parent 负责验证/脱敏后转发。不得含 raw SDK notification、Provider 文本、私有路径、
凭据。

一个父侧 monotonic supervisor 拥有 profile 已声明的 physical wall。到期时记录
`declared_wall_expired`，请求 cancel/terminate 进程组，在声明 grace 内等待 cleanup，
即使子进程不配合也返回 typed terminal。它不是新建的短 no-progress deadline；无 Provider
event 只是 observation，真正终态权威仍是已声明 wall 或 owner interruption。

### 3.4 一次 settlement，而非“下次再恢复”

Work leaf 在跨调用前，把 active `OperationRun.dispatch_id` 绑定到一个 ownership。正常
返回仍由 leaf 做 typed parsing 与 semantic validation；但在 cancellation、wall expiry、
worker 消失或 owner loss 时，ICP 在 shielded、bounded transaction 中：

1. 原子把 physical attempt 标成 terminal；
2. 调用 owner settlement capability；
3. 对 Work owner，复用 `WorkRuntime.reconcile_abandoned_operation` 的正常
   OperationRun → ProposalExecution → ValidationReport → FeedbackEvaluation 链，保守记
   unknown usage 并遵守 replay/repair policy；
4. 把 final Work/audit status 写回 control record；
5. 只有 policy 明确禁止 continuation 时才清理 private session state。

`WorkScheduler.dispatch_one`、`DirectWorkRunner`、全部 diagnostic runner 和 CLI
command boundary 都调用同一个 `ensure_settled(owner)`。原有启动时 scan 仍保留为第二道
恢复，不再是唯一可见收口。

`invocation-audit` 新增 `interrupted` 终态和每 lane 的 terminal classification。Ctrl-C
必须写非-running compact report 和 run-specific 安全 record；不得把取消伪装成 success 或 retry。

### 3.4.1 工作流恢复不是“从头换模型”

模型 fallback 的边界是 **当前失败 Work node**，不是整个 GenerateJob，也不是此前已经
commit 的 Agent 对话。对一个当前节点的临时容量失败，顺序固定为：

```text
已提交上游 WorkCommit / Artifact closure
        ↓（精确复用，绝不重跑）
当前节点：同模型、fresh node-local session、一次记录的 retry
        ↓（同一 classified transient 再次失败）
当前节点：下一兼容模型的新 diagnostic definition
        ↓
同一 immutable parent closure → parse/validate → 当前节点自己的 terminal/commit
```

因此“fresh session”只意味着不复用一个可能残缺、不可证明的 **失败节点会话**；不意味着
丢弃上游结果或重做全图。上游输出已经是带 provenance 的 typed Artifact，会被下游的精确
input closure 投影进新的调用。不同节点/角色不共享 ambient conversation，因为那会跨越
profile、workspace、capability 和 frozen disclosure 边界。

唯一例外是同一 logical node 收到精确 output-ceiling terminal、私有 continuation store 与
WorkDefinition 都明确授权的情况；那是受约束的 same-node continuation，不是跨节点 session
复用。

另有一个比 session continuation 更窄的 **CandidateBuild private workspace recovery**：若一个
已 settled 的 closed transient Provider/transport terminal 后，Builder leaf 能证明同一隔离
workspace 已有真实、常规文件活动但没有 `CandidateCompletion`/manifest/commit，则它可把既有的
一项 same-model infrastructure retry 改为“新 thread + 原 private workspace”。旧 thread id
绝不恢复，draft 不是 Artifact、不是 snapshot、更不能成为 Integration 输入。新的 Engineer
必须把 `candidate/` 当作不可信且未完成的草稿，先核查 frozen `inputs/`、检查文件并运行聚焦
public checks，再保留、重写或补齐它；只有完整 replacement `CandidateCompletion` 通过通常的
workspace validator 和 immutable commit 后才成为 Candidate。该路径不额外增加 retry 预算，且
不能跨越到 model fallback；同类别失败再次发生时 fallback 从空工作区开始。换言之，任何未
commit 的 workspace 结果都不能被 **adopt**，但可在同一路由的新会话中作为待审查的本地草稿。

### 3.5 显式归因和 policy route

每个 uncertain result 必须在五个 lens 上标记 `supported / weakened / unknown`：

1. project-execution Agent view；
2. effective runtime Prompt/input；
3. Runtime Skill；
4. code/provider/profile/adapter；
5. feedback/observability。

`TerminalFact` 提供 first credible lens，但不把其他 lens 伪装成已排除。

| 证据 | 第一优先归因 | 默认允许的下一步 |
| --- | --- | --- |
| closed、明确 retryable 的 provider/transport terminal | provider route/profile availability | 在 route-liveness 检查与 ledger 授权后，一次 same-definition + same-model + fresh-session retry |
| 上述 terminal + Builder 已证明私有 Candidate draft 有文件活动 | provider route/profile availability；draft 仍未知 | 同一项 retry 可走 fresh-session workspace recovery；新 Agent 检查/测试/完成，普通 validator 决定是否 commit |
| declared wall expiry、cleanup failure、owner loss、stale running record | adapter/supervisor/recovery code + observation | 先 reconcile；没有 terminal fact 前不自动 retry |
| 非法 JSON/envelope/结构化 shape | Prompt/input、Skill、response mode/profile、adapter/parser、feedback 都仍是候选 | 全量审计同类 surface 后，按证据选 regenerate、format repair、profile/adapter 改动或 feedback 改善；禁止盲 retry |
| 已解析 proposal 违反少量精确语义规则 | Prompt/input + Skill + semantic validator/feedback | 有精确反馈和 authority 才发 bounded correction；否则先做有因果改动的 regeneration |
| framework ID/order/wrapper/serialization/lease 错 | deterministic code | code fix + true boundary proof，不叫模型猜机械项 |
| scene 不足以区分原因 | feedback/observability | 先修 recipient-specific observation，不能据此改 Prompt/Skill |
| auth/capability/config/route incompatible | config/permission/human policy | fail closed / needs_human，不秘密换模型 |

### 3.6 Retry、continuation、semantic repair、fallback 分开

- **Infrastructure retry**：明确 closed retryable transport/provider terminal；同 immutable
  input、同模型、fresh node-local session、一次 recorded backoff + ledger action；失败结果
  保留 lineage。
- **Workspace recovery**：仅 CandidateBuild、仅上一个 infrastructure retry 的同一预算、仅
  leaf 已验证的 private draft。它新建 Provider thread，不复用旧 session，不把 draft 放进
  Artifact/feedback/Integration，并要求完整 CandidateCompletion 的正常验证/commit。fallback
  不接收该 draft。
- **Session continuation**：精确 output-ceiling terminal + 已有 private continuation store +
  WorkDefinition authority；不是泛用 retry。
- **Semantic repair**：已解析候选 + precise feedback + repair authority；runtime Agent 只接收
  它可用的 correction brief，不能看到 adapter/timeout/authorization 内部事实。
- **Regeneration**：由已证实的 Prompt/input/Skill/profile 因果改动触发，生成新的 immutable
  definition。
- **Model fallback**：前一路由已有 classified terminal 后，创建显式、可见的新 diagnostic
  definition；冻结同一语义 closure，记录改变的 model/profile/transport，且绝不沿用失败
  node-local session。一个同模型 retry 仍得到相同 classified transient route failure 后，
  controller 自动 dispatch 下一兼容模型的该 definition；它只重跑当前 node，并精确复用已
  commit parent closure。偏好顺序是：兼容时 Grok，随后 `gpt-5.3-codex-spark`，
  `gpt-5.4-mini`。兼容性需要对 execution mode/capability/output transport 证明；新定义
  不能直接宣称 normal commit，必须通过自己的 parse/validation boundary。

### 3.7 Feedback 与 project Agent view

| Recipient | 接收 | 禁止接收 |
| --- | --- | --- |
| project-execution Code Agent | 紧凑 scene：coordinate/lane、phase、elapsed/envelope、真实 Provider progress、有无 local heartbeat、terminal class、五 lens、精确 source 路径、唯一下一步 | Prompt/response、credentials、endpoint、private session/worker path |
| Control Plane | owner、lease、replay/idempotency、terminal fact、retry/continuation authorization | 伪造 semantic correction |
| runtime role Agent | 仅在获授权时接收 bounded semantic correction brief | adapter/provider/timeout/authorization/raw diagnostic |
| Human | 权限、配置、release 或 fallback 的真实决策 | 噪声和秘密材料 |

Agent view 是两层：紧凑 current index/scene + 可按需读取的相对/绝对路径。它不是 runtime
Agent Prompt，也不是权限或累积 transcript。ICP 只增加安全 pointer/summary，不把所有
lifecycle event 堆进 `index.md`。

## 4. Caller migration inventory

| Caller | 当前行为 | 目标 |
| --- | --- | --- |
| `designer/one_shot.py` | 单一 Scheduler proposal，后续 parse/validate | bind active OperationRun ownership；生命周期走 ICP，语义校验仍在 leaf |
| `builder/service.py` | workspace heartbeat + 直接 backend invoke + session state | ICP 拥有物理 lifecycle/cancel/terminal；Builder 保留 candidate workspace evidence |
| `judge/compiler.py` | local structured retry/correction loop | retry mechanics 迁入 policy/RepairAuthority；保留 verifier semantic diagnostic |
| `judge/reachability.py` | multi-turn solver/session loop | 每 physical solver turn 有 owner；Judge 保留 action/episode semantics |
| `designer/service.py` legacy loops | 组件内 timeout/retry/session | 迁到同一 policy 或退休，不能继续双重 retry authority |
| `invocation/audit.py`、`doctor.py` | standalone invoke/current JSON | 使用 standalone owner 和 guaranteed terminal report |
| `test_node.py`、`DirectWorkRunner`、CLI | 各自 cancel/recovery helper | 共用 settlement/recovery entry；保留 diagnostic-only/no-retry 限制 |
| `app.py` | 构造 router 后下发 services | 构造 transports → router → ICP；任何 service 不拿 raw adapter |

## 5. 真实证明顺序

已经有 terminal evidence 的 WorldRules、Verifier、plan 等语义节点不重跑。核心改变后，只证明
**改变的物理机制**，之后才重试当前真正 blocked 的 CandidateBuild。

1. 新的构造真边界：真实 `CodexSdkBackend` parent-worker subprocess，对受控 blocking worker
   fixture 运行。fixture 的小 wall 是它自己的 declared physical envelope，不是生产隐藏 cap。
   验证进程组 cleanup、typed terminal、非-running control record、没有伪造 Provider progress。
2. 新的跨进程 cancellation：以真实子进程运行 diagnostic test-node/audit + 同一 blocking worker；
   正常发送 interruption，再独立读取 Work head/audit JSON。必须只产生一个 terminal
   operation/evaluation、无 unauthorized retry、无 private data。
3. Direct/Codex fixture proof 可以在彼此 profile/state/lease 完全隔离时并行；这是机制并行，
   不是为了重复语义节点。
4. fixture 通过后，选择一个尚未 terminal-captured 的最窄 real live mechanism，一次即可；保留
   configured envelope，先读 safe scene。
5. 增加一个构造的真实 Scheduler/Builder boundary：第一 physical turn 在私有 Candidate
   workspace 写入部分常规文件后返回 closed retryable Provider terminal；控制面只能授权既有
   infrastructure retry，第二 turn 必须是新 session、同一受验证 workspace、完整
   CandidateCompletion → validator → commit。断言旧 thread 未恢复、draft 未成为 Artifact、同类
   第二失败只会进入 fallback 且 fallback 不看到 draft。
6. 之后才对 exact frozen CandidateBuild 做一次真实尝试。CandidateBuild commit 后，Integration 和
   后续 DAG 才按依赖启动；若 CandidateBuild transient retry/fallback，只重启它自身并复用
   已 commit 的 Design、BuildImplementationPlan 与其他精确 parent closure。只有真正独立的
   ready nodes 才并行。

pytest/type/lint/format/scene assertion 都是补充，不替代上述真实边界。

## 6. 安全、兼容和回滚

- immutable closure、capability profiles、budget/repair ledger、validation strictness、
  diagnostic-only marking、release authority 不变。
- private Codex SQLite/session 仍私有；只有 explicit continuation policy 才能保留，不写进
  control store/Artifact。
- 新 store redact-before-write；unsafe string field 直接拒绝，不试图保存 provider detail。
- migration 可按 caller gated，但对于已迁移 caller 没有第二条生产 success path。
- rollback 只能在 active ownership 已 settlement 后关闭 gate；不能删除 state、忽略 running
  record 或把 unknown consumption 当免费重放。

## 7. Acceptance mapping

- AC1：第 1–3 节给出边界、state machine、policy owner 和 bad-case 因果。
- AC2：第 4–5 节列出 caller、已证明节点和 dependency gate。
- AC3/AC4：第 5.1/5.2 是真实进程级 liveness/cancellation proof。
- AC5：第 3.5/3.6 区分 transient、output ceiling、格式、语义与 feedback-incomplete。
- AC6：第 5 节把 real boundary 放在 pytest 之前。
- AC7：第 3.7 保持 project Agent view 紧凑且与 runtime Agent 分离。
- AC8：第 3.2/3.3/6 的 redaction/private-state 约束。
