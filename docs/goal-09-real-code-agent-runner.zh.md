# Goal 09: Real Code Agent Runner

本文定义第九条 Goal 模式任务。Goal 08 补上了 `openai_codegen`：OpenAI-compatible LLM 可以返回 bundle file contents，由框架写入 isolated workdir 并验证。这仍然不是用户要求的完整 code agent 能力。

Goal 09 的目标是支持真正的 **code agent runner**：Codex CLI/SDK、mini-swe-agent、Claude Code/Agent SDK 或自定义 SWE agent 可以在隔离工作区内读取任务包、编辑文件、运行检查、根据失败反馈迭代修复，最后产出可验证的 environment bundle。

当前实现状态：已接入第一版 runner contract。`code_agent_runner` / `codex_cli_runner` 会接收 workspace packet，外部 runner 在 `generated/` 写文件并在 `agent-output/` 写 manifest/command log，框架再从 `generated/` 执行 build/check/replay。默认测试使用本地 runner fixture 证明 contract，不默认调用 live Codex/Claude/mini-swe-agent。Goal 11 已补上框架级 bounded repair loop；runner 仍可以内部自修复，但 pipeline 现在会在失败 attempt 后写 failure packet，并在 repair budget 内重新调用同一个 backend。

## 1. 为什么 Goal 08 不够

Goal 08 的 `openai_codegen` 是一个 LLM/file-content backend：

```text
prompt + artifacts
  -> LLM returns JSON files[]
  -> framework writes files
  -> build/check/replay
```

它适合小规模生成或 smoke test，但它不是完整 code agent，因为它不具备以下能力：

- 自己在工作区浏览多文件上下文。
- 自己创建/修改多个文件。
- 自己运行测试、查看失败、修复代码。
- 保留代码编辑、命令执行、失败修复的 agent trace。
- 在实现阶段进行多轮 TDD。

用户需要的是：

```text
ImplementationRequest + accepted artifacts + bundle contract
  -> code-agent workspace packet
  -> real code agent runner edits files and runs checks
  -> candidate bundle manifest
  -> framework build/check/replay gate
  -> optional bounded repair loop
  -> release only after verified
```

## 2. 概念边界

### 2.1 LLM Node

LLM node 可以做：

- 需求抽取。
- source/knowledge extraction。
- synthesis draft。
- verifier idea。
- judge/rubric 辅助。
- 小规模 structured generation。

LLM node 不等于 code agent runner。它没有被允许直接在 workspace 内执行多步软件工程循环。

### 2.2 File-content Codegen Backend

`openai_codegen` 属于 file-content codegen backend：

- 调用 OpenAI-compatible endpoint。
- 模型返回 `files[]` 的 path/content。
- 框架写文件。
- 框架运行 gate。

它是真实 LLM codegen 通道，但仍不是完整 code agent runner。

### 2.3 Code Agent Runner

Code agent runner 必须具备：

- 在 isolated workdir 内读写文件。
- 运行允许的本地命令，例如 unit tests、generated check、static checks。
- 根据失败输出迭代修复。
- 输出 machine-readable manifest 或 final patch summary。
- 记录 agent trace、命令记录、文件变更、预算和权限。

候选 adapter：

- `codex_cli_runner`
- `codex_sdk_runner`
- `mini_swe_agent_runner`
- `claude_code_runner`
- `process_code_agent_runner`
- `custom_code_agent_runner`

core 不能绑定任何单一 runner；所有 runner 都必须通过 `AgentBackend` / `AgentBackendConfig` / `AgentInvocationRecord` 接入。

## 3. 必须实现什么

### 3.1 CodeAgentWorkspace Packet

新增或等价实现一个 code-agent workspace packet。它应写入 isolated workdir，例如：

```text
agent-runs/<run_id>/<environment_id>/
  input/
    artifacts/
      need.json
      source-evidence-index.json
      knowledge-pack.json
      environment-spec.json
      logical-tool-graph.json
      task-set.json
      surface-plan.json
      verifier-plan.json
      feasibility-report.json
      implementation-request.json
    implementation-brief.md
    expected-bundle-layout.md
    acceptance-checks.md
  generated/
    runtime.py
    seed_state.json
    verifier.py
    surface_descriptor.json
    check_replay.py
    build_manifest.yaml
  agent-output/
    candidate_manifest.json
    transcript.jsonl
    command-log.jsonl
```

