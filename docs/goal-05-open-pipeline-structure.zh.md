# Goal 05: 打开真实生成流水线结构

本文定义第五条 Goal 模式任务。它不是继续扩展 `support-desk-lite` runtime，也不是一次性实现万能环境生成器。它的目标是把已经跑通的硬编码 vertical slice 打开成可维护、可替换、可观察的真实 pipeline 结构。

## 1. 任务定位

当前已经完成的内容可以证明：

```text
hardcoded support-desk-lite fixture
  -> S0-S11 artifacts
  -> deterministic gates / reviews
  -> release package
  -> replay / verifier
  -> rollout / reward / training export consumer
  -> online runtime / HTTP wrapper / environment CLI surface
```

但这仍然不是通用环境生成。主要问题是：

- S1-S7 多数 artifact 仍由 `workflow.py` 中的固定方法直接生成。
- source evidence 没有真正约束下游 spec/task/verifier。
- code generation / implementation 还没有作为正式 pipeline node 进入结构。
- runtime 和 consumer 已经比上游生成能力走得更远，容易误判系统已经完成。

Goal 05 的定位是结构收敛：

```text
hardcoded fixture workflow
  -> pipeline runner
  -> node registry
  -> artifact store
  -> source connector / extractor / synthesis nodes
  -> implementation/code-agent node slot
  -> build/check/replay gate
  -> release consumers
```

## 2. 用户目标重述

用户要的是 Agent-World-like 的 loop-engineering 环境生成系统：

```text
EnvironmentNeed / CapabilityGap / DomainSeed / PRD / repo / MCP / CLI / API docs / SDK docs
  -> source discovery
  -> knowledge extraction
  -> environment specification
  -> tool graph
  -> task generation
  -> surface planning
  -> verifier planning
  -> feasibility filtering
  -> implementation request
  -> code-agent or deterministic implementation
  -> checks / replay / verifier
  -> release package
  -> rollout / eval / training consumers
```

LLM、Codex、search agent、deep-search、mini-swe-agent 或 OpenAI-compatible model 可以参与 search、extract、synthesize、review、judge、implement，但只能作为显式 `AgentBackend` node 接入，必须有输入、输出、预算、权限、trace、artifact refs 和 gate evidence。

## 3. 本 Goal 要实现什么

### 3.1 Pipeline Runner

新增或整理一个 pipeline 层，用于表达一次环境生成 run。

建议对象：

- `PipelineRunConfig`
- `PipelineRunRecord`
- `PipelineNode`
- `PipelineNodeResult`
- `PipelineContext`

要求：

- S0-S11 不再只能由单个硬编码 workflow class 直接顺序调用。
- 每个 stage 可以注册不同 node implementation。
- 每个 node 明确声明 input artifact types、output artifact type、allowed agent backend、gate ids 和 failure policy。
- 当前 `support-desk-lite` 可以作为默认 fixture node set 保留。

### 3.2 Artifact Store

建立明确 artifact store 边界。

要求：

- artifact、gate records、review records、agent invocation records、trace refs 和 package refs 都通过统一 store 写入。
- store 第一版可以是本地目录 / JSON / YAML，不需要数据库。
- 不能依赖 prompt-only memory。
- package assembly 从 store 读取 accepted artifacts，而不是从散落的对象状态拼接。

### 3.3 Node Registry

新增 node registry 或等价机制。

至少区分：

- input normalization node。
- source discovery node。
- knowledge extraction node。
- environment spec synthesis node。
- tool graph synthesis node。
- task generation node。
- surface planning node。
- verifier planning node。
- feasibility node。
- implementation request node。
- implementation/code-agent node。
- package/release node。

第一版不要求每个 node 都是真实智能实现，但必须把 fixture node 和 future real node 的边界拆开。

### 3.4 Source Connectors

实现最小真实 source connector。

第一版至少支持本地文件：

- markdown PRD。
- CLI help text。
- JSON/YAML schema 或 examples。

输出必须进入 `SourceEvidenceIndex`，包含：

- source path。
- source kind。
- hash。
- section / line / anchor refs。
- license/auth/network/security note。
- extractable object candidates。

不要求默认跑真实网络搜索。真实 search 可以作为可选 agent backend smoke path。

### 3.5 Knowledge Extractor

