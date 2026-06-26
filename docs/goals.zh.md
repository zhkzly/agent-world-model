# Codex Goal 计划

这个文件给 Codex Goal mode 使用。长目标不要直接塞进 `/goal`，而是让 `/goal` 指向本文档和 `docs/agent-world-loop-program.zh.md`。

## 主目标

```text
/goal Coordinate the Agent World Loop Engineering Program. Use docs/agent-world-loop-program.zh.md as the source of truth. Keep implementation slice-based, AWM-first, TDD-first, observable, verifier-driven, and independently reviewed. Do not start real mini-swe/Codex SDK integration or training integration until the first AWM/scripted trace/reward/export slice passes review.
```

## 启动前上下文加载

先在仓库根目录启动 Codex：

```bash
cd /home/kelongzx/pycodes/loop_agent/agent-world-model
codex
```

受限环境里建议先设置 `uv` 可写目录：

```bash
export UV_CACHE_DIR=/tmp/uv-cache
export UV_PYTHON_INSTALL_DIR=/tmp/uv-python
```

如果某个 goal 明确需要轻量 LLM smoke test，再设置 OpenAI-compatible 变量。API key 只在 shell 中设置，不写入仓库：

```bash
export OPENAI_BASE_URL="https://blog.r78xoaxrk.nyat.app:50903/v1"
export OPENAI_API_KEY="<set locally>"
export AWMX_SMOKE_MODEL="gpt-5.4-mini"
export AWMX_CODE_MODEL="gpt-5.3-codex"
```

然后先发送这条上下文加载请求：

```text
Read AGENTS.md, docs/agent-world-loop-program.zh.md, docs/goals.zh.md, docs/loop-engineering.md, research/notes/agent-world-survey.zh.md, and research/notes/agent-world-timeline.zh.md. Summarize the goal, first acceptance gate, and the things that must not be implemented yet.
```

确认总结符合预期后，再启动主目标。

## 执行顺序

1. 完成 `awmx-contracts`。
2. 用 `research/data/awm_1k_samples/` 明确 AWM importer fixture 和最小 artifact 映射。
3. 从冻结后的 contracts 创建 worktree。
4. 并行推进 `awmx-foundation`、`awmx-workflow`、`awmx-rollout`。
5. `awmx-rollout` 第一条可运行路径必须是 scripted 或 AWM-backed。
6. 每个分支完成后运行 `awmx-review`。
7. 只合并 pass 的分支。
8. 合并后运行 first end-to-end AWM/scripted slice。
9. E2E pass 后再讨论真实 CLI 扩展、真实 mini-swe/Codex SDK agent runners 和 training export。

## 每个 goal 的固定要求

- 关键节点开始前必须重新阅读 `docs/loop-engineering.md` 和 `research/notes/` 下的 Agent World 综述。
- 先写测试或 dry-run check。
- 不破坏现有 `awm` CLI。
- 所有 Python 命令使用 `uv run ...`；依赖管理使用 `uv sync` 或 `uv add`。
- 不把 API key 写入仓库。轻量模型测试优先 `gpt-5.4-mini`；代码向 smoke test 可用 `gpt-5.3-codex`。
- 所有运行产物必须在 `outputs/agent_world/`。
- 所有稳定配置必须在 `configs/agent_world/`。
- 所有执行都必须写 `events.jsonl`。
- 只要调用 runner，就必须写 `trace.jsonl`。
- 只要调用 verifier，就必须写 `reward.json`。
- 完成后必须让独立 reviewer 只读验收。

## 独立验收 Prompt

```text
Review this implementation against docs/agent-world-loop-program.zh.md. Do not modify files. Check that tests were written first or are clearly tied to acceptance criteria, configs are under configs/agent_world, run artifacts are under outputs/agent_world, trace/events/reward files are produced, verifiers are deterministic where possible, and existing AWM CLI behavior is preserved. Return pass/fail with exact file references and required fixes.
```
