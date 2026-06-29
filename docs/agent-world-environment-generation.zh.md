# Agent World 环境生成任务定义

本文是当前任务源文档。若旧文档、旧实现、旧 goal 与本文冲突，以本文为准。

## 1. 用户真正要做什么

本项目要实现一个类似 Agent-World / AW 方向的 **环境生成系统**。

用户给系统一个输入，例如：

- 需要某类可训练环境。
- 某个模型能力不足，需要构造能训练或评估这个能力的环境。
- 基于某个行业、工具、PRD、repo、API、MCP server、CLI、网页服务或本地资料生成环境。

系统应自动推进环境生成，而不是让人手写一次性 prompt。目标输出不是一篇方案，而是可复现、可验证、可发布、可被训练/评估流程消费的环境包。

这里的环境包本质上是 **可执行后端/runtime 代码包**，而不是只落盘几份规格文件。它至少应逐步包含：状态转移逻辑、seed/state fixture、logical tool 到 concrete surface 的绑定、任务集合、deterministic verifier、check/replay 脚本、release metadata，以及后续 rollout/training/eval consumer 能稳定加载的入口。Codex、mini-swe-agent、OpenAI-compatible codegen 或其他 code agent 可以根据 source evidence 和 generated specs 写这些后端代码，但它们只能作为显式 implementation/repair 节点；是否可发布由框架侧 build/check/replay、independent verifier 和 bounded repair gate 决定。

## 2. AWM 的位置

AWM 只作为背景知识和可参考素材，不是本项目边界。

可以参考 AWM 的部分：

- code-driven environment generation。
- database/file-backed state transition。
- scenario / task / tool / verifier 的组合方式。
- execution feedback 用于修正环境代码和 verifier。
- 本地样本可作为 discovery source 或 fixture。

不能把 AWM 当成要求：

- 不能复现 AWM 论文作为主目标。
- 不能把 AWM JSONL、MCP 暴露形式或数据结构写死为通用格式。
- 不能假设所有环境都来自 AWM 样本。
- 不能让 AWM 的 MCP 形态限制 CLI、Python、HTTP 等 surface。

## 3. 推荐系统形态

不要先固定成“两条 loop”。更合理的设计是一个 **确定性环境生成工作流**，外加若干可选反馈边。

主路径：

```text
EnvironmentNeed / CapabilityGap / DomainSeed
  -> source discovery
  -> knowledge extraction
  -> environment specification
  -> tool dependency graph
  -> task generation
  -> surface planning
  -> verifier planning
  -> feasibility filtering
  -> implementation plan or code-agent request
  -> generated backend/runtime implementation and checks
  -> release package
  -> rollout/export/evaluation consumers
  -> failure analysis feedback
```

这条路径可以在后续形成循环，但第一性设计应是：

- 阶段可审计。
- artifact 明确。
- gate 明确。
- LLM/agent 只出现在显式节点。
- 失败可以回到上游某个阶段。
- 训练或评估只是消费发布后的环境，不反向污染环境合约。
- 后续可以形成部署、采样、SFT/GRPO/verl 消费、训练结果反馈到新环境构造的动态流程，但这些反馈必须作为新的显式 loop 或受控 feedback edge 表达，不能让 trainer 直接改写环境生成合约。

## 4. 核心模块

### 4.1 输入理解

把用户输入整理成结构化需求：

- 环境目标。
- 目标能力缺口。
- 任务类型。
- 预期 agent 行为。
- 约束：本地执行、网络、认证、许可证、安全边界、可 mock 范围。

这里可以用 LLM，但输出必须落到结构化 artifact。

### 4.2 Source Discovery

发现可用于生成环境的素材：

- MCP server。
- CLI help / man page。
- API docs / SDK docs。
- repo。
- PRD / 用户文档。
- 数据库 schema。
- 真实工具或服务。
- AWM 样本。

Source discovery 可以包含显式 research agent 节点。例如：为了判断某个 MCP server 是否适合作为 source 或 surface，可以调用 search agent、Codex SDK、Codex CLI、deep-search、mini-swe-agent 或其他 agent backend 去读取文档、探索 repo、检查 schema、运行受控探针。

这些调用必须是 workflow 的正式节点，而不是人工临时动作或隐藏 prompt：

- 通过统一 `AgentBackend` / `AgentInvocation` contract 调用。
- 记录输入 artifact、指令、权限、网络/认证需求、预算、输出 artifact、trace 和失败原因。
- 输出必须回写为 `SourceEvidenceIndex`、`KnowledgePack` 或 `ReviewRecord` 等可审计 artifact。
- Codex SDK 等只能是可替换 backend，不能成为核心框架依赖或唯一实现路径。

输出必须包含证据，而不是一句总结：

- source uri/path。
- source kind。
- version/hash。
- license/auth/network/security note。
- 可抽取的状态对象、工具、业务流程、可 mock 边界。
- 不确定点、自动解决候选、blocked 条件。

### 4.3 Knowledge Extraction

把 source evidence 变成可审计知识包：

- 工具/API/CLI/MCP schema。
- 状态对象。
- 状态转移约束。
- 可验证字段。
- 引用位置。
- 不确定点。

这不是 prompt 摘要，而是后续环境生成和 verifier 生成的输入。

### 4.4 Environment Specification

生成环境规格：

- domain。
- state backend：SQLite、文件、local service、mock API 等。
- state entities。
- logical tools。
- reset/isolation strategy。
- seed fixtures。
- 权限和安全边界。
- 可发布 surface：MCP / CLI / Python / HTTP。

注意：CLI 是环境可发布的一种 surface，不等于 harness 临时执行 shell 的 adapter。

### 4.5 Tool Dependency Graph

任务生成前必须知道工具依赖：

- 每个 tool 的 input schema、output schema、side effects、读写状态对象。
- 工具之间的依赖边：strong / weak / independent。
- 参数分类：external / internal / optional。

这部分可用 LLM 辅助判断，但必须可检查。

### 4.6 Task Generation

任务不是简单自然语言。每个任务候选至少应包含：

- natural user request。
- target capability。
- initial state requirements。
- expected state delta 或 expected answer。
- allowed logical tools。
- forbidden leakage：不能暴露 tool name、数据库字段、backend id。
- dependency path。
- difficulty metadata。
- verifier refs。

任务生成可以参考 Agent-World / EnvFactory 的思路：

- 从 tool graph 采样有效工具链。
- 改写成自然用户请求。
- 用 solver/filter 排除不可解、泄漏实现细节、无 verifier 的任务。

### 4.7 Surface Planning

同一个 logical tool 可以绑定多个 surface：

- MCP。
- CLI。
- Python callable。
- HTTP。

环境生成系统必须保持 logical tool 与 concrete surface 分离。第一版可以只实现一种 surface，但合约不能写死一种。

### 4.8 Verifier Planning

优先 deterministic verifier：

- 数据库状态检查。
- 文件状态检查。
- 命令退出码。
- 单元测试。
- API 状态检查。

LLM judge 只能作为辅助 verifier 或解释节点，必须有 evidence、rubric、model/version/budget，不能直接读取 runner 自评当 reward。

### 4.9 Feasibility Filtering

进入实现前必须检查：

- source evidence 是否足够。
- 是否可本地执行或可 mock。
- state backend 是否可 reset/isolate。
- tool graph 参数依赖是否可解。
- 至少一个 surface 是否可受控调用。
- verifier 是否可写且有正反例。
- 任务是否自然且可解。
- 权限、网络、license、安全边界是否可接受。

不通过时输出 failure class 和 recovery suggestion，而不是继续生成实现请求。

### 4.10 Implementation And Release

通过 feasibility 后，系统可以生成：

- environment blueprint。
- implementation request。
- runtime/backend code files。
- seed/state fixture。
- deterministic verifier。
- surface descriptor。
- check/replay script。
- expected package layout。
- TDD requirements。
- launch/check/replay commands。
- release manifest。

实现可以由 code agent 完成，但 Codex SDK、mini-swe-agent、deep-search 等只能是可替换后端，不能成为核心框架依赖。

只生成 `EnvironmentSpec`、`TaskSet`、`VerifierPlan` 或 `ImplementationRequest` 不等于环境已生成。进入 release 前，必须能从 generated files import 或 launch runtime，执行成功任务和负例 verifier，并把结果写入可审计记录。

## 5. 训练和评估的位置

训练不是当前系统的核心起点。环境生成出来后，训练/评估系统可以消费：

- environment release。
- task set。
- verifier specs。
- rollout traces。
- reward/eval records。
- export manifest。
- online runtime contract，用于需要在线采样的 RL trainer。

verl、LLaMA-Factory、OpenRLHF、TRL 或自定义训练框架都只是 consumer。环境生成框架不能绑定其中任何一个。

