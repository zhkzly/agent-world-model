# Agent World 环境生成任务定义

本文是当前任务源文档。若旧实现、旧会话记录或旧计划与本文冲突，以本文为准。

## 1. 用户真正要做什么

本项目要实现一个类似 Agent-World / AW 方向的环境生成系统。

用户给系统一个输入，例如：

- 环境需求或能力缺口。
- 行业、工具、PRD、repo、API、MCP server、CLI、SDK 文档或数据库 schema。
- 一组本地资料、可执行工具、服务说明或评测目标。

系统应自动推进环境生成，而不是让人每次手写一次性 prompt。目标输出不是方案文档，而是可复现、可验证、可发布、可被训练/评估流程消费的可执行环境包。

这里的“环境”应理解为后端/runtime 代码包。环境包至少应逐步包含：

- 状态转移逻辑。
- seed/state fixture。
- logical tool 到 concrete surface 的绑定。
- 任务集合。
- deterministic verifier。
- check/replay 脚本。
- release metadata。
- 后续 rollout/training/eval consumer 能稳定加载的入口。

Codex、OpenAI-compatible codegen、mini-swe-agent、Claude Agent SDK 或其他 code agent 可以根据 source evidence 和 generated specs 写这些后端代码，但它们只能作为显式 implementation/repair 节点。是否可发布由框架侧 build/check/replay、independent verifier 和 bounded repair gate 决定。

## 2. AWM 的位置

AWM 只作为背景知识和可参考素材，不是本项目边界。

可以参考 AWM 的部分：

- code-driven environment generation。
- database/file-backed state transition。
- scenario / task / tool / verifier 的组合方式。
- execution feedback 用于修正环境代码和 verifier。
- 本地样本可作为 discovery source。

不能把 AWM 当成要求：

- 不能复现 AWM 论文作为主目标。
- 不能把 AWM JSONL、MCP 暴露形式或数据结构写死为通用格式。
- 不能假设所有环境都来自 AWM 样本。
- 不能让 AWM 的 MCP 形态限制 CLI、Python、HTTP 等 surface。

## 3. 当前活动架构

当前 active slice 位于 `agent_world/`，核心入口是 `run_request_driven_pipeline()`。

主路径：

```text
raw request / source paths
  -> DomainPlan
  -> StrategySelection
  -> NeedSpec
  -> SourceEvidenceIndex
  -> KnowledgePack
  -> EnvironmentSpec
  -> LogicalToolGraph
  -> TaskSet
  -> SurfacePlan
  -> VerifierPlan
  -> FeasibilityReport
  -> ImplementationRequest
  -> AgentBackend generated candidate bundle
  -> GeneratedEnvironmentBundle
  -> IndependentVerificationReport
  -> EnvironmentPackagePlan
  -> ReleaseManifest
  -> envpkg/runtime/generated/<bundle_id>/
```

关键约束：

- 成功路径必须由上游 artifact 派生，不允许靠固定环境 ID、固定 task ID、固定 replay case 或手动领域 registry 放行。
- `PipelineRunner()` 默认使用 request-driven registry。
- request-driven implementation 必须走 `AgentBackend`，不能使用本地 deterministic template 代替真实 candidate bundle。
- agent 只负责在隔离工作区写候选文件；框架负责验证、repair budget 和 release 决策。
- generated `check_replay.py` 只是辅助证据，不是 release authority。

## 4. Artifact 与 Gate

稳定状态必须落在 artifact、manifest、typed config、trace record 或 package 文件中，不能只存在 prompt 记忆里。

每个阶段输出结构化 artifact：

- 输入 artifact refs。
- producer。
- source stage。
- hash。
- status。
- gate/review records。

Gate 的职责是阻止上下游漂移：

- source evidence 是否存在。
- knowledge 是否可追溯。
- environment spec 是否有 reset/isolation。
- logical tool graph 是否与 environment spec 一致。
- task 是否可解、可验证、无实现细节泄漏。
- surface 是否绑定 logical tools。
- verifier 是否包含正反例、trace/dependency path 输入和 deterministic checks。
- feasibility 是否汇总上游 gate。
- package/release 是否只引用已接受 artifact。

## 5. Source Discovery 与 Knowledge Extraction

Source 可以来自：

- raw request。
- 本地 PRD / markdown。
- CLI help / man page。
- API docs / SDK docs。
- repo。
- MCP server 描述。
- database schema。
- HTTP/local service 文档。
- AWM sample。

第一版默认不做 live crawler。没有显式配置时，request-driven path 使用 raw request 和可选 local source paths，生成本地 synthetic state 环境。

Source discovery 和 knowledge extraction 可以由 LLM/agent 辅助，但必须作为显式 workflow node：

- 通过 `AgentBackend` / `AgentInvocationRecord` 调用。
- 记录输入 artifact、权限、网络/认证需求、预算、输出 artifact、trace 和失败原因。
- 输出回写为 `SourceEvidenceIndex`、`KnowledgePack`、`ReviewRecord` 或 failure packet。

