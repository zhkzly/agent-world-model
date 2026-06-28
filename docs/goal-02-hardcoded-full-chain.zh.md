# Goal 02: 基于硬编码案例走通环境到训练消费全链路

本文定义下一条 Goal 模式任务。它不替代 `docs/agent-world-environment-generation.zh.md` 的长期目标；它是一个刻意收窄的第二阶段实现任务。

## 1. 任务定位

当前 `support-desk-lite` 已经能跑通：

```text
S0-S11 artifact workflow
  -> live/mock/process agent review
  -> deterministic gates
  -> release package
  -> replay tasks
  -> deterministic verifier
```

但当前仍然是硬编码案例，不是通用环境生成器。下一步先不要急着把所有阶段泛化，而是基于这个硬编码案例继续向后打通训练/评估消费链路。

目标是证明：

```text
一个已发布的环境包
  -> 可以被执行/采样
  -> 可以产生可审计 rollout trace
  -> 可以产生 deterministic reward/eval record
  -> 可以导出训练/评估消费者可读的数据集
  -> 可以由 pluggable trainer/evaluator adapter 消费
```

## 2. 当前环境是否可以直接调用

可以，但边界要说清楚。

当前可直接调用的是仓库内 Python surface：

- `agent_world.fixtures.support_desk_lite.SupportDeskLite`
- `agent_world.fixtures.support_desk_lite.create_seed_db`
- `agent_world.fixtures.support_desk_lite.reset_environment`
- `agent_world.fixtures.support_desk_lite.verify_task_completion`
- `agent_world.replay.replay_package`

当前 release package 不是完全自包含 runtime。它包含 specs、checks、release records、seed SQLite 和 replay plan；真正的 Python runtime 仍来自本仓库的 `agent_world` 包。

因此当前复现方式是：

```text
安装/保留本仓库代码
  + 使用 release package 目录
  + 调用 agent_world.replay 或 SupportDeskLite surface
```

Goal 02 可以改进 package，让它记录 runtime module refs、import checks 和 consumer entrypoints，但不要求把全部 runtime 代码复制成独立 wheel。

## 3. 本 Goal 要实现什么

### 3.1 Rollout / Sampling

新增一个最小 rollout 层，只针对已发布 package 执行。

输入：

- `release/release-manifest.yaml`
- `spec/tasks.yaml`
- `spec/surfaces.yaml`
- `checks/replay-plan.yaml`
- `fixtures/seed/support-desk-lite.sqlite`

行为：

- 对每个 task reset isolated SQLite state。
- 调用 Python surface 执行任务。
- 写入 tool call trace、state snapshot hash、final answer。
- 调用 deterministic verifier。
- 输出 rollout/eval records。

第一版 policy 可以是 deterministic scripted policy，因为当前目标是验证链路，不是训练出模型。

### 3.2 Reward / Eval Record

新增 deterministic reward/eval record。

每条 record 至少包含：

- `environment_id`
- `release_id`
- `task_id`
- `run_id`
- `policy_id`
- `success`
- `reward`
- `verifier_id`
- `verifier_checks`
- `dependency_path_expected`
- `dependency_path_observed`
- `initial_snapshot_hash`
- `final_snapshot_hash`
- `surface_trace_ref`
- `failure_class`
- `recovery_suggestion`

reward 第一版可以简单定义为：

```text
success=true  -> reward=1.0
success=false -> reward=0.0
```

但必须保留 `reward_source=deterministic_verifier`，不能把 LLM review 当作 reward。

### 3.3 Training Export

新增 training/eval consumer export，不绑定具体训练框架。

输出建议：

```text
training/dataset-manifest.yaml
training/rollout-records.jsonl
training/reward-records.jsonl
training/sft-records.jsonl
training/adapter-index.yaml
```

`sft-records.jsonl` 第一版可以使用简单结构：

```json
{
  "environment_id": "support-desk-lite",
  "task_id": "task-1",
  "messages": [
    {"role": "user", "content": "...natural request..."},
    {"role": "assistant", "content": "...tool-use trace or final answer..."}
  ],
  "tool_trace": [...],
  "reward": 1.0,
  "verifier_result": {...}
}
```

