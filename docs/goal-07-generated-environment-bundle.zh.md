# Goal 07: Generated Environment Bundle

本文定义第七条 Goal 模式任务。Goal 06 已经证明第二个本地 source family 可以通过同一套 pipeline 结构运行，但它仍然复用领域 fixture runtime。Goal 07 的目标是把 implementation 阶段推进到真正生成可执行环境文件，并用这些生成文件完成 build/check/replay。

## 1. 任务定位

当前状态：

```text
project-board-lite CLI help + schema + examples
  -> SourceEvidenceIndex
  -> KnowledgePack
  -> S3-S7 source-grounded artifacts
  -> ImplementationRequest
  -> deterministic fixture runtime smoke
  -> package/release plan
```

这还不是环境代码生成。Goal 07 必须变成：

```text
project-board-lite accepted artifacts
  -> ImplementationRequest
  -> GeneratedEnvironmentBundle
     - generated runtime code
     - generated seed/state fixture
     - generated verifier
     - generated surface descriptor
     - generated tests/check script
     - build manifest
  -> build/check/replay from generated files
  -> release/package plan references verified bundle
```

## 2. 核心原则

- 环境生成不能停在 JSON/YAML artifact。
- implementation node 必须写出可执行文件。
- verified 必须从 generated files 加载或启动环境。
- release 不得只引用旧 fixture runtime。
- deterministic template/codegen 可以作为 CI 默认路径；agent-backed codegen 通过 `AgentBackend` 可插拔接入。
- Codex SDK、Codex CLI、OpenAI-compatible、deep-search 等只能是 backend adapter，不能成为 core 依赖或唯一实现。

## 3. 本 Goal 要实现什么

### 3.1 GeneratedEnvironmentBundle Contract

新增 `GeneratedEnvironmentBundle` 或等价 build manifest。

必填信息建议包括：

- `bundle_id`
- `environment_id`
- `source_artifact_ids`
- `implementation_request_id`
- `build_dir`
- `generated_files[]`: path、kind、sha256、source_refs
- `runtime_entrypoint`
- `seed_fixture_ref`
- `verifier_entrypoint`
- `surface_descriptors`
- `check_commands[]`
- `replay_commands[]`
- `build_check_replay_records[]`
- `status`: `accepted`, `fail`, `needs_human`

`generated_files.kind` 至少支持：

- `runtime_code`
- `seed_fixture`
- `verifier_code`
- `surface_descriptor`
- `test_or_check`
- `build_manifest`

### 3.2 Deterministic Template/Codegen Path

默认 CI 路径可以先用 deterministic generator，不要求真实 LLM 写代码。

但它必须：

- 在 isolated build dir 写文件，例如 `build/generated/project-board-lite/`。
- 写出 runtime module，而不是 import `agent_world.fixtures.project_board_lite`。
- 写出 seed/state fixture。
- 写出 verifier module。
- 写出 surface descriptor。
- 写出 check/replay script 或 Python check entrypoint。
- 记录所有 generated file hash。

可以允许生成代码内容来自模板，但模板输出必须是独立可加载文件。

### 3.3 Build / Check / Replay

新增或收紧 build/check/replay gate。

要求：

- 从 generated runtime module import 环境。
- 从 generated seed fixture reset 环境。
- 调用 generated Python callable surface 执行至少一个成功任务。
- 运行 generated verifier，成功任务必须 pass。
- 运行一个负例，generated verifier 必须 fail。
- 如果 generated surface descriptor 标记 CLI implemented，则执行 generated CLI `--help`，再执行至少一个成功命令和一个失败命令，使用 `subprocess.run(argv, shell=False)`。
- 如果 HTTP/MCP 标记 implemented，则必须启动并探测；否则只能 deferred。

build/check/replay records 必须写入 `ArtifactStore`，并被 S10/S11 package/release plan 引用。

### 3.4 Agent-backed Codegen Slot

agent-backed implementation path 必须继续存在。

要求：

- 通过 `AgentBackend` 调用。
- 写 `AgentInvocationRecord`。
- agent 输出只能写入 isolated workdir。
- agent 输出不能直接 release。
- 必须经过同样的 build/check/replay。

默认测试不能依赖真实网络、API key 或模型。可以用 mock/process agent 只验证 wiring。

### 3.5 Release / Package 引用

S10/S11 不能只引用 `ImplementationRequest`。

要求：

- `EnvironmentPackagePlan` 或 release manifest 引用 verified bundle id。
- release known_limits 明确当前 bundle 是 deterministic generated bundle，不是通用 agent codegen。
- 如果 bundle check fail，不得生成 `ReleaseManifest`。

## 4. 不做什么

不要实现：

- 真实 trainer loop。
- GPU/Ray/vLLM/SGLang。
- 通用 shell executor。
- MCP 全量 server，除非该 surface 被单独实现并 verified。
- 真实网络 search 作为默认路径。
- 第三个领域。

不要误判：

- deterministic template/codegen 不等于通用代码生成。
- generated Python surface 不等于 CLI/MCP/HTTP 都已实现。
- agent-backed path 有 invocation record 不等于 agent 生成代码已经 verified。

## 5. 验收标准

完成后应满足：