## 6. Task、Tool 与 Surface

任务不是自然语言字符串。每个 task 至少包含：

- natural user request。
- target capability。
- initial state refs。
- expected state delta 或 expected answer。
- allowed logical tools。
- forbidden leakage。
- dependency path。
- verifier refs。
- machine-readable `framework_replay.tool_calls`。

logical tool 与 concrete surface 必须分离：

- Python callable。
- CLI。
- HTTP。
- MCP。

第一版只要求 generated Python callable surface 可执行。其他 surface 可以先是 descriptor，但不能把 generic shell executor 冒充环境工具 surface。

## 7. Implementation / Code Agent

Implementation node 需要生成可执行 bundle，而不是只生成规格。

候选 bundle 必须包含：

- `runtime.py`
- `seed_state.json`
- `verifier.py`
- `surface_descriptor.json`
- `check_replay.py`
- `build_manifest.yaml`
- `candidate_manifest.json` 或等价 agent output manifest

Agent backend 可以是：

- `openai_codegen`
- `code_agent_runner`
- `codex_cli_runner`
- 其他符合 `AgentBackend` contract 的 runner

要求：

- 只在隔离 workdir 写文件。
- candidate manifest 使用相对路径。
- 拒绝绝对路径、`..`、symlink escape、未声明文件、hash mismatch、secret leak。
- live model/network smoke 必须显式配置；普通测试不能依赖外部模型、网络或 credential。
- API key、base URL 中的 secret、auth token 不得写入 artifact 或 trace 明文。

## 8. Independent Verifier 与 Repair Loop

框架侧 independent verifier 是 release authority 的核心。

它必须：

- 直接 import/load generated `runtime.py`、`verifier.py`、`seed_state.json`。
- 从 accepted `TaskSet.framework_replay.tool_calls` 执行正例。
- 构造负例，要求 verifier 拒绝。
- 检查 trace 顺序等于 dependency path。
- 检查 state delta 或 final answer 证据。
- 返回结构化 `framework_check_observation`。

失败后进入 bounded repair：

- `PipelineRunConfig.max_repair_attempts` 或 `AGENT_WORLD_MAX_REPAIR_ATTEMPTS` 控制预算。
- 每次失败生成 failure packet。
- failure packet 包含 manifest/path/hash/check failure、failed task ids、traceback、expected/actual evidence 和 recovery suggestion。
- repair 仍通过同一个 `AgentBackend`。
- agent 不能控制 pipeline flow，也不能自己决定 release。

## 9. Package 与 Consumer

通过 release gate 后，生成环境被复制到 package-relative 稳定路径：

```text
envpkg/runtime/generated/<bundle_id>/
envpkg/release/generated-runtime-index.yaml
```

`run_packaged_generated_bundle_check(package_dir)` 是 downstream smoke consumer。它从 package 内读取 runtime index、执行 generated check，并再次运行 framework independent verifier。

这证明后续模块可以加载 packaged generated backend/runtime，但不等于已经完成部署、online rollout、SFT/GRPO 采样或训练反馈闭环。

## 10. 训练与评估的位置

训练不是当前系统的核心起点。训练/评估系统只能消费已 release 的环境：

- environment package。
- task set。
- verifier specs。
- rollout traces。
- reward/eval records。
- online runtime contract。

verl、LLaMA-Factory、OpenRLHF、TRL 或自定义训练框架都是 consumer，不是 core dependency。

后续可以把部署、采样、SFT/GRPO、训练结果反馈到新环境构造表达为外层 loop，但这些必须作为显式 feedback edge，不能让 trainer 直接改写环境生成合约。

## 11. 当前真实性等级

当前能声称：

- request-driven S0-S11 artifact path 已经存在。
- agent-backed candidate bundle path 已经存在。
- machine-readable replay contract 已经存在。
- framework independent verifier 已经按 accepted tasks 执行正反例。
- bounded repair packet 已经存在。
- verified generated runtime 可以复制到 package-relative path 并被 consumer check 加载。
- `awm` CLI 仍作为兼容入口保留。

当前不能声称：

- 已经实现高质量通用环境自动生成。
- 已经实现真实网络 search/discovery。
- 已经实现通用 verifier synthesis。
- live code agent 默认能稳定发布任意 request。
- 已经实现通用 rollout/online runtime adapter。
- 已经接入真实 RL trainer。
- 已经实现训练结果自动反向迭代环境生成。

## 12. 开发约束

- 使用 `uv` 运行 Python 命令。
- 保留 `awm` CLI 兼容，除非用户明确要求改动。
- 不要新增硬编码 smoke domain 来绕过 request-driven path。
- 不要把 deterministic template、mock backend 或本地 helper 伪装成真实 code agent。
- 不要把 generated self-check stdout 当作最终 verifier。
- 不要把 prompt-only memory 当成项目状态。
- 文档、测试和代码若与本文冲突，应删除或重写。