实现 source-grounded knowledge extraction。

要求：

- 从 `SourceEvidenceIndex` 读取真实 source refs。
- 产出 `KnowledgePack`。
- state objects、operations、business rules 必须带 source refs。
- 缺少 source ref 的内容只能标记为 `inferred`，且不能单独通过 feasibility。
- 增加负例：source 中删除某个 operation 后，下游 gate 必须失败或进入 `needs_human`。

### 3.6 Source-grounded Synthesis

收紧 S3-S7。

要求：

- `EnvironmentSpec` 的 state entities 和 logical tools 必须来自 `KnowledgePack`。
- `LogicalToolGraph` 的 reads/writes/parameters 必须能追溯到 operations/state objects。
- `TaskSet` 的 allowed tools 和 dependency path 必须引用 known logical tools。
- `VerifierPlan` 的 checks 和 evidence_refs 必须引用 task、state object、operation 或 generated implementation evidence。
- 不允许无视 S1/S2 继续输出固定 support-desk constants。

第一版可以仍然只支持 support-desk-lite 这一个 domain，但必须证明 source evidence 变化会影响下游结果或 gate。

### 3.7 Implementation / Code-agent Node Slot

加入正式 implementation node 边界。

该 node 接收：

- accepted S0-S8 artifacts。
- `ImplementationRequest`。
- target package layout。
- TDD requirements。
- allowed surfaces。
- verifier plan。

它可以有两种实现：

- deterministic fixture implementation：用于 CI 和本地稳定测试。
- agent-backed implementation：通过 `AgentBackend` 调用 process agent、Codex CLI、OpenAI-compatible model 或其他 adapter。

要求：

- agent-backed 路径必须产生 `AgentInvocationRecord`。
- 真实 code agent 只能在隔离 workdir 中写代码。
- 输出不能直接进入 release；必须经过 build/check/replay gate。
- 默认 deterministic tests 不依赖网络、真实 API key 或真实模型。

### 3.8 Build / Check / Replay Gate

实现或整理 code implementation 后的检查阶段。

至少记录：

- static check command。
- test command。
- replay command。
- verifier result。
- package validation result。
- failure class 和 recovery suggestion。

失败不能被 LLM 直接改成通过。

## 4. 本 Goal 不做什么

不要实现：

- 真实 trainer loop。
- GPU/Ray/vLLM/SGLang worker。
- 真实外部认证服务。
- 通用 shell executor。
- MCP server 全量实现。
- 真实网络 search 作为默认测试路径。
- 把 Codex SDK、deep-search、mini-swe-agent 或某个 OpenAI model 写成 core dependency。
- 重写或删除 `support-desk-lite` 已有可运行链路。

可以做：

- 可选 live smoke test，但必须在缺少 env/network/model 时跳过。
- deterministic fake codegen，但必须保留 agent-backed codegen slot 和 invocation records。
- 本地 PRD / CLI help / schema fixture，用于证明 source-grounded pipeline。

## 5. 验收标准

完成后应满足：

- `uv run pytest` 全部通过。
- 旧 `awm` CLI 行为不破坏。
- `support-desk-lite` full chain 仍然通过。
- 有明确 pipeline runner / node registry / artifact store 边界。
- `support-desk-lite` 被标注为 fixture node set，不再被误称为通用 generator。
- 至少一个真实本地 source connector 能读取 PRD 或 CLI help 文件并生成 `SourceEvidenceIndex`。
- `KnowledgePack` 至少部分字段来自真实 source refs，而不是纯 Python 常量。
- 有负例测试证明：source evidence 缺失 operation/state/rule 时，S3-S7 或 gate 会失败。
- 有 implementation/code-agent node slot，默认 deterministic path 可跑，agent-backed path 可配置并产生 `AgentInvocationRecord`。
- build/check/replay evidence 进入 artifact 或 run record。
- README / docs 明确当前真实性等级：pipeline structure opened，仍未完成通用环境自动生成。

## 6. 当前实现状态

本 Goal 的当前代码状态是 **pipeline structure opened**：

