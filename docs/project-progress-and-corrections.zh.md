# Project Progress And Corrections

本文只记录会影响项目方向的纠偏；目标以 `docs/agent-world-environment-generation.zh.md` 为准。

## 2026-06-30

已清理会误导后续 AI 的历史材料：

- 旧 Goal / PRD / implement 计划。
- Trellis task、workspace journal、workflow 和 channel agent prompt 文档。
- 旧研究说明与 AWM 样本说明文。
- 与当前 `agent_world` 无关的旧 spec。

保留：

- 项目目标源文档。
- `docs/loop-engineering.md` 背景材料。
- 原始 AWM 样本 JSONL，作为可选 source evidence。
- 面向 `agent_world` 的极简规范。

实现进展：

- `codex_sdk` 已作为真实 `InvocationBackend` 接入：配置、provider、registry、SDK 缺失处理、direct-host full-access profile、私有 `CODEX_HOME`/workspace、invocation record 和 implementation candidate manifest 路径均走统一 contract。
- Pipeline 会把 `codex_sdk` 视为 agent-backed implementation runner，由框架继续执行 candidate manifest/path/hash/self-check/independent verifier；SDK 不直接决定 release。
- 固定六文件 `GeneratedEnvironmentBundle` 路径已移除，当前实现改为 `GeneratedEnvironmentProject` / contract-project：code agent 自由生成 `generated/source`、`state`、`adapters`、`scripts`、`spec`，框架只要求 `contract.json`、candidate manifest、package-relative path/hash 和八个 runtime ABI 接口。
- 新增项目内通用 skill `.agents/skills/agent-world-environment-codegen`，用于指导 Codex/runner 实现环境项目；schema 真源放在 `agent_world/contracts/*.schema.json`，并由 pipeline 注入到 `input/schemas/`，不是每个环境一个 skill。
- 独立验证器已改为读取 `contract.json` 并通过 `describe/setup/reset/health/invoke/verify/export_trace/teardown` 做 framework-owned positive/negative replay，不再 import 固定 `runtime.py/verifier.py/seed_state.json`。
