# Monitor real codegen run

## Goal

由 Codex 代替用户手动启动一次真实 codegen 执行，并在运行过程中监控结果。

这不是 unit test 任务。目标是使用当前 shell 环境中已配置的 base URL、API key、model 等变量，启动真实 code agent runner，让 Codex 这样的 agent 接收 workspace packet、读取 artifacts、写环境 bundle 文件、运行检查，并在失败时由框架的 bounded repair loop 再次调用。框架必须继续拥有 build/check/replay、independent verifier、package/release gate；agent 不能自己决定发布成功。

## Confirmed Facts

- 当前仓库已有两类真实外部实现路径：
  - `AGENT_WORLD_AGENT_BACKEND=openai_codegen`: OpenAI-compatible file-content codegen，模型返回 JSON `files[]`，再由框架写 isolated workdir。
  - `AGENT_WORLD_AGENT_BACKEND=codex_cli_runner`: Codex CLI 非交互式 runner，接收 workspace packet 后自行写 `generated/`、运行 check、输出 `agent-output/candidate_manifest.json` 和 command log。
- 当前环境变量中存在相关变量名，包括 `AGENT_WORLD_OPENAI_BASE_URL`、`AGENT_WORLD_OPENAI_API_KEY`、`AGENT_WORLD_OPENAI_MODEL`、`AGENT_WORLD_SMOKE_OPENAI_MODEL` 以及 fallback `OPENAI_*`。
- 上一次最小 live LLM smoke 已证明当前 env 至少能完成 chat-completions 调用。
- 官方 Codex manual 确认 Codex SDK 存在，Python SDK 通过本地 Codex app-server 控制 Codex；`codex exec` 是官方支持的非交互式 runner，并支持 `--json`、sandbox 和 approval 配置。当前实现保持 backend-neutral `AgentBackend`，先使用 `codex_cli_runner`，后续可新增 SDK adapter。
- 已执行多次真实 `codex_cli_runner` booking-service-lite live run：Codex 启动成功，读取 `input/` packet，写出六个 `generated/` 文件，并在框架 repair loop 下进行后续 attempt。框架始终拥有 release gate；最终 live 状态记录在下方 Live Run Record。
- 本任务不得打印或提交 API key、base URL、auth token 或完整模型输出里可能包含的敏感值。

## Requirements

1. Do not add a unit-test-only proof as the primary outcome.
2. Start a monitored live run using current environment credentials and model config.
3. Prefer the real agent-runner path first:
   - `PipelineRunConfig(..., implementation_mode="agent")`
   - env override `AGENT_WORLD_AGENT_BACKEND=codex_cli_runner`
   - `AGENT_WORLD_CODEX_CMD='codex --ask-for-approval on-request --sandbox workspace-write exec --json --skip-git-repo-check --ephemeral -'`
   - real network/auth enabled through existing env/config
4. Capture only sanitized run summary:
   - record status,
   - failure class / recovery suggestion,
   - agent backend kind,
   - generated bundle id/status if present,
   - independent verifier status if present,
   - package/release status if present,
   - output directory path under `/tmp`.
5. If the real run fails, do not hide it with a unit test. Record the exact gate/failure class and decide the next engineering fix.
6. Keep generated outputs out of git.
7. If code changes are required, prefer improving the agent workspace packet/schema over weakening framework release gates.

## Acceptance Criteria

- [x] A real live codegen run is started by Codex in this session.
- [x] The run uses env-provided credentials/config without printing secret values.
- [x] The run result is inspected through framework artifacts/gates, not model self-report.
- [x] Task record captures whether the live run passed, failed, or reached a repairable blocker.
- [x] If code changes are needed, they are justified by the live run result and verified separately.

## Live Run Record

Multiple monitored `codex_cli_runner` runs were executed against the booking-service-lite request. They all reached the real Codex CLI runner and produced isolated workspace attempts under `/tmp/agent-world-codex-run-*`; none printed secrets.

Observed progression:

1. Initial run failed at manifest contract: `candidate_file_kind_mismatch` because the workspace packet did not state exact `generated_files[].kind` values.
2. After adding the kind table/schema, the run reached framework independent verifier and exposed missing runtime entrypoint/helper contracts.
3. After adding runtime entrypoint/helper/trace contracts, the run exposed framework noise: `__pycache__/*.pyc` files were being treated as undeclared generated files.
4. After ignoring Python bytecode cache files and adding replay expectations, the final monitored run still failed release at framework independent verifier:
   - `run_status: fail`
   - `agent_backend_kind: codex_cli_runner`
   - `agent_invocation_count: 2`
   - `generated_bundle_id: bundle-booking-service-lite-agent-generated`
   - `generated_bundle_status: fail`
   - `independent_status: fail`
   - `release_environment_id: ""`
   - final failure class: `independent_generated_bundle_verification_failed`

Final live failure details:

- The manifest shape was valid in both attempts.
- The generated bundle exposed required runtime class/helpers/methods.
- The remaining failure was runtime/verifier behavior under framework replay, e.g. `TypeError: unsupported operand type(s) for -: 'NoneType' and 'int'`.
- Codex CLI repair attempts sometimes tried sandbox-blocked shell cleanup commands or produced code that passed its local check but not the framework independent verifier.

Conclusion: the real Codex CLI runner path is wired and observable, but live runner output is not yet reliable enough to pass S10/S11 release for booking-service-lite. The framework correctly blocked release instead of trusting Codex self-report or generated `check_replay.py`.

## Notes

- This task did reveal code defects and contract gaps. The implemented fixes are in the runner env setup, workspace packet/schema, repair packet, and candidate validator behavior.
