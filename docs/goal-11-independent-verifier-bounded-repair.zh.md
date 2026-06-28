# Goal 11: Independent Generated Bundle Verifier And Bounded Repair Loop

本文记录本次 Goal 的边界：修正 generated environment release gate 过度信任 generated `check_replay.py` 自报的问题，并在框架层增加有上限的 repair loop。

## 背景

Goal 07-10 已经让 `project-board-lite` 可以生成 isolated `GeneratedEnvironmentBundle`，也可以通过 `openai_codegen` 或 `code_agent_runner` 进入同一 release gate，并复制到 package 内稳定路径。但旧 gate 仍存在两个问题：

- `check_project_board_generated_bundle()` 主要相信 generated `check_replay.py` 的 stdout JSON。
- agent candidate 失败后 pipeline 直接停止，没有构造 failure packet 并重新调用同一个 backend。

这会导致两个误判风险：伪造只打印 success JSON 的 `check_replay.py` 可能被当成通过；一次可修复的 agent candidate 失败无法被框架级反馈循环处理。

## 已实现边界

- 新增 `agent_world.independent_verifier.verify_project_board_generated_bundle_independent()`。
- independent verifier 从 generated bundle/package 直接加载 `runtime.py`、`verifier.py`、`seed_state.json`。
- verifier 检查 runtime/verifier import、seed load、required entrypoints、runtime tool methods、`check_replay.py` 结构 sanity。
- verifier 对 release accepted tasks 中的 `pb-task-1`、`pb-task-2`、`pb-task-3` 分别执行 positive/negative replay，并写 task-level check records。
- bundle/package gate 只有 generated check 与 independent verifier 都通过才 accepted。
- 伪造只打印 success JSON 且不导入 runtime/verifier、不加载 seed 的 `check_replay.py` 会被拒绝。
- `PipelineRunConfig.max_repair_attempts` 和 `AGENT_WORLD_MAX_REPAIR_ATTEMPTS` 控制框架级 bounded repair loop。
- agent implementation attempt 失败时写 failure packet，包含 failure class、recovery suggestion、failed task/verifier、command、exit code、stdout/stderr preview、candidate path/hash/security/check 信息。
- 还有 repair budget 时，pipeline 调用同一个 `AgentBackend`，把 previous attempt 和 failure packet 放进 instruction；runner backend 还会在 `input/failure-packet.json` 与 `input/previous-attempt-record.json` 中收到文件版上下文。
- 每次 attempt 都记录 `AgentInvocationRecord`、implementation/check record、candidate paths/file hashes；达到上限仍失败时停止，不进入 S10/S11。

## 仍然不是

- 不是通用 verifier synthesis。
- 不是第三个领域。
- 不是真实 trainer、verl、GPU、Ray、vLLM 或 rollout loop。
- 不是 MCP/HTTP/CLI 通用发布。
- 不是让 agent 控制 pipeline 流程；pipeline 仍由 `PipelineRunner` 和 typed config 控制。
- 不是默认 live Codex/Claude/mini-swe-agent smoke；外部 runner/model 仍需显式配置、allowlist、network/auth 权限。

## 验收回归

- `uv run pytest` 全量通过。
- 测试证明 forged `check_replay.py` 不能通过 bundle gate，也不能进入 release。
- 测试证明 `pb-task-1`、`pb-task-2`、`pb-task-3` 都被 independent verifier 覆盖。
- 测试证明第一次 agent candidate 失败、第二次 repair 成功时 pipeline pass，并保留两次 attempt 记录和 failure packet。
- 测试证明超过 `max_repair_attempts` 后 pipeline fail 且不生成 `ReleaseManifest`。