要求：

- `input/` 是只读 source packet。
- runner 只能写 `generated/` 和 `agent-output/`。
- release 只能引用 `generated/` 内通过验证的文件。
- workspace packet 本身是 artifact 或 trace ref，可复盘。

### 3.2 CodeAgentRunnerBackend

新增 backend kind，建议至少支持：

- `code_agent_runner`
- `codex_cli_runner`

实现可以先把 `codex_cli_runner` 和 `process_code_agent_runner` 作为两个 adapter。

Runner invocation 必须包含：

- command argv 或 SDK entrypoint。
- cwd / filesystem root。
- writable roots。
- network permission。
- auth permission。
- timeout。
- max repair attempts。
- allowed commands policy。
- output manifest path。
- transcript path。

### 3.3 真实 Runner 行为

和 Goal 08 的 local helper 不同，Goal 09 的 acceptance 不能只调用 `write_project_board_agent_candidate_files()` 这类本地模板函数。

Runner 必须至少完成以下动作：

1. 读取 `input/implementation-brief.md` 和 artifact JSON。
2. 在 `generated/` 写出 `runtime.py`、`seed_state.json`、`verifier.py`、`surface_descriptor.json`、`check_replay.py`、`build_manifest.yaml`。
3. 运行 `python generated/check_replay.py` 或等价 check。
4. 如果 check fail，读取失败输出并最多修复 N 次。
5. 写 `agent-output/candidate_manifest.json`。
6. 框架重新从磁盘读取 generated files，计算 hash，执行 build/check/replay。

### 3.4 Repair Loop

Repair loop 必须由框架控制，而不是让 agent 自由决定无限循环：

```text
run code agent
-> validate candidate manifest
-> build/check/replay
-> if fail and attempts < max_repair_attempts:
     write failure packet
     call same runner with repair instruction
-> else fail/needs_human
```

每次 attempt 都要写入：

- `AgentInvocationRecord`
- attempt id
- input failure packet ref
- command log ref
- changed file hashes
- check result

### 3.5 Security

必须强制：

- runner workdir 是 isolated disposable directory。
- runner 不得直接写 repo 源文件、`.git`、`.codex`、`.agents`、home、release 目录。
- 所有命令使用 allowlisted argv 或 runner 自身 sandbox。
- 禁止 generic shell executor 作为环境 surface。
- secret 只以 env var/ref 传递；transcript preview 必须 redaction。
- live runner 默认关闭，显式配置才运行。
- network 默认关闭；需要联网时必须进入 `AgentInvocationRecord.permissions`。
- auth 默认关闭；需要 API key 时只能通过指定 env ref。

### 3.6 Verification

通过 code agent runner 生成的 bundle 必须满足 Goal 07/08 的全部 gate：

- path normalization。
- relative path only。
- no symlink escape。
- exact required files。
- no undeclared files。
- sha256 match。
- no forbidden fixture import。
- `check_replay.py` pass。
- positive verifier pass。
- negative verifier fail。
- `ReleaseManifest` 引用 verified bundle。

## 4. 不做什么

不要实现：

- 真实 trainer loop。
- GPU/Ray/vLLM/SGLang。
- MCP 全量 server。
- 第三个领域。
- 任意 shell executor。
- 让 agent 直接改 repo 并把 repo diff 当 release。

不要误判：

- `openai_codegen` 不等于完整 code agent runner。
- `process_agent` 调用本地 helper 不等于真实 code agent runner。
- 有 `AgentInvocationRecord` 不等于 runner-generated bundle 已 verified。
- live runner smoke pass 不等于通用环境自动生成完成。

## 5. 验收标准

完成后应满足：

