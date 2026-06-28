# Goal 06: 第二个本地 Source Family 验证

本文定义第六条 Goal 模式任务。Goal 05 已经把 `support-desk-lite` 从单个硬编码 workflow 打开成 pipeline runner、node registry、artifact store、source connector、source-grounded extractor、implementation/code-agent slot 和 build/check/replay gate。Goal 06 的目标是验证这个结构可以承载第二种本地 source family，而不是只服务 `support-desk-lite`。

## 1. 任务定位

当前状态：

```text
support-desk-lite PRD
  -> LocalSourceConnector
  -> SourceEvidenceIndex
  -> SupportDeskLiteKnowledgeExtractor
  -> KnowledgePack
  -> support-desk fixture node registry
  -> deterministic implementation smoke
  -> pipeline store records
```

Goal 06 要增加第二个本地 source family，推荐使用：

```text
CLI help text + JSON/YAML schema + examples
```

它应该模拟真实工具生态，例如项目看板、文件管理、日历、库存、issue tracker 或文档系统。具体领域可以选择一个小而完整的本地 fixture，但必须包含：

- 至少 4 个 logical operations。
- 至少 3 个 state objects。
- 至少 3 个可验证任务，其中至少 2 个状态变更任务，至少 1 个只读任务。
- deterministic verifier。
- release/package 或 pipeline store record 可审计。

## 2. 用户目标约束

本 Goal 仍服务于长期目标：

```text
EnvironmentNeed / CapabilityGap / Source Material
  -> source discovery
  -> knowledge extraction
  -> environment spec
  -> tool graph
  -> task generation
  -> verifier planning
  -> implementation/code-agent slot
  -> build/check/replay
  -> release/consumer outputs
```

但本 Goal 不是通用万能生成器。它只证明第二种 source family 可以进入同一 pipeline 结构。

## 3. 本 Goal 要实现什么

### 3.1 第二组本地 source fixtures

新增第二个 source family，建议命名为 `project-board-lite`、`inventory-cli-lite` 或类似小领域。

至少包含：

- CLI help text，例如 `fixtures/<domain>_cli_help.txt`。
- JSON/YAML schema，例如 state entities、fields、relations。
- examples 文件，例如常见命令调用和预期行为。

要求：

- 不要把 source evidence 直接写成 Python 常量。
- `SourceEvidenceIndex` 必须包含 path、hash、source kind、section/line refs。
- CLI commands 必须被识别为 operation candidates。
- schema entities 必须被识别为 state object candidates。

### 3.2 Connector / extractor 复用

优先扩展 `LocalSourceConnector`，不要为第二领域重写一套完全独立 connector。

允许新增：

- `CliHelpExtractor`
- `SchemaKnowledgeExtractor`
- `SecondSourceFamilyKnowledgeExtractor`
- 或一个小型 generic extractor scaffold

要求：

- extractor 输入是 `SourceEvidenceIndex`。
- extractor 输出 `KnowledgePack`。
- state objects、operations、business rules 必须带 source refs。
- 没有 source refs 的内容只能标为 `inferred`，且不能单独通过 feasibility。

### 3.3 第二个 NodeRegistry

新增第二个 node registry 或 registry factory，例如：

```text
project_board_lite_node_registry()
```

它必须复用：

- `PipelineRunner`
- `PipelineRunConfig`
- `NodeRegistry`
- `PipelineNode`
- `ArtifactStore`
- gate/review 机制
- implementation/code-agent node slot

它不能复制一套新的 pipeline runner。

### 3.4 Source-grounded S3-S7

第二领域的 S3-S7 可以先是 deterministic synthesis，但必须从 `KnowledgePack` 派生：

- `EnvironmentSpec.state_entities` 来自 state objects。
- `EnvironmentSpec.logical_tools` 来自 operations。
- `LogicalToolGraph.tools` 来自 operations。
- `TaskSet.allowed_logical_tool_ids` 和 `dependency_path` 引用 known tools。
- `VerifierPlan.evidence_refs` 引用 source refs、task refs 或 implementation check refs。

必须新增负例测试：

- 删除 CLI help 中的一个 required command，pipeline 不得 release。
- 删除 schema 中的一个 required state object，pipeline 不得 release。
- 删除 verifier/rule evidence，pipeline 必须 fail 或 `needs_human`。

### 3.5 Deterministic implementation 与 agent-backed slot

第二领域可以先实现 deterministic fixture runtime，不要求真实 code agent 默认执行。

要求：

- deterministic path 必须运行一个正例任务和一个失败/负例 verifier。
- build/check/replay evidence 写入 pipeline store 或 artifact。
- agent-backed path 继续通过 `AgentBackend`，写 `AgentInvocationRecord`。
- agent output 未通过 build/check/replay gate 前不能 release。