当前第二阶段 Goal 可以先基于硬编码 `support-desk-lite` 案例补齐训练/评估消费链路，见 `docs/goal-02-hardcoded-full-chain.zh.md`。这只表示先打通 release package -> rollout/eval -> reward records -> training export -> dataset-only consumer 的链路，不表示已经完成通用环境自动生成，也不表示要把真实训练框架接成核心依赖。

注意：GRPO/PPO 这类在线强化学习不是单纯读取离线 SFT JSONL。它们需要 trainer 在 rollout 阶段反复调用当前 policy，和环境交互，获得 observation、done、verifier reward，再做 advantage 和参数更新。因此环境 release 若要被 verl、verl-agent 或自定义 GRPO trainer 使用，必须额外暴露稳定的 online runtime contract：

```text
load package -> start runtime -> reset(task) -> step(action/tool_call)* -> finalize(answer) -> verifier reward
```

Goal 03 可以基于已发布的 `support-desk-lite` package 补齐这个 runtime/adapter contract，见 `docs/goal-03-online-runtime-grpo.zh.md`。这仍然不表示把 verl 作为核心依赖，也不表示实现真实 GPU 训练循环。

SFT 数据生产、verl/GRPO 在线采样、环境部署，以及“根据训练结果继续生成或修正环境”的外层闭环，都是后续动态流程。当前优先级是把 request -> source -> generated backend code -> verifier -> package/release 的前半段稳定跑通，并保留给训练消费的 artifact 和 runtime contract。

## 6. Loop Engineering 原则

这里的 loop engineering 不是必须写成两个固定 loop，而是以下原则：

- 主流程由代码、typed config 或显式 DAG 控制。
- LLM/agent 是节点，不是流程控制器。
- 所有中间状态落盘。
- 所有 gate 有可审查 evidence。
- 每次运行可观察、可复盘、可重放。
- 失败能回到明确阶段，而不是让模型自由决定下一跳。
- 成功路径必须无人参与；人只在运行前提供 raw request、配置、凭证引用、预算和权限策略，或在运行后审计 artifacts。运行中 source、权限、安全、产品语义无法自动解决时，pipeline 写 blocked artifact，而不是等待人工介入。
- Python 环境和验证命令默认使用 `uv`，例如 `uv run pytest ...`；不要在文档或脚本里默认要求手动 venv、conda 或裸 `python` 执行测试。

## 7. 当前不做

当前不应实现：

- `awmx` demo。
- 与环境合约混在一起的 scripted rollout / reward / export demo。若进入 `docs/goal-02-hardcoded-full-chain.zh.md`，可以作为 release package 的下游 consumer 实现最小 rollout/reward/training export 链路。
- MCP-only 或 CLI-only 环境。
- generic CLI adapter 当主线。
- 真实训练框架集成。若进入 `docs/goal-03-online-runtime-grpo.zh.md`，只能实现 trainer adapter contract、online runtime 和可选配置导出；不能把 verl、verl-agent、LLaMA-Factory、OpenRLHF 或 TRL 写成核心依赖。
- 把真实 Codex SDK / mini-swe-agent / deep-search 直接绑定进核心或作为唯一 agent backend。
- AWM 论文复现。
- 自动下载完整 AWM 1K。
- 无 verifier evidence 的 LLM judge。

## 7.1 当前阶段判断：打开流水线后的结构收敛

Goal 02-04 已经证明 `support-desk-lite` 这个硬编码 fixture 可以被 package、replay、rollout、online runtime、HTTP wrapper 和 environment CLI surface 消费。这个结果有价值，但它仍然不是通用环境生成。

当前阶段已经从“继续扩展 fixture runtime”切换为“打开真实生成流水线结构”。重点不是一次性实现万能 search 或万能 code generation，而是把下面几层明确拆开，使后续真实节点可以替换硬编码实现：

- pipeline orchestration：已由 `agent_world.pipeline` 负责 S0-S11 节点顺序、失败停止和 run record；后续仍需补更多恢复/反馈边。
- artifact store：已由 `agent_world.store.ArtifactStore` 负责 artifact、gate record、review record、agent invocation、trace 和 package refs 的本地目录落盘。
- node registry：已提供 `NodeRegistry` 和 support-desk-lite fixture node set；后续真实 node 可替换 fixture node。
- source connectors：已提供最小本地 connector，PRD、CLI help、schema-like 本地文件进入 `SourceEvidenceIndex`；真实网络 search 仍不是默认路径。
- knowledge extractors：已提供 support-desk-lite extractor，把 source evidence 转成带 source refs、hash、section refs 和不确定点的 `KnowledgePack`。
- synthesis nodes：support-desk-lite 的 `EnvironmentSpec`、`LogicalToolGraph`、`TaskSet`、`SurfacePlan` 和 `VerifierPlan` 已从 `KnowledgePack` 派生；当前不代表通用 synthesis。
- implementation/code-agent node：已在 S9 与 S10 之间增加 deterministic implementation、generated bundle implementation 和 agent-backed slot；agent path 通过 `AgentBackend` 写 `AgentInvocationRecord`。
- build/check/replay gate：deterministic implementation 需要通过本地 callable smoke 或 generated bundle check/replay evidence 后才进入 S10/S11；agent output 未通过 gate 不进入 release。
- release consumers：rollout、online runtime、training/eval export 是 release 的 consumer，不能反向污染生成 pipeline。

因此，下一条结构性 Goal 应该优先建立这些边界。`support-desk-lite` 可以继续作为 fixture node set 和回归测试，但不能继续代表通用 pipeline 本身。

## 7.2 当前阶段判断：第二个本地 Source Family

Goal 05 之后，最重要的风险不是缺少更多 runtime，而是 pipeline 结构仍可能只适配 `support-desk-lite`。Goal 06 已引入第二个本地 source family 来验证复用性。当前第二领域是 `project-board-lite`，输入素材为 CLI help + YAML schema + examples/rules。

推荐形态：

- 输入素材使用 CLI help + JSON/YAML schema + small examples，而不是另一个 PRD-only fixture。
- source connector 读取真实本地文件，保留 path/hash/line refs，并识别 CLI command、schema state object、business rule 和 example candidates。
- extractor 从 CLI commands、schema entities、examples/rules 中生成 `KnowledgePack`。
- node registry 复用 `PipelineRunner`、`ArtifactStore`、gate/review/invocation 机制。
- S3-S7 是第二领域的 deterministic synthesis，但从 `KnowledgePack` 派生，并且 source 缺失 command/schema/rule 时停止 release。
- implementation 当前在 `project-board-lite` 上已从 deterministic fixture runtime path 推进到 generated bundle path，并新增 agent-backed codegen path。两条路径都必须写出独立 runtime/verifier/seed/check files，并记录正反 verifier 的 build/check/replay evidence；agent-backed path 只有通过 path/hash/security checks 和同一 build/check/replay gate 后才能 release。

Goal 06 不证明“已经通用”。它只证明：同一 pipeline 结构可以承载第二种 source family，并把剩余领域专用逻辑暴露出来。

### 7.3 当前阶段判断：Generated Environment Bundle 已验证

Goal 07 已把 `project-board-lite` implementation 节点推进到 `GeneratedEnvironmentBundle`：通过 feasibility 后，deterministic implementation path 从 source-grounded artifacts 写出隔离 build directory，并从 generated files 运行 build/check/replay。该结果证明当前 pipeline 能把第二领域从 source evidence 推到 verified generated files，但仍不等于通用 agent code generation。

`GeneratedEnvironmentBundle` 应产出可复现执行产物，例如：

- runtime code files：定义 state backend、reset/isolation、logical tool 行为。
- verifier code/files：实现 deterministic verifier，含正反例。
- seed/state fixtures：可版本化，可 reset。
- surface descriptors：声明 Python callable、environment CLI、HTTP 或 MCP 中哪些 surface 已实现。
- launch/check/replay commands：说明如何从生成文件构造环境、调用 surface、运行 verifier。
- build manifest：记录 generated file paths、hashes、source artifact refs、implementation invocation refs、check results。

surface verification 规则：

- Python callable：必须从 generated module import 并执行 reset/tool/verifier。
- environment CLI：必须能从 generated command 或 module 执行 `--help` 和至少一个成功/失败任务命令，使用 `subprocess.run(argv, shell=False)`。
- HTTP：若标记 implemented，必须能启动本地服务并调用 health/reset/step/finalize 或 domain endpoints。
- MCP：若标记 implemented，必须能启动 server，完成 initialize/list_tools/call_tool，并运行 verifier。
- 未实现 surface 只能标记为 descriptor-only 或 deferred，不能算 verified。

进入 Generated Environment Bundle 阶段后，相关 release 必须引用 verified generated bundle。仅有 source evidence、spec、task、verifier plan 或 implementation request 不足以表示可执行环境已生成。

