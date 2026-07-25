# Agent World Foundry 迁移与续跑说明

## 项目目的

本项目把一句自然语言环境需求自动转化为真实可执行、可交互、可验证、可发布的程序化 Agent 训练环境。代码负责工作流、Artifact、Gate、局部返工预算和发布决策；隔离的 Agent SDK 后端负责研究、语义设计、代码生成、独立挑战和语义修正。Runtime 的状态转移必须由程序执行，不能用 mock 或 LLM 文本状态转移替代。

## 当前续跑位置

当前真实需求是“用户预订宾馆”。已经得到可执行候选，并完成真实 Integration：

- EnvironmentDesign：`sha256:541032581b374dc47171c9a2d121705d0a9d3cfb54370df8c7b70428a8b4c639`
- WorldSpec：`sha256:eefb5481c46b067407b53351ce8d6b1f883c6d62aea366fa48ee55cfd2ca6e6b`
- r17 Candidate：`sha256:f43412dc2bd692a94ddd764a757bd6ad30f2d510d51cd101ed9f85a990c7cd33`
- r17 SourceSnapshot：`sha256:4472a18e2be151f1c7152bffc712e1187ceda364ecfbb65ca6ab61a28d716466`
- IntegrationReport：`sha256:e2fa38ba17e67c9db1f8cd67d288dfaeb6c535ab11a944d2d3cf5216d7e4927a`
- Candidate source tree digest：`sha256:0b2529cbf8407ee6b629744d0eff108325e56ef84c12a7476ff8c543686046cc`

Integration 状态为 `ready`，7 个硬门全部通过，包含 105 个真实任务 episode、真实安装、Reset、工具调用、并发 Reset、快照和清理。下一步不是重新 Research/Design/Build，而是重新运行 Verifier-only，得到 `VerifierIR` 后进入完整 Judge。尚无成功的 VerifierIR 或 JudgeReport。

## Git 不保存的本机状态

`.agent-world-live/` 被故意忽略。原机器上的主要状态根目录是：

```text
.agent-world-live/hotel-booking/state-v3-20260717-01
```

它包含 ArtifactStore、运行 checkpoint、候选 SourceSnapshot 和 IntegrationReport，可用于精确续跑；但其历史运行目录也可能嵌入 `.agent-runtime/codex-home/auth.json`、Codex session、shell snapshot 和本机日志，因此绝不能原样提交 Git。

如果需要迁移精确运行状态，应在原机器上单独制作脱敏归档，并至少排除：

```text
**/.agent-runtime/codex-home/**
**/.agent-runtime/home/**
**/auth.json
```

ArtifactStore 在恢复后仍会校验上述 content-addressed revision。只迁移 Git 仓库而不迁移脱敏状态根目录时，可以继续开发框架，但必须重新生成运行 Artifact。

## Codex SDK、认证与 CODEX_HOME

完整、可逐项执行的迁移步骤见 [Codex 凭证与本机运行能力迁移](codex-credential-migration.zh.md)。该文档说明 API-key/base-URL 环境句柄、`CODEX_HOME` 隔离、真实 doctor 验证和常见失败。

生产路径使用真实 `CodexSdkBackend`，模型由显式 `agent.model` 配置决定；当前实验优先
`grok-4.5`，在额度或兼容服务不可用时才显式切换为 `gpt-5.4-mini`。迁移后需要重新安装支持当前 SDK 协议的 Codex 预览版，并通过当前机器的 `command -v codex` 设置 `agent.codex_bin`；不要继续使用旧机器上带版本哈希的绝对路径。

模型凭证和路由只从启动进程的 `OPENAI_API_KEY` 与 `OPENAI_BASE_URL` 读取。ProfileProvider 不复制或物化 `auth.json`；隔离 `codex-home/` 中若出现该文件即 fail closed。`codex-home/sessions/`、`codex-home/state/` 和 shell snapshots 都是可重建运行材料，不属于项目 Artifact，也不能进入 Git、envpkg 或发布 Registry。

## 迁移后恢复顺序

1. 克隆私有仓库并切换到 `codex-agent-world-runtime-redesign`。
2. 执行 `uv sync` 重建已删除的 `.venv`。
3. 安装/确认 Codex 预览版，并让 secret manager 向启动进程注入两个环境变量。
4. 把脱敏后的状态根目录复制到新位置；如果不迁移状态，则准备从 Artifact 生成阶段重新运行。
5. 更新本机 TOML 配置中的 `state_root`、`agent.codex_bin`、`agent.api_key_environment`、`agent.openai_base_url_environment` 和 `judge.uv_cache_dir`。
6. 先运行相关 lint/测试，再以新的空 workspace 执行 Verifier-only；成功后加载其 `VerifierIR` 运行 Judge。

## 最近一次框架诊断结论

- reset/task/action schema 错误由代码返回精确字段路径、缺失字段和公开约束，不再压成笼统错误。
- 世界级 invariant 在 Reset 只执行可求值子集，动作相关 invariant 在真实动作后执行。
- retryable provider/transport 错误由代码 Router 做局部 fresh-session retry，不交给 LLM 解释，也不回退 Design/Builder。
- Verifier coverage context 使用 `scope="world_shared", task_type=null` 表示共享世界规则，避免模型把 `shared` 当作真实任务。
- Verifier 要用最少轨迹覆盖语义要求；`semantic_case_limit` 是容量上限，不是目标数量。
- Challenger SDK event 上限与 rollout token 上限对齐，同时继续受协议总字节硬上限保护。

这些约束都服务于同一目标：用有限、可观测、局部的返工得到真实可执行环境，而不是让每个验证失败造成全流水线回退。