- `uv run pytest` 全部通过。
- 旧 `awm` CLI 行为不破坏。
- Goal 02-08 回归不破坏。
- 新增 `CodeAgentWorkspace` 或等价 workspace packet。
- 新增 `code_agent_runner` / `codex_cli_runner` 或等价 backend adapter。
- runner 在 isolated workdir 内写 generated files，不调用本地 deterministic codegen helper 冒充生成。
- runner 至少运行一次 generated check command，并记录 command output。
- 框架从 runner 写出的磁盘文件重新计算 hash 并执行 build/check/replay。
- check fail 时 bounded repair loop 可运行或明确返回 fail/needs_human。
- 所有 attempt 都有 `AgentInvocationRecord`、trace ref、command log ref、file hash refs。
- live code-agent smoke 默认 skip；显式配置时可以调用 Codex CLI/SDK、mini-swe-agent 或 Claude Code 等真实 runner。

## 6. 给 Goal 模式的建议 Prompt

```text
阅读 AGENTS.md、README.md、docs/agent-world-environment-generation.zh.md、docs/goal-08-agent-backed-environment-codegen.zh.md、docs/goal-09-real-code-agent-runner.zh.md、docs/project-progress-and-corrections.zh.md。

目标：实现 Goal 09。Goal 08 的 openai_codegen 是 LLM/file-content backend，不是完整 code agent runner。本 Goal 必须支持真正 code agent runner：Codex CLI/SDK、mini-swe-agent、Claude Code/Agent SDK 或自定义 process runner 可以在 isolated workdir 读取任务包、写代码、运行检查、根据失败修复，并产出 verified GeneratedEnvironmentBundle。

实现要求：
1. 新增 CodeAgentWorkspace 或等价 workspace packet，包含 input/artifacts、implementation brief、expected bundle layout、acceptance checks、generated/、agent-output/。
2. 新增 code_agent_runner / codex_cli_runner / process_code_agent_runner 中至少一种真实 runner adapter。core 只能依赖 AgentBackend、AgentBackendConfig、AgentInvocationRecord，不得绑定单一 SDK。
3. runner 必须在 isolated workdir 内写 runtime.py、seed_state.json、verifier.py、surface_descriptor.json、check_replay.py、build_manifest.yaml。
4. runner 必须能运行 generated check command，并把 stdout/stderr/exit code 写入 command log。
5. 不允许调用 write_project_board_agent_candidate_files 或 deterministic template helper 冒充 code agent 生成。
6. 框架必须从 runner 写出的磁盘文件重新读取、计算 sha256、构造 GeneratedEnvironmentBundle。
7. 继续执行 path/hash/security checks、fixture import ban、positive verifier pass、negative verifier fail。
8. check failure 时实现 bounded repair loop，或至少把 repair loop contract、failure packet 和 needs_human/fail 结果落盘。
9. 所有 runner attempt 都必须有 AgentInvocationRecord，记录 backend kind、command/runtime、permissions、budget、trace、command log、input/output artifact refs，并 redaction secret。
10. live runner smoke 默认 skip；显式配置时允许调用 Codex CLI/SDK、mini-swe-agent 或 Claude Code runner。
11. 更新 README、docs/agent-world-environment-generation.zh.md、docs/project-progress-and-corrections.zh.md，明确 LLM node、openai_codegen、code agent runner 的区别。

不要做：
- 不实现真实 trainer。
- 不实现 GPU/Ray/vLLM/SGLang。
- 不新增第三领域。
- 不实现 MCP 全量 server。
- 不把 generic shell executor 当 environment CLI。
- 不让 live runner/model 调用成为默认测试依赖。
- 不把 process helper 或 deterministic template 输出冒充真实 code agent runner。

验收：
- PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -p no:cacheprovider
- project-board-lite runner path 生成 isolated bundle。
- runner command log 证明它写文件并运行 check。
- bundle 文件 hash 和 source refs 被记录。
- 成功任务 verifier pass，负例 verifier fail。
- 模拟 check failure 时 bounded repair/fail path 可观测。
- 破坏 generated runtime/verifier/check 或模拟恶意路径时不得 release。
- 旧 awm CLI 仍可运行。

完成后请输出：
- PASS / PASS WITH RISKS / FAIL
- 改动文件列表
- CodeAgentWorkspace 结构
- runner adapter 如何调用
- runner command log / trace 位置
- build/check/replay 如何验证 runner 写出的环境
- 哪些内容仍是 fixture/domain-specific
- 如何运行完整验证和可选 live runner smoke
- 下一 Goal 建议
```