Goal 07 已基于 `project-board-lite` 完成 deterministic generated bundle 门槛，因为该领域已经有 CLI help、schema、examples、source-grounded `KnowledgePack` 和 pipeline registry。Goal 08 在同一领域补上 agent-backed path 和真实 `openai_codegen` backend：`openai_codegen` 调用 OpenAI-compatible chat-completions endpoint，接收模型返回的 bundle file contents，写入 isolated workdir。Goal 09 进一步补上真正 code agent runner path：pipeline 写入 `input/` workspace packet，外部 runner 在 `generated/` 写环境文件、运行 check，在 `agent-output/` 产出 manifest 和命令日志；框架只对 runner 生成的 `generated/` 执行 path/hash/security checks 和 build/check/replay。框架拒绝绝对路径、`..`、symlink escape、未声明文件、hash mismatch、fixture runtime import、secret leak 和 check failure，只有 verified bundle 才能进入 S10/S11。下一步应减少领域模板比例，让更通用的 planner/codegen strategy 生成 bundle；不应把该结果误判为第三领域、训练/runtime consumer 扩展、通用网络 search 或真实 trainer 集成。

### 7.4 当前阶段判断：Agent-backed Environment Codegen 已验证第一条路径

Goal 08 已证明当前 pipeline 能把 accepted `project-board-lite` artifacts 交给 codegen backend，由 backend 在 isolated workdir 写出可执行 bundle，并由 deterministic build/check/replay gate 放行。该结果分两层：`process_agent` helper 证明 adapter wiring；`openai_codegen` 证明真实 OpenAI-compatible model/file-content backend 通道。二者都仍不等于通用环境自动生成。

当前已验证的形态：

- code agent 是显式 workflow node，`node_purpose=implement`。
- 调用必须通过 `AgentBackend` / `AgentBackendConfig`，不能把 Codex SDK、mini-swe-agent、Claude Agent SDK、OpenAI-compatible API 或任何单一 runner 绑定进 core。
- 调用产生 `AgentInvocationRecord`，记录 backend kind、model/runtime、command/config ref、输入输出 artifact、权限、预算、timeout、trace、redaction 和失败原因。
- code agent 只能写本次 run 的 isolated workdir，不能直接修改 repo、release 目录、`.git`、`.codex`、用户 home 或未声明路径。
- 进入 bundle 前做 path normalization 和 security check，拒绝绝对路径、`..`、symlink escape、未声明文件、hash mismatch、fixture runtime import 和 secret 泄漏。
- agent-generated files 和 deterministic generated bundle 一样，通过 build/check/replay：从 generated runtime/verifier/check files import 或启动环境，执行成功任务和负例。
- agent output 未通过 build/check/replay、schema gate、review gate 和 release gate 前，不得生成 `ReleaseManifest`。

第一条 agent-backed codegen 使用 `project-board-lite`，因为其 source evidence、knowledge pack、tasks、verifier plan 和 deterministic bundle check 已经存在。默认测试使用 mock/process agent 验证 wiring，并使用本地 fake OpenAI-compatible endpoint 验证 `openai_codegen` HTTP/code-file protocol；真实外部模型调用只能作为显式 live smoke。

Goal 08 没有新增第三领域、真实 trainer、GPU/Ray/vLLM/SGLang、MCP 全量 server 或 generic shell executor。它只回答了一个问题：当前环境生成流水线可以把 accepted artifacts 交给 codegen backend，由 backend 写出可执行环境 bundle，并由 deterministic verifier 放行。下一步问题是降低 `project-board-lite` 领域专用模板比例，而不是继续扩 runtime/training consumer。

### 7.5 当前阶段判断：Code Agent Runner 已接入

Goal 09 纠正了一个关键概念：`openai_codegen` 是 LLM/file-content codegen，不是完整 code agent runner。真正的 runner 可以是 Codex CLI/SDK、Claude Code、mini-swe-agent 或自定义 SWE agent；它应接收 workspace packet，自己写文件、自己运行检查、根据失败修复或返回失败，再交给框架做最终 release gate。

当前已接入的 runner contract：

- `code_agent_runner`: 通用本地 runner 命令，通过 `AGENT_WORLD_CODE_AGENT_CMD` 配置，必须在 allowlist 中，使用 `subprocess.run(argv, shell=False)` 调用。
- `codex_cli_runner`: Codex CLI runner 适配器，要求命令显式声明安全的 approval/sandbox 参数，禁止危险 bypass 参数。
- workspace packet：`input/artifacts/*.json`、`input/implementation-brief.md`、`input/acceptance-checks.md`、`input/skills/environment-codegen.md`、`generated/`、`agent-output/`。
- runner 输出：`generated/runtime.py`、`seed_state.json`、`verifier.py`、`surface_descriptor.json`、`check_replay.py`、`build_manifest.yaml`，以及 `agent-output/candidate_manifest.json`。
- 可观测性：`AgentInvocationRecord` 记录 backend kind、runtime/command、输入 artifact、权限、预算、trace ref、evidence refs；`agent-output/runner-command-log.jsonl` 记录 runner 命令 stdout/stderr/exit code；runner 自己也可以写 `agent-output/*` trace。
- release 边界：`input/` 和 `agent-output/` 不进入 release；只有 manifest 指向的 `generated/` 被扫描、hash、验证和发布。

当前仍不是“live Codex/Claude 已默认跑通”。默认测试使用本地 runner fixture 验证 contract、workspace、command log 和 release gate；真实 Codex CLI、Claude Code 或 mini-swe-agent smoke 必须由显式 env/command/allowlist/network/auth 配置启用。Goal 11 已补上框架级 bounded repair loop：agent implementation 失败时 pipeline 会写 failure packet，在 `PipelineRunConfig.max_repair_attempts` / `AGENT_WORLD_MAX_REPAIR_ATTEMPTS` 范围内重新调用同一个 backend；达到上限仍失败时 fail，不进入 S10/S11。当前 runner 仍可以内部自修复，但不能控制 pipeline 流程。

### 7.6 当前阶段判断：Packaged Generated Runtime 已接入

Goal 10 解决“生成环境是否可以被之后环节调用”的工程化缺口。此前 verified `GeneratedEnvironmentBundle` 位于 build/workspace 目录，例如 `/tmp/.../agent-runs/.../generated`，release manifest 只能证明它已经生成并验证，但后续 rollout/training/online runtime consumer 缺少稳定 package 内入口。

当前成功 S11 后，如果存在 accepted `GeneratedEnvironmentBundle` 且配置了 `output_dir`，pipeline 会额外写：

```text
envpkg/
  release/
    release-manifest.yaml
    generated-runtime-index.yaml
  runtime/
    generated/<bundle_id>/
      runtime.py
      seed_state.json
      verifier.py
      surface_descriptor.json
      check_replay.py
      build_manifest.yaml
  checks/
    generated-bundle-package-check.yaml
```

后续模块应读取 `envpkg/release/generated-runtime-index.yaml`，其中包含：

- `runtime_dir_ref`
- `runtime_entrypoint`
- `verifier_entrypoint`
- package-relative generated file refs 和 sha256
- package-relative check/replay command
- consumer contract

新增 `run_packaged_generated_bundle_check(package_dir)` 作为最小 downstream consumer：它依赖 package 内 runtime index，同时执行 packaged `check_replay.py` 和框架侧 independent verifier。对 request-generated bundle，independent verifier 会直接加载 package 内 `runtime.py`、`verifier.py`、`seed_state.json`，按 `TaskSet.framework_replay.tool_calls` 覆盖 accepted tasks 的正反记录。这样 generated environment 不再只存在于临时 build workdir，而是有了 package 内稳定调用入口，并且不只信任 generated check 的 stdout 自报。

### 7.7 当前阶段判断：Independent verifier 与 bounded repair loop 已接入

Goal 11 修正了两个 release 真实性问题：

- generated bundle gate 不再把 generated `check_replay.py` stdout success 当作唯一放行证据。
- agent-backed implementation 失败后不再只能停止；框架会构造 failure packet，并在有界 attempt budget 内重新调用同一个 `AgentBackend`。

当前实现边界：

- `agent_world.independent_verifier` 是框架侧 verifier，不属于 generated bundle。
- 对 request-generated bundle，它直接 import generated `runtime.py` / `verifier.py`，加载 `seed_state.json`，检查 runtime/verifier entrypoints、runtime tool methods 和 `check_replay.py` 结构 sanity。
- 对 release accepted tasks，通用 verifier 根据 `TaskSet.framework_replay.tool_calls` 执行工具调用，检查 trace 顺序、state/answer evidence，并产生独立 positive/negative task records；未覆盖或 unsupported task 会阻止 release。
- 伪造只打印 success JSON 的 `check_replay.py` 会被拒绝。
- 每次 agent implementation attempt 都记录 `AgentInvocationRecord`、candidate paths/file hashes、check/replay records；失败 attempt 生成包含 failure class、failed task/verifier、command、exit code、stdout/stderr preview、manifest/path/hash/check failure 的 failure packet。
- repair loop 由 `PipelineRunner` 控制，agent 只接收 failure packet 并生成下一候选；agent 不能决定跳过 gate 或进入 release。

