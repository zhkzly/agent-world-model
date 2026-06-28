# Goal 12: Request-Driven Environment Generation Pipeline

当前实现状态：已接入两条 request-driven probe path。`run_request_driven_pipeline()` / `request_driven_node_registry()` 会从 booking/ticket/reservation raw_request 生成 `booking-service-lite`，也会从 library/book/loan/borrow/return/fine raw_request 生成 `library-lending-lite`。两条路径都会自动推进 `DomainPlan`、`StrategySelection`、source packet discovery、source-grounded S0-S11、generated backend/runtime bundle、framework-owned independent verifier、bounded repair 和 package release。这不是通用任意领域生成，也不是 live crawler/trainer 集成。

阅读方式：本文前半保留 Goal 12 的目标和验收要求，顶部“当前实现状态”和末尾“完成后的真实状态”记录已经完成的事实。Goal 12 的核心不是新增 booking 脚本，而是让用户输入环境需求后，系统自动选择/构造领域流水线并发布可执行环境包。

订票服务只是第一条验收输入，不是 Goal 12 的架构目标。图书馆借阅管理是第二条 request-driven 探针，用来验证新场景文本不会继续落回旧领域。Goal 12 不能通过新增一个手动调用的领域 registry 然后生成第三个 fixture 来完成。

## 背景

当前项目已经能完整跑通 `support-desk-lite` 和 `project-board-lite`。`project-board-lite` 覆盖了 generated bundle、code agent runner contract、package 内 runtime index、framework-owned independent verifier 和 bounded repair loop。

但实测仍存在核心缺口：

```text
raw_request = "Generate a booking service environment..."
selected registry = project_board_lite_node_registry()
actual release.environment_id = "project-board-lite"
```

这说明 `raw_request` 目前只是进入 `NeedSpec.goal`，不会驱动领域选择、source planning、knowledge extraction、task/verifier synthesis、implementation strategy 或 independent verifier strategy。

Goal 12 要修正的是“请求驱动流水线缺失”，不是“仓库里缺一个 booking fixture”。

## 目标

输入可以只有自然语言需求：

```text
生成一个订票服务环境，支持演出/航班/活动查询、座位余量、座位暂占、预订确认、支付状态、取消和退款/释放座位等流程。
```

系统应通过通用请求驱动路径输出：

```text
release.environment_id = booking-service-lite
envpkg/
  release/
  runtime/generated/<bundle-id>/
  spec/
  checks/
```

这里的可执行环境包必须包含 generated backend/runtime code，而不是只生成 specs。第一版通过 package 内 `runtime/generated/<bundle-id>/runtime.py`、`seed_state.json`、`verifier.py`、`surface_descriptor.json`、`check_replay.py` 和 `build_manifest.yaml` 表达。后续训练、部署、verl/GRPO 采样或 SFT 数据生产都应消费这个 release/package 入口；训练结果反向驱动环境迭代属于后续 loop，不是 Goal 12 验收项。

并完整通过：

```text
raw_request
-> request/domain planner
-> strategy selector
-> S0 NeedSpec
-> S1 SourceEvidenceIndex
-> S2 KnowledgePack
-> S3 EnvironmentSpec
-> S4 LogicalToolGraph
-> S5 TaskSet
-> S6 SurfacePlan
-> S7 VerifierPlan
-> S8 FeasibilityReport
-> S9 ImplementationRequest
-> IMPLEMENT
-> framework-owned independent verifier
-> bounded repair when needed
-> S10 EnvironmentPackagePlan
-> S11 ReleaseManifest
-> packaged runtime check
```

## 完整执行过程要求

Goal 12 的重点是端到端执行过程，不是断续的阶段 demo。

运行语义必须是无人参与 loop：

- 用户只在运行前提供 `raw_request`、配置、凭证引用、预算和权限策略。
- 运行中不能请求人工选择 registry、source、strategy、verifier 或 repair 方案。
- planner/selector/source/codegen/verifier 都必须由代码、配置和 agent backend 自动推进。
- 如果信息不足，pipeline 应自动尝试允许的 discovery/retry；仍不足时写 terminal failed/blocked artifact，而不是等待人工确认。
- 人类 review 可以作为运行后的审计记录，但不能是 success path 的必要步骤。

每个阶段必须满足：

- 输入来自上游 artifact refs，而不是重新读取 prompt 或领域常量。
- 输出写入 `ArtifactStore`，并记录 `produced_by`、`consumed_inputs`、source refs、hash/trace refs。
- 下游阶段只能基于已落盘 artifact、source evidence、failure packet 或 review record 推进。
- gate record 必须说明通过/失败基于哪些 artifact。
- release manifest 必须能追溯到 raw request、domain plan、source evidence、task/verifier plan、implementation request、generated bundle 和 independent verifier records。