- `uv run pytest` 全部通过。
- 旧 `awm` CLI 行为不破坏。
- `support-desk-lite` full chain 仍然通过。
- `project-board-lite` pipeline 仍然通过。
- implementation node 生成 isolated environment bundle。
- bundle 包含 runtime code、seed/state fixture、verifier code、surface descriptor、check/replay entrypoint 和 build manifest。
- build/check/replay 从 generated files 构造环境并执行。
- 成功任务 verifier pass。
- 负例 verifier fail。
- generated file hashes 被记录。
- package/release plan 引用 verified bundle。
- 删除或破坏 generated runtime/verifier/check file 时，build/check/replay fail，且不得 release。
- agent-backed implementation slot 仍写 `AgentInvocationRecord`，但未通过 check 不 release。

## 6. 当前实现状态

当前代码状态是 **generated environment bundle verified**：

- `GeneratedEnvironmentBundle` 已进入 artifact contract 和 validator，记录 `bundle_id`、source artifact refs、implementation request ref、generated file hashes、check/replay commands 和 build/check/replay records。
- `project-board-lite` deterministic implementation node 写出 isolated build dir：`runtime.py`、`seed_state.json`、`verifier.py`、`surface_descriptor.json`、`check_replay.py`、`build_manifest.yaml`。
- generated runtime/verifier/check files 自包含 project-board state、reset、tool 行为和 deterministic verifier，不通过 import `agent_world.fixtures.project_board_lite` 冒充 generated environment。
- build/check/replay 使用 `subprocess.run(argv, shell=False)` 执行 generated `check_replay.py`，并从 generated files import runtime/verifier，执行一个成功任务和一个负例。
- 成功任务 verifier pass，负例 verifier fail；破坏 generated runtime、verifier 或 check entrypoint 时 implementation fail，pipeline 不生成 `ReleaseManifest`。
- S10/S11 package/release 引用 verified bundle；release known limits 标明这是 deterministic generated bundle，不是通用 agent codegen。
- agent-backed implementation slot 仍保留并写 `AgentInvocationRecord`；agent output 未通过同一 build/check/replay gate 前不能 release。

仍然是 deterministic/domain-specific 的部分：

- project-board bundle 由领域模板/codegen 生成，不是通用 planner/codegen strategy。
- 当前只验证 generated Python callable surface；CLI/HTTP/MCP 对 project-board 仍只能 deferred 或 descriptor-only，除非单独实现并验证。
- Goal 02-04 的 rollout/training/online runtime/HTTP/environment CLI 仍是 `support-desk-lite` 回归，不代表第二领域或通用 runtime consumer 已完成。

## 7. 给 Goal 模式的建议 Prompt

```text
阅读 AGENTS.md、README.md、docs/agent-world-environment-generation.zh.md、docs/goal-06-second-source-family.zh.md、docs/goal-07-generated-environment-bundle.zh.md。

目标：实现 Goal 07。不要再只复用 fixture runtime。基于 project-board-lite 已有 SourceEvidenceIndex、KnowledgePack、S3-S7 artifacts 和 ImplementationRequest，让 implementation node 写出 isolated GeneratedEnvironmentBundle，并从 generated files 执行 build/check/replay。

实现要求：
1. 新增 GeneratedEnvironmentBundle 或等价 build manifest contract。
2. implementation deterministic path 必须在 isolated build dir 写出 runtime code、seed/state fixture、verifier code、surface descriptor、check/replay entrypoint。
3. generated runtime 不能 import agent_world.fixtures.project_board_lite 作为环境实现；必须由 generated files 自己定义 state/reset/tool/verifier 行为。
4. build/check/replay 必须从 generated files import 或启动环境。
5. 至少执行一个成功任务，generated verifier 必须 pass。
6. 至少执行一个负例，generated verifier 必须 fail。
7. 记录 generated file hashes、source artifact refs、implementation request ref、check commands 和 check results。
8. S10/S11 package/release plan 必须引用 verified bundle；bundle check fail 不得 release。
9. agent-backed implementation slot 保留，通过 AgentBackend 写 AgentInvocationRecord；agent 输出未通过 build/check/replay 不得 release。
10. 保持 support-desk-lite full chain、Goal 02-06 测试、environment_cli、HTTP wrapper 和旧 awm CLI 不破坏。

不要做：
- 不实现真实 trainer。
- 不实现 GPU/Ray/vLLM/SGLang。
- 不实现 generic shell executor。
- 不把 Codex SDK、deep-search、mini-swe-agent 或某个模型绑定进 core。
- 不把真实网络 search 作为默认测试依赖。
- 不新增第三个领域。
- 不通过 import 现有 project_board_lite fixture runtime 冒充 generated environment。

验收：
- PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -p no:cacheprovider
- support-desk-lite full chain 仍通过。
- project-board-lite pipeline 正向通过。
- generated environment bundle 文件存在且 hash 被记录。
- build/check/replay 从 generated files 构造环境并 verified。
- 破坏 generated runtime/verifier/check 文件会 fail 且不会 release。
- README/docs 更新当前真实性等级和仍未完成边界。

完成后请输出：
- PASS / PASS WITH RISKS / FAIL
- 改动文件列表
- GeneratedEnvironmentBundle 文件结构
- build/check/replay 如何从 generated files 执行
- 哪些内容仍是 deterministic template/domain-specific
- 如何运行完整验证
- 下一 Goal 建议
```