这仍不等于高质量通用 verifier synthesis，也不等于 live code-agent 质量保证。当前已完成的是 contract-driven generic generated bundle verification：框架能执行上游 artifacts 生成的 replay contract，并把失败 observation 喂给 bounded repair。

仍未完成的是通用 rollout/online adapter：当前只是 package-relative check consumer，不是任意 policy rollout，也不是 verl/GRPO trainer 集成。下一步应基于 runtime index 读取 `TaskSet`、加载 runtime/verifier entrypoints、执行外部 policy action，并产出 rollout/reward records。

### 7.8 当前阶段判断：Request-driven generation pipeline 已泛化为 agent-backed path

用户最终要的不是“手动选择一个已注册 fixture registry 后完整跑通”，而是输入一个新环境需求后，系统自动生成对应环境。当前 request-driven 入口已经从 booking/library 探针改为通用 artifact path：

```text
raw_request = 任意非空环境需求
release.environment_id = env-<request-derived-slug>-<hash>
```

当前实现边界：

- `DomainPlan` 从 `PipelineRunConfig.raw_request` 派生 environment id、recognized concepts、state objects 和 operations，不再依赖 booking/library/project-board 等领域词表。
- `StrategySelection` 自动选择 raw-request source discovery、generic extraction/synthesis、agent-generated bundle、generic independent verifier 和 generated-runtime package strategy。
- `request_driven_node_registry()` / `run_request_driven_pipeline()` 是 request-driven 入口；success path 不要求调用方手动选择领域 registry。
- Source planning/discovery 会在 pipeline store 下写 raw request source，并合并显式传入的本地 source paths，形成带 hash/license/auth/network/security note 的 `SourceEvidenceIndex`。
- S2-S7 从 source evidence / `KnowledgePack` 派生 `EnvironmentSpec`、`LogicalToolGraph`、`TaskSet`、`SurfacePlan`、`VerifierPlan` 和每个 task 的 `framework_replay.tool_calls`。
- IMPLEMENT 强制使用 `AgentBackend`。如果 request-driven run 仍走 deterministic mode，只会返回 `agent_backend_required`，不会产生 release。
- Agent 生成的 bundle 必须包含 `runtime.py`、`seed_state.json`、`verifier.py`、`surface_descriptor.json`、`check_replay.py`、`build_manifest.yaml`，并由 generated self-check 与 framework-owned generic independent verifier 同时验证。
- `IndependentVerificationReport` 覆盖 accepted tasks 的 positive/negative records；伪造只打印 success 的 `check_replay.py` 会被拒绝。
- 每个阶段 artifact 都记录上游 inputs/consumed_inputs 与 producer/produced_by；`ReleaseManifest.request_lineage` 可追溯 raw request/domain plan -> source evidence -> task/verifier plan -> implementation request -> generated bundle -> independent verifier report。
- Source failure 会写 failure packet 并停止在 release 前；agent implementation failure 继续进入 bounded repair loop，达到上限仍失败时不生成 S10/S11 release。
- 手动 `project_board_lite_node_registry()` 加任意 raw request 仍会发布 `project-board-lite`，但测试明确证明这不是 request-driven success path。

当前仍不表示真实网络 crawler、真实 trainer、全 surface 发布，或 live code agent 默认能稳定产出高质量环境。下一步应提升 source-grounded extraction/synthesis 和 implementation brief/replay contract 质量，而不是新增手动领域 registry。

## 8. 第一实现切片冻结

本节之后的内容冻结第一实现切片。冻结目标不是实现 runtime，而是把后续实现必须遵守的阶段边界、artifact contract、deterministic gate、surface 边界、fixture 和验收标准写清楚。

第一实现切片的范围：

1. 输入一个环境需求或资料种子。
2. 生成可审计的 source evidence、knowledge package、environment spec、logical tool graph、task set、surface plan、verifier plan、feasibility report 和 release manifest 草案。
3. 只要求第一条垂直 fixture 能被实现成可 reset、可调用、可 verifier 检查的环境包。
4. 不实现训练、rollout、reward export、解题 agent runner 绑定或通用训练运行时；但必须实现环境生成流水线内部的 `AgentBackend` / `AgentInvocationRecord` 机制。

第一实现切片的硬边界：

- AWM 仍然只是背景和可选 fixture source，不是目标架构、默认 schema 或默认 surface。
- 核心 contract 使用本项目自己的 artifact 名称和字段，不能继承 AWM JSONL 作为内部标准。
- logical tool 与 concrete surface 必须分离。
- gate 默认 deterministic；LLM/agent 只能出现在显式节点，并且必须产生日志、预算、输入、输出和 evidence。
- 调研、搜索、repo 探索、MCP/CLI/API 文档读取、实现请求起草等需要智能判断的步骤，必须通过 `AgentInvocation` / `AgentBackend` 作为 workflow 节点进入流程。第一实现切片必须实现这个调用机制；Codex SDK、Codex CLI、search agent、mini-swe-agent、deep-search 等真实 backend 可以作为 adapter 使用，但核心只依赖 backend-neutral contract。
- 训练/评估框架只能消费 release package，不能成为生成系统依赖。
- Goal 02-04 已经添加的 rollout、online runtime、HTTP wrapper 和 environment CLI 只能作为 fixture/downstream consumer 回归保留；Goal 05 已完成 pipeline 结构收敛，Goal 06 期间不继续新增 runtime/training surface，除非用户明确要求。

## 9. 冻结工作流阶段

第一实现切片使用显式 staged workflow，而不是固定两条 loop。阶段可以由 DAG 表达，默认按下表顺序执行；失败时只能回到表中指定的上游阶段。

| 阶段 | 名称 | 输入 artifact | 输出 artifact | LLM/agent 边界 | 必过 gate | 允许反馈边 |
| --- | --- | --- | --- | --- | --- | --- |
| S0 | Input Normalization | raw request/source seed | `NeedSpec` | 允许 LLM 抽取需求；不能决定流程 | G0, G1, G13 | S0 retry / terminal blocked |
| S1 | Source Discovery | `NeedSpec` | `SourceEvidenceIndex` | 允许通过 `AgentBackend` 调用 search/code agent 搜索、列候选、读资料、探索 MCP/CLI/API/repo | G0, G2, G3, G13 | S0 |
| S2 | Knowledge Extraction | `SourceEvidenceIndex` | `KnowledgePack` | 允许 LLM/agent 抽取 schema、流程、状态对象；必须带引用和 invocation evidence | G0, G2, G13 | S1 |
| S3 | Environment Specification | `NeedSpec`, `KnowledgePack` | `EnvironmentSpec` | 允许 LLM 起草；deterministic validator 定稿 | G0, G4, G13 | S2 |
| S4 | Tool Graph | `EnvironmentSpec`, `KnowledgePack` | `LogicalToolGraph` | 允许 LLM 判断 weak/strong dependency；必须可解释 | G0, G5, G13 | S2/S3 |
| S5 | Task Generation | `NeedSpec`, `LogicalToolGraph`, `EnvironmentSpec` | `TaskSet` | 允许 LLM 生成自然请求和难度；solver/filter 必须 deterministic 优先 | G0, G6, G7, G13 | S4 |
| S6 | Surface Planning | `LogicalToolGraph`, `EnvironmentSpec` | `SurfacePlan` | 允许 LLM 推荐 surface；绑定检查 deterministic | G0, G8, G13 | S3/S4 |
| S7 | Verifier Planning | `TaskSet`, `EnvironmentSpec`, `SurfacePlan` | `VerifierPlan` | 允许 LLM 起草 verifier idea；最终 verifier 必须有 deterministic path | G0, G9, G13 | S5/S6 |
| S8 | Feasibility Filtering | S0-S7 artifacts | `FeasibilityReport` | 不允许 LLM 直接放行；LLM 只能解释失败和建议 recovery | G0, G10, G13 | S1-S7 |
| S9 | Implementation Plan | `FeasibilityReport`, accepted artifacts | `ImplementationRequest` | 允许 LLM/code agent 起草实现请求；不能执行实现 | G0, G13 | S3-S8 |
| S10 | Package Assembly Plan | S0-S9 artifacts | `EnvironmentPackagePlan` | deterministic assembly spec；LLM 只能补文案 | G0, G11, G13 | S3-S9 |
| S11 | Release Plan | `EnvironmentPackagePlan`, accepted tasks/verifiers | `ReleaseManifest` | deterministic manifest；LLM 只能生成 consumer notes | G0, G12, G13 | S5-S10 |

阶段不变量：