### 3.6 Package / full-chain 边界

本 Goal 不要求把第二领域接入 Goal 02-04 的全部 rollout/training/HTTP/CLI runtime。

最低要求：

- pipeline run 成功。
- artifacts/store 可审计。
- deterministic verifier 正反例可执行。
- release planning 或 package plan 可生成。

可以选择性实现 package assembly，但不要破坏 `support-desk-lite` full chain。

## 4. 当前实现状态

Goal 06 完成时的代码状态是 **second local source family validated**；Goal 07 已在其上推进到 generated bundle：

- 第二领域选择 `project-board-lite`。
- source fixtures 包含 CLI help、YAML schema 和 examples/rules。
- `LocalSourceConnector` 识别 CLI commands、schema state objects、business rules 和 examples，并保留 path/hash/line refs。
- `ProjectBoardLiteKnowledgeExtractor` 从 `SourceEvidenceIndex` 生成带 source refs 的 `KnowledgePack`。
- `project_board_lite_node_registry()` 复用 `PipelineRunner`、`PipelineRunConfig`、`NodeRegistry`、`PipelineNode`、`ArtifactStore`、gate/review 和 implementation/code-agent slot。
- 第二领域 S3-S7 从 `KnowledgePack` 派生。
- 第二领域包含 3 个 tasks，其中 2 个状态变更、1 个只读查询。
- deterministic verifier 有正例和负例，并进入 implementation build/check/replay record。
- 删除 required CLI command、schema state object 或 rule evidence 时，pipeline fail 或 `needs_human`，不会产生 `ReleaseManifest`。
- agent-backed implementation path 仍通过 `AgentBackend` 写 `AgentInvocationRecord`，未通过 build/check/replay 不进入 release。
- Goal 07 已将 `project-board-lite` deterministic implementation 从 fixture runtime smoke 替换为 isolated `GeneratedEnvironmentBundle`，从 generated runtime/verifier/check files 执行 build/check/replay。

仍然是 fixture/domain-specific 的部分：

- `project-board-lite` 的 synthesis、task templates 和 generated bundle template 仍是领域节点，不是通用 synthesis 或通用 code generation。
- `project-board-lite` CLI help 是 source evidence，不表示已实现 project-board environment CLI runtime surface。
- Goal 07 的 deterministic generated bundle 不表示真实 agent code generation 已完成。
- Goal 02-04 的 rollout/training/online runtime/HTTP/environment CLI 仍只作为 support-desk-lite 回归保留。

## 5. 不做什么

不要实现：

- 真实网络 search 作为默认路径。
- 真实 trainer loop。
- GPU/Ray/vLLM/SGLang。
- 通用 shell executor。
- MCP server 全量实现。
- 把 Codex SDK、deep-search、mini-swe-agent 或某个 OpenAI model 绑定进 core。
- 把第二领域写成另一个完全独立、不可复用的 workflow。

不要误判：

- 第二领域跑通不等于通用环境生成完成。
- deterministic generated bundle 不等于真实 agent code generation 已完成。
- CLI help source 不等于 environment CLI runtime surface 已完成。

## 6. 验收标准

完成后应满足：

- `uv run pytest` 全部通过。
- 旧 `awm` CLI 行为不破坏。
- `support-desk-lite` full chain 仍然通过。
- 第二 source family 通过同一个 `PipelineRunner` 运行。
- 第二 source family 的 `SourceEvidenceIndex` 来自真实本地 CLI help/schema/examples 文件。
- 第二 source family 的 `KnowledgePack` 带 source refs。
- 第二 source family 的 S3-S7 从 `KnowledgePack` 派生。
- 至少 3 个第二领域任务，其中包含状态变更和只读任务。
- deterministic verifier 有正例和负例。
- 删除 required command/state/rule source evidence 时，pipeline 不得进入 release。
- agent-backed implementation slot 仍可配置，并写 `AgentInvocationRecord`。
- README/docs 更新当前真实性等级；Goal 06 对应 second local source family validated，Goal 07 对应 generated environment bundle verified，但通用/网络 discovery、通用 synthesis、真实 agent code generation 仍未完成。

## 7. 下一阶段建议

Goal 07 已推进 `GeneratedEnvironmentBundle`：implementation node 从 source-grounded artifacts 写出独立 build directory，包含 runtime code、seed/state fixture、verifier、surface descriptor 和 tests/check command，并从 generated files 执行 build/check/replay。

下一阶段应减少领域模板比例，让更通用的 planner/codegen strategy 生成 bundle，同时保持 agent-backed implementation slot、build/check/replay gate 和 release 引用边界。