典型数据流应类似：

```text
raw_request
-> DomainPlan
-> SourcePlan / SourceEvidenceIndex
-> KnowledgePack
-> EnvironmentSpec
-> LogicalToolGraph
-> TaskSet
-> SurfacePlan
-> VerifierPlan
-> FeasibilityReport
-> ImplementationRequest
-> GeneratedEnvironmentBundle candidate
-> BuildCheckReplayEvidence
-> IndependentVerificationReport
-> EnvironmentPackagePlan
-> ReleaseManifest
```

禁止把某阶段做成“看 raw_request 后硬编码返回完整 booking artifacts”。如果 S3-S7 没有消费 S1/S2 的 artifact refs，或者 IMPLEMENT 没有消费 S9 的 `ImplementationRequest`，或者 independent verifier 没有消费 S5/S7/S10 的任务和 verifier/package artifacts，该 Goal 不能算完成。

## 反馈回环要求

Goal 12 需要明确的、有界反馈边：

- source evidence 不足：生成 source failure packet，回到 source planning/discovery；达到上限仍不足时写 terminal failed/blocked artifact。
- extraction/synthesis 缺少状态对象、操作或 verifier refs：生成 synthesis failure packet，回到 S1/S2 或 planner。
- feasibility 不通过：生成 feasibility failure packet，不进入 IMPLEMENT。
- implementation/check/verifier 失败：生成 implementation failure packet，进入 Goal 11 的 bounded repair loop。
- repair 达到上限仍失败：run 失败，不生成 S10/S11 release。

所有回环都必须由 framework 控制。LLM/agent 可以作为节点产生候选、分析失败或写代码，但不能自己决定跳过 gate、改写历史 artifact 或直接发布 release，也不能把“等待人类决定”作为正常执行路径。

## 必须实现

### 1. Request / Domain Planner

新增显式 planner 节点或等价 artifact-producing 组件，从 `PipelineRunConfig.raw_request` 生成结构化 domain plan。

第一版至少要识别：

- booking / ticket / reservation / seat / payment / cancel 等订票服务意图。
- domain seed，例如 `booking-service-lite`。
- domain intent。
- required state objects。
- required operations。
- likely source needs。
- constraints、license/auth/network/security notes。

planner 输出必须落盘，且被后续 S1-S11 引用。不能只把判断结果放在 prompt memory。

### 2. Strategy Selector

新增 request-driven registry/strategy selector。

selector 的职责不是让 agent 任意控制流程，而是在 deterministic framework 下根据 planner artifact 选择或构造可执行节点策略：

- source discovery strategy。
- knowledge extraction strategy。
- synthesis strategy。
- implementation/code-agent strategy。
- independent verifier strategy。
- package/check strategy。

验收重点：用户只提供 `raw_request` 时，系统必须走 selector 路径；不能由调用方手动选择 `project_board_lite_node_registry()` 或新增 `booking_service_lite_node_registry()` 来绕过。

### 3. Source Planning / Discovery

第一版可以不做真实网络搜索，但必须通过 workflow 节点产生可追踪 source evidence。

允许的第一版 source：

- source planner 生成最小 PRD/schema/CLI/API source packet，并写入 artifact store。
- 本地生成或本地发现的 source packet，但必须作为 `SourceEvidenceIndex` 的 source refs 出现。
- 真实本地 PRD、schema、CLI help、API notes 等。

必须记录：

- `source_kind`。
- source path/uri/ref。
- hash。
- license/auth/network/security note。
- evidence refs。

不允许：

- 只在 prompt 中描述订票服务，不落盘 source evidence。
- 直接复制 `project-board-lite` artifacts 改名。
- source evidence 与后续 `KnowledgePack` / `TaskSet` / `VerifierPlan` 脱节。

### 4. Extraction And Synthesis Strategy

Goal 12 不要求一次支持任意所有领域，但要把领域逻辑放进可替换策略，而不是散落成第三个手写 fixture。

至少应从 source evidence 生成：

- `KnowledgePack`
- `EnvironmentSpec`
- `LogicalToolGraph`
- `TaskSet`
- `SurfacePlan`
- `VerifierPlan`
- `FeasibilityReport`
- `ImplementationRequest`

订票服务作为验收案例时，至少应产生 3 个任务：

- 查询活动/演出并确认座位后完成预订。
- 取消已有预订并释放座位。
- 只读查询剩余座位或价格/可用性。

每个任务必须有：

- natural request。
- dependency path。
- expected state delta 或 expected answer。
- verifier refs。
- positive/negative verifier evidence。

### 5. Implementation / Code-Agent Strategy