- 每个 artifact 必须有 `id`、`version`、`created_at`、`source_stage`、`inputs`、`producer`、`hash` 和 `status`。
- 所有跨 artifact 引用都用稳定 ID，不用自然语言位置描述。
- 任何 LLM/agent 输出都必须写入 `AgentInvocationRecord`，记录 `backend_kind`、`model_or_runtime`、`prompt_or_instruction_ref`、`budget`、`tool_access`、`input_artifact_ids`、`output_artifact_ids` 和 `trace_ref`。
- gate 的通过或失败必须落到 `GateRecord`，不能只写在日志或 prompt 中。
- 关键节点的 gate 通过前必须产生独立 `ReviewRecord`，确认当前 artifact 没有偏离 `NeedSpec`、本文 source-of-truth 和已接受的上游 artifact。
- 失败只能产生 typed `failure_class` 和 `recovery_suggestion`，不能让模型自由决定下一跳。

### 9.1 关键节点独立 Review

关键节点不是可选流程。每个会批准下游继续推进的节点，都必须先做独立 review，再记录 gate 结果。第一实现切片中，S0-S11 都是关键节点；任何阶段 artifact 被标记为 accepted 之前都要有独立 `ReviewRecord`。

每个阶段的 review 重点：

- S0 完成后：确认需求范围没有漂移，没有把训练、AWM 复现或 runtime 实现提前纳入。
- S1 完成后：确认 source selection 没有偏向 AWM、MCP-only、CLI-only 或不可接受 license/auth/network source。
- S2 完成后：确认 knowledge extraction 有 source evidence，不是 prompt-only 总结。
- S3 完成后：确认 environment spec 仍然 surface-neutral，且 state/reset/isolation 明确。
- S4 完成后：确认 tool graph 的读写状态、依赖边和参数分类没有脱离 source evidence。
- S5 完成后：确认 task set 自然、可解、无内部泄漏，并绑定 verifier refs。
- S6 完成后：确认 surface binding 没有改变 logical tool 语义，没有把 generic shell executor 当环境 CLI surface。
- S7 完成后：确认 verifier plan 有 deterministic path，不把 LLM judge 当唯一 reward。
- S8 完成后：确认 feasibility pass 有证据支撑，失败时没有被模型强行放行。
- S9 完成后：确认 `ImplementationRequest` 只是实现输入，没有执行环境 runtime implementation，也没有绑定单一解题/rollout runner；生成流水线内部的 `AgentBackend` 调用必须保留 backend-neutral contract。
- S10 完成后：确认 package contract 完整，包含 gate/review/replay evidence，不夹带实现外任务。
- S11 完成后：确认 release contract 可被 consumer 使用，且没有绑定训练框架。

独立 review 的规则：

- reviewer 不能是同一个 artifact 的 producer。
- review 输入必须包含当前 artifact、上游 accepted artifact、相关 gate checklist 和本文档对应章节。
- review 输出必须写入 `ReviewRecord`，包括 `alignment_status`、`drift_findings`、`required_fixes`、`waived_risks` 和 `reviewer_ref`。
- `alignment_status=fail` 时不得进入下游阶段；只能修复当前 artifact 或回到允许的上游阶段。
- LLM/agent 可以担任 reviewer，但必须作为显式 review 节点运行，记录模型、预算、输入输出和 trace；不能把同一次生成调用的自评当独立 review。

## 10. Artifact Contracts

第一实现切片只冻结 contract，不冻结序列化格式。默认可以用 YAML 或 JSON；实现时必须提供 schema validator。字段名使用英文，说明文字可以是中文。

所有 artifact 都必须同时包含通用元数据和类型字段。类型字段里的 `environment_id`、`release_id`、`review_id` 等是领域 ID，不替代通用 `id`。通用元数据为：

- `id`
- `version`
- `created_at`
- `source_stage`
- `inputs`
- `producer`
- `hash`
- `status`

### 10.1 `NeedSpec`

必填字段：

- `id`
- `goal`
- `target_capabilities`
- `domain_seed`
- `expected_agent_behavior`
- `constraints`: `network`, `auth`, `license`, `safety`, `local_execution`, `mocking_allowed`
- `preferred_surfaces`
- `out_of_scope`
- `blocked_conditions`

### 10.2 `SourceEvidenceIndex`

必填字段：

- `sources[]`: `source_id`, `kind`, `uri_or_path`, `version_or_hash`, `retrieved_at`, `license`, `auth_requirement`, `network_requirement`, `security_note`
- `extractable_objects[]`: `source_id`, `object_kind`, `name`, `evidence_refs`
- `mock_boundaries[]`
- `open_questions[]`
- `rejected_sources[]`: `source_id`, `reason`

`kind` 枚举至少包括：`prd`, `repo`, `mcp_server`, `cli_help`, `api_docs`, `sdk_docs`, `database_schema`, `http_service`, `local_files`, `awm_sample`, `manual_note`。

### 10.3 `KnowledgePack`

必填字段：

- `state_objects[]`: `object_id`, `name`, `fields`, `relations`, `source_refs`
- `operations[]`: `operation_id`, `name`, `inputs`, `outputs`, `side_effects`, `source_refs`
- `business_rules[]`: `rule_id`, `description`, `source_refs`, `confidence`
- `verifiable_fields[]`
- `uncertainties[]`: `question`, `blocking`, `candidate_resolution`

任何没有 `source_refs` 的知识只能标为 `inferred`，并且不能单独通过 feasibility。

### 10.4 `EnvironmentSpec`

必填字段：

- `environment_id`
- `domain`
- `state_backend`: `kind`, `reset_strategy`, `isolation_strategy`, `seed_fixture_refs`
- `state_entities[]`
- `logical_tools[]`
- `permissions`
- `safety_boundaries`
- `mock_policy`
- `release_surfaces_allowed`: `python`, `cli`, `http`, `mcp`
- `observability`: `logs`, `traces`, `state_snapshots`

### 10.5 `LogicalToolGraph`

必填字段：

- `tools[]`: `tool_id`, `name`, `input_schema`, `output_schema`, `reads`, `writes`, `side_effects`, `errors`, `idempotency`
- `edges[]`: `from_tool_id`, `to_tool_id`, `dependency_type`, `reason`
- `parameters[]`: `name`, `classification`, `source`, `validation`
- `forbidden_direct_access[]`

`dependency_type` 只能是 `strong`、`weak`、`independent`。`classification` 只能是 `external`、`internal`、`optional`。

### 10.6 `TaskSet`

必填字段：

- `tasks[]`: `task_id`, `natural_request`, `target_capability`, `initial_state_refs`, `expected_state_delta`, `expected_answer`, `allowed_logical_tool_ids`, `forbidden_leakage`, `dependency_path`, `difficulty`, `verifier_refs`
- `coverage`: `tool_ids`, `capabilities`, `state_entities`
- `rejected_candidates[]`: `candidate_id`, `reason`

`natural_request` 不能暴露 tool name、database field、backend ID、verifier ID 或实现路径。

### 10.7 `SurfacePlan`

必填字段：

- `bindings[]`: `binding_id`, `logical_tool_id`, `surface`, `exposure_name`, `input_mapping`, `output_mapping`, `error_mapping`, `auth_context`, `state_scope`
- `surface_status`: 每个 surface 的 `planned`, `required_for_first_slice`, `deferred` 或 `rejected`
- `compatibility_notes[]`

### 10.8 `VerifierPlan`

必填字段：

- `verifiers[]`: `verifier_id`, `task_id`, `kind`, `inputs`, `checks`, `success_criteria`, `failure_criteria`, `positive_examples`, `negative_examples`, `evidence_refs`
- `llm_judges[]`: `judge_id`, `task_id`, `rubric`, `model`, `budget`, `evidence_inputs`, `fallback_policy`

第一实现切片中，`llm_judges[]` 可以存在，但不能作为唯一 verifier。

`kind` 至少支持：

- `state_query`: 对 SQLite、文件索引、local service state 或 API state 做只读断言。
- `state_diff`: 对 initial snapshot 和 final snapshot 做差异断言。
- `file_assertion`: 检查文件存在性、内容、hash 或结构化 parse 结果。
- `command_assertion`: 运行受控命令，检查退出码、stdout/stderr schema 和超时。
- `test_assertion`: 运行指定测试目标，检查测试结果和 coverage note。
- `api_assertion`: 调用受控 API，检查 response、状态副作用和错误映射。

每个 deterministic verifier 必须补充：

- `replay_inputs`: seed fixture、initial snapshot、final snapshot、agent answer、surface trace 中需要哪些输入。
- `assertions[]`: `assertion_id`, `target`, `operator`, `expected`, `tolerance`, `source_ref`
- `allowed_side_effects`: 默认空；非空时必须说明原因。
- `timeout_ms`
- `isolation_requirement`
- `failure_diagnostics`

### 10.9 `FeasibilityReport`

必填字段：

- `status`: `pass`, `fail`, `blocked`
- `gate_results[]`: `gate_id`, `status`, `evidence`, `failure_class`, `recovery_suggestion`
- `minimum_viable_surface`
- `minimum_viable_task_ids`
- `minimum_viable_verifier_ids`
- `implementation_blockers[]`