- `agent_world.pipeline` 定义 `PipelineRunConfig`、`PipelineRunRecord`、`PipelineNode`、`PipelineNodeResult`、`PipelineContext`、`NodeRegistry` 和 `PipelineRunner`。
- `support-desk-lite` 通过 fixture node registry 接入 S0-S11，并在 S9 与 S10 之间增加正式 implementation/code-agent node slot。
- `agent_world.store.ArtifactStore` 统一记录 artifact、gate record、review record、agent invocation、trace 和 package ref；第一版使用本地目录 YAML/JSONL。
- `agent_world.sources.LocalSourceConnector` 可读取本地 PRD / CLI help / schema-like 文件，输出带 path、hash、section/line refs 的 `SourceEvidenceIndex`。
- `SupportDeskLiteKnowledgeExtractor` 从 `SourceEvidenceIndex` 提取 `KnowledgePack`，state objects、operations 和 business rules 均带 source refs。
- S3-S7 的 support-desk-lite spec、tool graph、task set、surface plan 和 verifier plan 从 `KnowledgePack` 派生；source 缺少 operation 或 rule 时，负例测试会触发 gate fail 或 `needs_human`。
- implementation node 默认 deterministic fixture path，运行本地 callable smoke 和 deterministic verifier，记录 build/check/replay evidence；agent-backed path 通过 `AgentBackend` 写 `AgentInvocationRecord`，未通过 build/check/replay 前不会进入 release。

仍然是 fixture 的部分：

- 当前真实 source-grounded synthesis 只覆盖 `support-desk-lite`。
- 默认 implementation 仍复用已有 fixture runtime 代码，不是通用 code generation。
- package/release consumer 仍主要服务 Goal 02-04 回归。
- 没有默认真实网络 search、真实 trainer loop、GPU/Ray/vLLM/SGLang worker、MCP 全量实现或 generic shell executor。

下一步不应继续扩展 `support-desk-lite`。应进入 `docs/goal-06-second-source-family.zh.md`，增加第二个本地 source family，例如 CLI help + schema/examples，用同一套 `PipelineRunner`、`NodeRegistry`、`ArtifactStore` 和 gate/review 机制跑通，并用负例证明 source evidence 缺失会阻止 release。

## 7. 历史 Goal 05 Prompt

```text
阅读 AGENTS.md、README.md、docs/agent-world-environment-generation.zh.md、docs/goal-05-open-pipeline-structure.zh.md。

目标：打开真实环境生成流水线结构，而不是继续扩展 support-desk-lite runtime。当前 support-desk-lite full chain 可以保留，但必须被整理为 fixture node set。新增或重构 pipeline runner、node registry、artifact store、source connector、knowledge extractor、source-grounded synthesis、implementation/code-agent node slot 和 build/check/replay gate 边界。

关键要求：
1. S0-S11 不能只能由单个硬编码 workflow class 直接产出常量 artifact；至少要有可替换 node registry 或等价结构。
2. 新增最小本地 source connector，读取 PRD markdown、CLI help text 或 schema fixture，生成带 path/hash/section refs 的 SourceEvidenceIndex。
3. KnowledgePack 必须从 SourceEvidenceIndex 提取，并带 source refs。
4. S3-S7 必须被 source evidence 约束；不能无视 S1/S2 输出固定 support-desk constants。
5. 增加负例测试：source 中缺少 operation/state/rule 时，下游 gate 必须失败或 needs_human。
6. 新增 implementation/code-agent node slot。默认 deterministic path 可在 CI 中运行；agent-backed path 必须通过 AgentBackend，并写 AgentInvocationRecord。
7. code implementation 输出必须经过 build/check/replay gate 后才能进入 release。
8. 保持 Goal 02-04 已有 full chain、online runtime、environment_cli、HTTP wrapper 和旧 awm CLI 不破坏。

不要做：
- 不接真实训练框架。
- 不实现 GPU/Ray/vLLM/SGLang。
- 不实现 generic shell executor。
- 不把 Codex SDK、deep-search、mini-swe-agent 或某个 OpenAI model 绑定进 core。
- 不把真实网络 search 作为默认测试依赖。

验收：
- PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -p no:cacheprovider
- support-desk-lite full chain 仍通过。
- 新 source connector / extractor / source-grounded gate 有正反测试。
- implementation/code-agent node slot 有 deterministic test 和 AgentInvocationRecord 覆盖。
- README/docs 更新当前真实性等级和下一步边界。
```