IMPLEMENT 必须根据 `ImplementationRequest` 写出 generated bundle：

```text
runtime.py
seed_state.json
verifier.py
surface_descriptor.json
check_replay.py
build_manifest.yaml
```

这些文件共同构成当前环境的最小后端/runtime 代码包：`runtime.py` 承载状态转移和 tool 行为，`seed_state.json` 承载可 reset 的初始状态，`verifier.py` 承载 deterministic task verifier，`check_replay.py` 证明它们可执行，`build_manifest.yaml` 记录 bundle 布局、hash 和 replay contract。仅生成 `ImplementationRequest` 或几份 specs 不算完成环境生成。

实现可以使用：

- `code_agent_runner`
- `codex_cli_runner`
- `openai_codegen`
- deterministic fallback

但 deterministic fallback 只能作为可回归的保底路径；release known limits 必须说明它不是通用 code-agent 生成能力。真实 agent/codegen 调用仍必须通过 `AgentBackend` / `AgentInvocationRecord`，并受 isolated workdir、path/hash/security checks、build/check/replay gate 约束。

### 6. Independent Verifier Strategy

不能继续把 independent verifier 写死为 `project-board-lite`。

Goal 12 应提炼 verifier strategy 边界：

- 根据 release/task/verifier artifacts 选择 verifier strategy。
- 直接加载 generated `runtime.py` / `verifier.py` / `seed_state.json`。
- 对 accepted tasks 产生 positive/negative records。
- 不信任 generated `check_replay.py` 自报。
- forged success-only `check_replay.py` 必须失败。

第一版可以注册 booking 验收策略，但它必须通过 strategy interface 被调用，不能成为孤立 release gate。

### 7. Bounded Repair Loop

沿用 Goal 11 的 repair loop：

- implementation attempt 失败时写 failure packet。
- repair attempt 使用同一个 `AgentBackend`。
- repair input 包含 previous attempt、failure packet、相关 artifact refs。
- 受 `PipelineRunConfig.max_repair_attempts` / `AGENT_WORLD_MAX_REPAIR_ATTEMPTS` 控制。
- 到达上限仍失败时不进入 S10/S11。

## 验收标准

必须新增自动化测试证明：

1. 只传入 booking/ticket/reservation raw_request 时，系统通过 request planner/selector 路径运行。
2. `ReleaseManifest.environment_id == "booking-service-lite"`。
3. raw_request 为订票服务时不得发布 `project-board-lite`。
4. 生成的 package 位于 `output_dir/envpkg`。
5. package 内 runtime index 指向 generated bundle。
6. generated files 存在且 sha256 校验通过。
7. 至少 3 个 booking acceptance tasks 有 independent positive/negative task records。
8. forged success-only `check_replay.py` 不能通过 release。
9. bounded repair 成功路径有 attempt records 和 failure packet。
10. bounded repair 耗尽路径不生成 `ReleaseManifest`。
11. 旧 `support-desk-lite`、`project-board-lite` 和 `awm` CLI 回归不破坏。
12. 测试能区分“request-driven selector 自动选择 booking strategy”和“调用方手动选择 booking registry”。

## 不做

- 不接真实 trainer、verl、Ray、vLLM、SGLang 或 GPU。
- 不实现部署环境、policy rollout、SFT 数据生产、verl/GRPO 采样或训练结果反馈到环境生成的闭环。
- 不要求一次支持任意所有领域。
- 不做默认真实网络 crawler。
- 不把 booking service 做成绕开 S0-S11 的孤立 demo。
- 不允许输入订票服务但实际发布 `project-board-lite`。
- 不通过新增第三个手动 registry 来宣称 request-driven pipeline 已完成。
- 不让 agent 控制 pipeline 流程。

## 完成后的真实状态

Goal 12 完成后，可以声称：

- 项目具备 request-driven environment generation pipeline 的已注册探针路径。
- 用户只提供 booking raw_request 时，系统能通过 planner/selector/source/codegen/verifier/release 路径发布 `booking-service-lite` envpkg。
- 用户只提供 library lending raw_request 时，系统能通过同一路径发布 `library-lending-lite` envpkg。
- 订票服务和图书馆借阅管理是验收探针，用来证明 raw_request 能驱动领域选择和生成，而不是手动 fixture 调用。
- 发布产物包含可被 package-relative runtime index 加载的 generated backend/runtime files，并通过 generated check 与 framework independent verifier。

仍不能声称：

- 任意领域都能自动生成。
- 通用网络 discovery 已完成。
- 通用 verifier synthesis 已完成。
- 真实训练框架已接入。
- live Codex/Claude/mini-swe-agent 已成为默认测试依赖。
- 已经实现训练结果驱动环境迭代。