只有 `status=pass` 时才能生成 `ImplementationRequest`。

### 10.10 `ImplementationRequest`

必填字段：

- `request_id`
- `environment_id`
- `source_artifact_ids`
- `accepted_task_ids`
- `accepted_verifier_ids`
- `required_surface_ids`
- `package_layout_ref`
- `implementation_scope`
- `non_goals`
- `tdd_requirements`
- `launch_check_replay_commands`
- `review_record_refs`

`ImplementationRequest` 是给后续 code agent 或 implementation backend 的输入，不代表本文阶段开始实现 runtime。

### 10.11 `GeneratedEnvironmentBundle`

必填字段：

- `bundle_id`
- `environment_id`
- `source_artifact_ids`
- `implementation_request_id`
- `build_dir`
- `generated_files[]`: `path`, `kind`, `sha256`, `source_refs`
- `runtime_entrypoint`
- `seed_fixture_ref`
- `verifier_entrypoint`
- `surface_descriptors`
- `check_commands[]`
- `replay_commands[]`
- `build_check_replay_records[]`

`generated_files.kind` 至少支持：

- `runtime_code`
- `seed_fixture`
- `verifier_code`
- `surface_descriptor`
- `test_or_check`
- `build_manifest`

`GeneratedEnvironmentBundle` 是 implementation/check 阶段的可执行产物记录，不替代 `ImplementationRequest`。相关 release 必须引用通过 build/check/replay 的 bundle；如果 bundle check fail 或 `blocked`，不得生成 `ReleaseManifest`。

### 10.12 `EnvironmentPackagePlan`

必填字段：

- `package_plan_id`
- `environment_id`
- `layout`
- `included_artifact_ids`
- `fixture_refs`
- `static_check_refs`
- `review_record_refs`
- `replay_plan_ref`
- `release_manifest_ref`
- `consumer_output_refs`
- `excluded_items[]`: `item`, `reason`

`EnvironmentPackagePlan` 在存在 generated implementation 时必须引用 verified `GeneratedEnvironmentBundle`，不能只引用 `ImplementationRequest`。

### 10.13 `ReleaseManifest`

必填字段：

- `release_id`
- `environment_id`
- `version`
- `artifact_hashes`
- `package_layout`
- `task_index`
- `verifier_index`
- `surface_index`
- `fixture_index`
- `replay_contract`
- `consumer_outputs`
- `known_limits`

`consumer_outputs` 面向训练/评估系统，但只描述数据 contract，不引入 verl、LLaMA-Factory、OpenRLHF、TRL 等依赖。

### 10.14 `GateRecord`

必填字段：

- `gate_record_id`
- `gate_id`
- `stage`
- `checked_artifact_ids`
- `status`: `pass`, `fail`, `blocked`
- `evidence_refs`
- `failure_class`
- `recovery_suggestion`
- `review_record_refs`
- `created_at`

### 10.15 `ReviewRecord`

必填字段：

- `review_id`
- `reviewed_artifact_ids`
- `source_of_truth_refs`
- `reviewer_ref`
- `review_type`: `human`, `llm_agent`, `static_check`, `peer_process`
- `alignment_status`: `pass`, `fail`, `blocked`
- `drift_findings[]`: `requirement_ref`, `finding`, `severity`, `evidence`
- `required_fixes[]`
- `waived_risks[]`: `risk`, `reason`, `approver`
- `created_at`

`ReviewRecord` 是 gate evidence，不是可读性建议。没有 review evidence 的关键节点不能标记为通过。

### 10.16 `ReplayPlan`

必填字段：

- `replay_plan_id`
- `environment_id`
- `seed_fixture_refs`
- `task_ids`
- `surface_binding_ids`
- `reset_steps`
- `execution_trace_inputs`
- `state_snapshot_points`: `before`, `after`, `on_failure`
- `verifier_ids`
- `expected_gate_ids`
- `determinism_notes`
- `known_nondeterminism[]`: `source`, `mitigation`

### 10.17 `ConsumerIndex`

必填字段：

- `consumer_index_id`
- `release_id`
- `task_records_ref`
- `verifier_records_ref`
- `surface_index_ref`
- `reset_contract_ref`
- `trace_contract_ref`
- `result_record_schema`
- `adapter_notes`

`ConsumerIndex` 只描述训练/评估 consumer 如何读取 release package，不指定或依赖具体训练框架。

### 10.18 `AgentInvocationRecord`

当任何阶段调用 LLM、search agent、code agent、Codex SDK/CLI、mini-swe-agent、deep-search 或其他智能 backend 时，必须产生 `AgentInvocationRecord`。

必填字段：

- `invocation_id`
- `stage`
- `node_purpose`: `search`, `extract`, `synthesize`, `review`, `judge`, `draft_implementation_request`, `implement`, `other`
- `backend_kind`: `llm`, `openai_codegen`, `code_agent_runner`, `codex_cli_runner`, `codex_sdk`, `codex_cli`, `process_agent`, `search_agent`, `mini_swe_agent`, `deep_search`, `manual`, `mock`, `custom`
- `backend_ref`
- `config_ref`
- `model_or_runtime`
- `instruction_ref`
- `input_artifact_ids`
- `allowed_tool_access`
- `permissions`: `network`, `filesystem`, `auth`, `sandbox`
- `budget`: `tokens`, `time_ms`, `cost_limit`
- `output_artifact_ids`
- `evidence_refs`
- `trace_ref`
- `status`: `pass`, `fail`, `blocked`
- `failure_class`
- `recovery_suggestion`

### 10.19 `AgentBackendConfig`

第一实现切片必须定义 agent backend 的配置 contract。它用于让 workflow 节点调用 OpenAI-compatible API、OpenAI-compatible codegen、Codex CLI/SDK、search agent、process agent 或 mock/manual backend。

必填字段：

- `backend_id`
- `backend_kind`: `llm`, `openai_codegen`, `code_agent_runner`, `codex_cli_runner`, `codex_sdk`, `codex_cli`, `process_agent`, `search_agent`, `mini_swe_agent`, `deep_search`, `manual`, `mock`, `custom`
- `provider`: `openai`, `openai_compatible`, `azure_openai`, `codex`, `local_process`, `manual`, `mock`, `custom`
- `model`
- `base_url`
- `api_version`
- `auth`: `api_key_env`, `auth_env_refs`, `requires_auth`
- `command`: 仅 `process_agent` / `codex_cli` / `code_agent_runner` / `codex_cli_runner` 需要，包含命令、固定参数、allowlist 和禁止参数。
- `timeouts`: `connect_ms`, `run_ms`
- `budgets`: `max_tokens`, `max_cost`, `max_tool_calls`
- `permissions`: `network`, `filesystem`, `auth`, `sandbox`
- `output_schema_ref`
- `redaction_policy`

配置来源优先级：

1. 显式 config file / workflow input。
2. 环境变量。
3. 安全默认值。

第一实现切片至少支持这些环境变量：

- `AGENT_WORLD_AGENT_BACKEND`: 默认 backend，例如 `openai_codegen`、`code_agent_runner`、`codex_cli_runner`、`process_agent`、`codex_cli`、`llm`、`mock`。
- `AGENT_WORLD_CODE_AGENT_CMD`: generic process-agent/code-agent runner command；用于 mini-swe-agent、自定义 wrapper、Claude Code wrapper 或其他本地 code agent。
- `AGENT_WORLD_OPENAI_BASE_URL`: OpenAI-compatible API base URL；未设置时可回退到 `OPENAI_BASE_URL`。
- `AGENT_WORLD_OPENAI_API_KEY`: API key；未设置时可回退到 `OPENAI_API_KEY`。
- `AGENT_WORLD_OPENAI_MODEL`: agent backend 使用的模型；未设置时可回退到 `OPENAI_MODEL`。
- `AGENT_WORLD_SMOKE_OPENAI_MODEL`: Goal/CI/live smoke test 优先使用的低成本模型；未设置时回退到 `AGENT_WORLD_OPENAI_MODEL`。
- `AGENT_WORLD_OPENAI_API_VERSION`: Azure/OpenAI-compatible provider 需要 API version 时使用；标准 OpenAI API 可以为空。
- `AGENT_WORLD_CODEX_CMD`: Codex CLI 或 Codex runner 命令路径，例如 `codex exec --json --sandbox workspace-write --ask-for-approval on-request -`。

测试模型策略：

- Goal 模式、CI 或本地 smoke test 若需要真实 OpenAI-compatible 调用，必须优先使用低成本模型。
- 推荐示例：`gpt-5.4-mini`、`gpt-3-codex-spark`。这些只是配置示例；实现不能把具体模型名写死。
- live smoke test 必须可通过环境变量关闭或跳过；没有 API key、base URL、模型或网络权限时，不得导致 deterministic test 失败。
- 默认测试路径应使用 `mock` / 预配置 `manual` backend；真实模型调用只验证 agent backend wiring、artifact 记录、权限/预算/trace 和 gate 行为。`manual` backend 只能读取运行前提供的响应，不能在运行中等待人工输入。