`adapter-index.yaml` 只描述如何映射到下游训练框架，例如 verl、LLaMA-Factory、OpenRLHF、TRL。不要把这些框架作为核心依赖。

### 3.4 Trainer Adapter Contract

新增 pluggable trainer/evaluator adapter contract。

第一版只需要：

- `TrainerAdapter` protocol / interface。
- `NoopTrainerAdapter` 或 `DatasetOnlyAdapter`。
- 能读取 `training/dataset-manifest.yaml`。
- 能返回 `TrainingConsumerRecord`。
- 能证明导出的数据可被消费。

不要实现真实模型训练循环。真实 verl/LLaMA-Factory/OpenRLHF/TRL 集成作为后续 adapter。

### 3.5 Package Integration

release package 需要新增：

```text
rollouts/
training/
checks/rollout-records.jsonl
checks/reward-records.jsonl
release/training-consumer-index.yaml
```

`ReleaseManifest` 或新增 `TrainingConsumerIndex` 应引用这些输出。

## 4. 必须保持的原则

- 明确标注 `support-desk-lite` 是 fixture/full-chain demo，不是通用生成能力。
- 训练模块是 consumer，不反向污染环境合约。
- 不绑定任何具体训练框架。
- 不引入 AWM JSONL 作为核心格式。
- 不把 LLM judge 当 reward。
- 不把 generic shell command executor 当环境 CLI surface。
- 所有 rollout/reward/export records 必须落盘。
- 所有 records 必须可通过 deterministic validator 检查。

## 5. 当前仍然不做

本 Goal 不做：

- 任意环境自动生成。
- 真实 source discovery 驱动 artifact 生成。
- 真实 code agent 生成环境代码。
- 真实模型训练。
- 真实 verl/LLaMA-Factory/OpenRLHF/TRL 依赖。
- MCP/CLI/HTTP surface 实现。
- AWM 论文复现。

这些是后续 Goal。

## 6. 验收标准

完成后应能运行：

```bash
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -p no:cacheprovider
```

并能执行一个完整链路命令或 Python API：

```text
generate support-desk-lite package
  -> replay all tasks
  -> produce rollout records
  -> produce reward records
  -> export SFT/eval records
  -> consume through DatasetOnlyAdapter
```

至少验证：

- 5 个 task 都有 rollout record。
- 5 个 task 都有 reward record。
- 5 个 task 都有 training export record。
- reward 由 deterministic verifier 产生。
- export manifest 引用的文件都存在。
- records 中没有 secret。
- release package 中可定位 runtime module refs。

## 7. 给 Goal 模式的建议 Prompt

```text
阅读 AGENTS.md、docs/agent-world-environment-generation.zh.md、docs/goal-02-hardcoded-full-chain.zh.md。

目标：基于当前硬编码 support-desk-lite first slice，走通 release package -> rollout/eval -> reward records -> training export -> DatasetOnly trainer consumer 的完整链路。

不要把本任务误解成通用环境自动生成。不要实现真实训练框架集成。不要引入 AWM JSONL 或 MCP-only 设计。训练模块必须是 consumer，不能污染环境合约。

实现要求：
1. 新增 rollout/eval consumer 层，能从现有 release package 执行全部 task。
2. 新增 deterministic reward/eval record，reward 来源必须是 verifier。
3. 新增 training export manifest 和 JSONL records。
4. 新增 pluggable TrainerAdapter contract，并实现 DatasetOnly/Noop adapter。
5. Package/Release manifest 中能追踪新增 records。
6. 所有新增内容必须有 deterministic tests。
7. 保持现有 S0-S11 workflow、agent invocation records、review records、gate records 可用。
8. 保持旧 awm CLI 行为不破坏。

验收：
- `uv run pytest` 全部通过。
- 一个完整链路运行产出 5 条 rollout records、5 条 reward records、5 条 training export records。
- 所有任务 replay/verifier 成功。
- 导出的训练消费数据可被 DatasetOnlyAdapter 成功读取。
```