安全要求：

- artifact 和 `AgentInvocationRecord` 只能记录 secret 的 env var 名称或 secret ref，不能记录 API key 明文。
- `base_url`、`model`、`api_version`、backend kind、命令路径和权限必须进入 `AgentBackendConfig` 或 `AgentInvocationRecord`，便于 replay 和审计。
- 旧 AWM 变量如 `AWM_SYN_OVERRIDE_MODEL` 只能作为 legacy compatibility fallback，不能成为新系统主配置名。

约束：

- core workflow 只能依赖 `AgentInvocationRecord` 和 backend-neutral `AgentBackend` 接口，不能直接依赖某个 SDK。
- 真实 Codex SDK、Codex CLI、mini-swe-agent、deep-search 等只能作为 adapter 实现。
- 第一实现切片必须实现 agent invocation runtime、backend registry 和至少两个 backend：一个用于 deterministic tests 的预配置 `manual` 或 `mock` backend，以及一个真实 codegen/backend runner，例如 `openai_codegen`、`code_agent_runner`、`codex_cli_runner` 或真实可调用的本地 agent backend。真实 backend 必须受配置、权限、超时、预算和输出 schema 约束。
- `process_agent` 只用于生成流水线内部的 research/code-agent workflow node，不是环境 CLI surface，也不是允许 agent 任意执行 shell 的环境工具。
- `code_agent_runner` / `codex_cli_runner` 是生成流水线内部的 implementation runner，不是环境 CLI surface。它们的 workspace packet 和 command log 必须可审计，release 只能引用 verified generated bundle。
- Codex CLI/SDK、search agent、mini-swe-agent、deep-search 等可以作为具体 adapter，但都不能成为 core dependency。
- agent backend 的输出不能直接放行 gate；必须进入 artifact validator、gate 和 independent review。

## 11. Deterministic Gates

第一实现切片必须先实现或至少在文档中定义以下 gate。后续 runtime 实现时，gate 失败必须停止下游阶段。

| Gate | 阶段 | 类型 | 通过条件 |
| --- | --- | --- | --- |
| G0 Schema Gate | 全阶段 | static | artifact schema、必填字段、枚举、ID、hash、cross-ref 全部合法 |
| G1 Scope Gate | S0 | static | need 与当前系统目标一致，不要求训练集成、AWM 复现或 runtime 外能力 |
| G2 Evidence Gate | S1/S2 | deterministic | 每个核心状态对象、工具、规则至少有一个 source ref 或明确 inferred 标记 |
| G3 Permission Gate | S1 | deterministic | 网络、认证、license、安全要求可接受；不可接受则 `blocked` |
| G4 State Reset Gate | S3 | deterministic | state backend 有 reset 和 isolation 策略，seed fixture 可版本化 |
| G5 Tool Graph Gate | S4 | deterministic | tool 读写对象存在，依赖边无未知节点，strong dependency 可满足 |
| G6 Task Solvability Gate | S5 | deterministic-first | 每个 accepted task 有 initial state、allowed tools、expected delta/answer 和 verifier ref |
| G7 Leakage Gate | S5 | static | 用户请求不泄漏 tool/schema/backend/verifier 内部名 |
| G8 Surface Gate | S6 | deterministic | 至少一个 surface 可受控调用；surface binding 不改变 logical tool 语义 |
| G9 Verifier Gate | S7 | deterministic | 每个任务至少一个 deterministic verifier，有正例和负例说明 |
| G10 Feasibility Gate | S8 | deterministic | sources、state、tools、tasks、surface、verifier、安全全部满足最小可行要求 |
| G11 Package Gate | S10 | static | package plan 包含 spec、fixtures 或 generated bundle、surfaces、tasks、verifiers、checks、release metadata；generated bundle check fail 时不得通过 |
| G12 Release Gate | S11 | static | release manifest 可被训练/评估 consumer 枚举任务、调用 surface、运行 verifier、记录 trace；存在 generated implementation 时必须引用 verified bundle |
| G13 Independent Review Gate | 关键节点 | review | 关键节点存在独立 `ReviewRecord`，且 `alignment_status=pass`；若 review blocked 则写 blocked artifact 并停止，不等待人工 |
| G14 Agent Invocation Gate | 使用 LLM/agent 的阶段 | static/security | 每次 LLM/agent 调用都有 `AgentInvocationRecord` 和 `AgentBackendConfig`，权限/预算/输入输出/trace 完整，secret 不落盘，backend 通过 adapter 接入 |

LLM 可以辅助解释 gate failure，但不能把失败改成通过。

## 12. Source Discovery 策略

Source discovery 使用 connector registry 的概念。第一实现切片最初只冻结策略，不实现 connector runtime；进入结构收敛阶段后，应实现最小 connector runtime，让真实本地 PRD、CLI help、schema 或 docs 文件能进入 `SourceEvidenceIndex`，并能被后续节点引用。

Source discovery 也使用 agent backend registry 的概念。需要调研、搜索、探索 MCP server、读取 CLI/API/SDK 文档或分析 repo 时，可以启动 research/code agent backend；但每次调用必须留下 `AgentInvocationRecord`，并把结果转换成 source evidence 或 knowledge artifact。

优先级：

1. 用户显式提供的 PRD、repo、docs、schema、MCP server、CLI、API/SDK docs。
2. 本地可读资料和仓库内 fixture。
3. 可公开访问且 license/network 可接受的资料。
4. AWM 样本，仅作为 `awm_sample` source kind，不作为默认 schema。

每个 source candidate 必须被分类：

- `primary`: 可以直接支撑 environment spec。
- `supporting`: 只能补充术语、示例或 verifier idea。
- `fixture`: 只能用于离线测试或转换样例。
- `rejected`: 因 license、auth、网络、安全、质量或范围不符被拒绝。

MCP、CLI、HTTP、Python callable 在 discovery 阶段都只是 source 或 potential surface，不自动成为环境实现方式。

## 13. Task Generation 策略

任务生成必须从 `LogicalToolGraph` 和 `EnvironmentSpec` 出发。

生成流程：

1. 采样 dependency path，包括单工具、弱依赖链、强依赖链和跨状态对象链。
2. 为每条 path 生成自然用户请求。
3. 绑定 initial state requirement 和 expected state delta/answer。
4. 分配 allowed logical tools，禁止直接暴露内部工具名。
5. 为每个任务绑定至少一个 deterministic verifier plan。
6. 运行 solvability、leakage、coverage、difficulty、verifier gates。
7. 把失败候选写入 `rejected_candidates[]`。

第一实现切片的任务集最小要求：

- 至少 5 个 accepted tasks。
- 至少覆盖 4 个 logical tools。
- 至少包含 2 个会改变状态的任务。
- 至少包含 1 个只读查询任务。
- 至少包含 1 个需要 strong dependency path 的任务。

## 14. Surface 边界

核心对象是 logical tool。surface 只是把 logical tool 暴露给 agent 或 harness 的方式。

### 14.1 Python Surface

Python surface 是第一实现切片的推荐最小 runnable surface，因为它最容易被 deterministic verifier 和测试直接调用。

边界：

- 每个 callable 对应一个 logical tool 或一个明确的 reset/check 操作。
- 输入输出必须是 schema 化对象。
- callable 不能读取 prompt-only memory。
- callable 可以被 harness 调用，但 harness 控制流不是 environment surface 的一部分。

### 14.2 CLI Surface

CLI 是环境发布 surface，不是 generic shell executor。

本文中的 CLI surface 指 **环境工具本身通过命令行暴露**，例如：

```text
lark doc create ...
gh issue create ...
kubectl apply ...
aws s3 cp ...
```

它不是 harness/runtime control CLI。`reset`、`observe`、`step`、`finalize` 这类命令可以作为调试或外部 trainer 控制入口，但它们不等于环境工具 CLI surface。

边界：

- CLI 命令必须映射到具体 logical tool。runtime lifecycle 命令必须单独标注为 `runtime_control_cli`，不能冒充 environment CLI surface。
- 参数来自 logical tool input schema。
- 输出默认为 JSON 或 JSONL。
- 不允许暴露任意 shell 执行能力作为环境工具。
- CLI 名称不能泄漏 backend table/field，除非该名称本来就是用户领域概念。
- CLI discovery 可以来自 `--help`、man page、CLI docs、examples 或受控探针；正式发布 package 必须固化 command template、input schema、output parser、allowed exit codes、timeout 和 state scope。
- 运行时必须使用 `subprocess.run(argv, shell=False)` 或等价安全机制，不允许 `bash -c`、管道、重定向、命令拼接或未声明命令。

调用模型：

```text
RuntimeAction(tool_name, arguments)
  -> lookup environment_cli descriptor
  -> render allowlisted argv template
  -> execute CLI command
  -> parse stdout/stderr/exit_code
  -> write observation and step record
  -> verifier reward
```

MCP 与 CLI 的发现方式不同：

```text
MCP: start server -> initialize -> list_tools -> call_tool
CLI: read docs/help -> package command templates -> subprocess argv
```

二者进入训练系统前都应归一到 logical tool / RuntimeAction / RuntimeObservation。

### 14.3 HTTP Surface

HTTP surface 适合模拟真实 API 或 local service。

边界：

- endpoint 必须映射到 logical tool。
- OpenAPI 或等价 schema 必须从 `SurfacePlan` 生成。
- auth、tenant、session 和 reset scope 必须显式。
- HTTP 状态码与 logical error 必须有 mapping。

### 14.4 MCP Surface

MCP surface 是可选发布 surface，不是默认架构。

边界：

- MCP tools/resources 从 logical tool 和 state read model 生成。
- MCP server 不能要求 AWM JSONL 或 AWM-specific schema。
- MCP session state 必须能 reset/isolate。
- MCP tool name 可以是 adapter 名称，但必须保留 `logical_tool_id` mapping。

## 15. Surface-neutral Environment Package

第一实现切片的环境包使用 surface-neutral 布局。实现时可以调整文件扩展名，但不能删除 contract 层次。

```text
envpkg/
  package.yaml
  sources/
    evidence-index.yaml
  spec/
    need.yaml
    knowledge-pack.yaml
    environment.yaml
    logical-tools.yaml
    tool-graph.yaml
    tasks.yaml
    surfaces.yaml
    verifiers.yaml
    feasibility.yaml
    implementation-request.yaml
    package-plan.yaml
  fixtures/
    seed/
    positive/
    negative/
  checks/
    agent-backend-config.yaml
    static-gates.yaml
    gate-records.yaml
    review-records.yaml
    agent-invocations.jsonl
    replay-plan.yaml
  release/
    release-manifest.yaml
    task-records.jsonl
    verifier-records.jsonl
    consumer-index.yaml
```

包内可以包含实现代码。第一实现切片最初只冻结 layout 和 artifact contract；进入结构收敛阶段后，允许通过 explicit implementation/code-agent node 在隔离目录生成或装配实现代码，但必须记录 `AgentInvocationRecord`、build/check evidence、replay result 和 release refs。

## 16. 第一 runnable fixture

第一实现切片的首个 runnable fixture 冻结为 `support-desk-lite`。选择该 fixture 的原因是：它可以由小型 PRD 和本地 seed 数据支撑，包含读写状态、强依赖任务、deterministic verifier，并且不依赖 AWM、网络或认证。

### 16.1 领域和状态

领域：客服工单处理。

状态 backend：

- 第一实现建议：SQLite。
- 必须支持：从 seed reset、每次 run 独立工作目录、final state snapshot。

状态实体：

- `customer`: 客户、等级、区域、联系信息。
- `ticket`: 工单、状态、优先级、主题、描述、所属客户。
- `ticket_note`: 内部备注和用户可见备注。
- `assignment`: 工单负责人和队列。
- `audit_event`: 状态变化记录。

### 16.2 Logical tools

最小 logical tools：

- `search_tickets`: 按状态、客户等级、关键词、队列查询工单。
- `get_ticket`: 查看单个工单和关联客户、备注、audit。
- `add_ticket_note`: 添加内部备注或用户可见备注。
- `update_ticket_priority`: 修改优先级并记录 audit。
- `assign_ticket`: 分配队列或负责人并记录 audit。
- `resolve_ticket`: 关闭工单并记录 resolution note。

第一实现的 required surface：Python callable。

第一实现的 planned-but-deferred surfaces：CLI、HTTP、MCP。它们必须出现在 `SurfacePlan` 中，但可以标记为 `deferred`。

### 16.3 Fixture tasks

首个 task set 至少包含：

1. 查询某个 VIP 客户的开放退款相关工单，并给目标工单添加内部备注。
2. 找到超时未处理且高优先级的工单，将其分配给指定队列。
3. 根据工单详情判断优先级不足的情况，提升优先级并留下 audit。
4. 只读查询：回答某客户当前有多少开放工单和最高优先级。
5. 强依赖任务：先搜索目标工单，再读取详情，再基于详情关闭或转派。

### 16.4 Fixture verifier

每个状态变化任务必须有 deterministic verifier：

- 对 initial snapshot 和 final snapshot 做差异检查。
- 检查目标记录被修改。
- 检查非目标记录未被修改。
- 检查 audit_event 存在且字段匹配。
- 检查备注或 resolution 内容满足结构化要求。

只读任务 verifier 可以检查 final answer，也可以检查无状态变化。

### 16.5 Fixture 非目标

`support-desk-lite` 不要求：

- 真实客服系统集成。
- 网络服务。
- MCP server。
- AWM 样本导入。
- RL rollout 或 reward export。

## 17. Release 和训练/评估消费

Release package 面向 consumer，但 consumer 不属于核心。

最小 release 输出：

- `release-manifest.yaml`: 包版本、artifact hash、surface、fixture、task、verifier 索引。
- `task-records.jsonl`: 每行一个任务记录，使用本项目字段，不使用 AWM JSONL 作为标准。
- `verifier-records.jsonl`: 每行一个 verifier contract。
- `consumer-index.yaml`: 描述如何枚举任务、reset 环境、调用 surface、运行 verifier、收集 trace。
- `replay-plan.yaml`: 描述 deterministic replay 所需输入、seed、状态快照和预期 gate。

训练/评估 consumer 可以读取 release package 后做格式转换，例如转成某个 RL 或 eval 框架需要的数据集。转换器是 consumer adapter，不是环境生成核心。

## 18. 验收标准

本文冻结的第一实现切片使用以下文档验收标准作为 runtime implementation 的进入门槛。

文档验收：

- 阶段边界已定义，并且每个阶段有输入、输出、LLM/agent 边界、gate 和反馈边。
- artifact contracts 已覆盖 need、source evidence、knowledge、environment、tool graph、task、surface、verifier、feasibility、implementation request、generated environment bundle、package plan、release、gate record、review record、replay plan、consumer index、agent invocation record 和 agent backend config。
- agent-backed research/code nodes 已有可运行的 `AgentInvocationRecord`、backend registry 和 backend-neutral `AgentBackend` 调用机制，允许通过 Codex SDK/CLI、search agent 等 adapter 调研 MCP、CLI、API、SDK 文档或 repo，但核心不绑定单一 SDK。
- deterministic/static gates 已定义，并说明 LLM 不能直接放行 gate。
- 关键节点独立 review 已定义，且 review 输出进入 `ReviewRecord`，用于确认没有偏离任务需求。
- source discovery 策略覆盖 PRD、repo、MCP、CLI、API/SDK docs、database/schema、本地资料和 AWM 样本。
- task generation 策略包含 dependency path、自然请求、leakage filter、solver/filter 和 verifier refs。
- surface-neutral package format 已定义。
- Python、CLI、HTTP、MCP surface 边界已定义，并保持 logical tool 与 concrete surface 分离。
- 首个 runnable fixture 已定义为非 AWM 的 `support-desk-lite`。
- release format 已说明如何被训练/评估 consumer 使用，且没有绑定具体训练框架。
- 文档明确保留 AWM 背景边界，不把 AWM JSONL、MCP 或数据结构设为目标架构或默认 schema。

后续实现验收：

- 第一条 runtime vertical slice 已按以上文档验收进入实现；后续代码必须继续满足这些验收项。
- Goal 02-04 已经把 `support-desk-lite` 扩展到 rollout/training consumer、online runtime、HTTP wrapper 和 environment CLI fixture。这些能力只能作为 fixture/downstream consumer 回归，不代表通用环境生成已经完成。
- Goal 05 已打开 pipeline 结构：pipeline runner、node registry、artifact store、source connector、knowledge extractor、synthesis node、implementation/code-agent node、build/check/replay gate 和 release consumer 必须分层明确。
- 后续实现不得继续把新能力塞进硬编码 `support-desk-lite` workflow，除非同时说明它只是 fixture node set。
- Goal 06 已通过第二个本地 source family 检验 pipeline 复用性；不得把该结果误判为通用环境生成。
- Goal 07 已让 `project-board-lite` 从 source-grounded artifacts 生成 verified executable bundle；Goal 08 已让同一领域通过 backend-neutral `AgentBackend` 生成 verified agent-backed bundle。不得把 deterministic template/codegen 或当前 project-board-specific agent mock/process path 误判为通用 agent code generation。
- 任何实现 PR 都必须保留现有 `awm` CLI 行为，除非用户明确要求改动。
- 不得恢复 `awmx` demo 作为主线。
- 不得继续扩展真实训练、GPU/Ray/vLLM/SGLang、通用 shell executor 或外部认证服务作为下一步；环境生成流水线内部的 `AgentBackend` 调用机制和 code-agent 插槽属于结构收敛范围。
