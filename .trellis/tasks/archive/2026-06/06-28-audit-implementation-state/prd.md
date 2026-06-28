# Audit implementation state

## Goal

把当前未收束的实现工作变成一个可继续开发的、可验证的仓库基线。

用户已经确认项目方向：这是一个 loop-engineering 风格的环境生成系统，核心是从直接需求/source evidence 出发，生成可执行 backend/runtime 环境包，并由框架侧 gate、verifier、bounded repair 和 release/package 控制质量。当前文档已经对齐并提交，但实现层、Trellis 工具化层和本地研究资料还大量停留在未提交状态。

本任务不新增 Goal 13 或新功能；它先审视当前实现，按依赖关系分组，验证可执行性，然后把应该进入仓库的内容提交成清晰基线，方便后续继续泛化 request-driven pipeline、package consumer、rollout/training consumer 等工作。

## Confirmed Facts

- 主任务源是 `docs/agent-world-environment-generation.zh.md`。
- 进度/偏差日志是 `docs/project-progress-and-corrections.zh.md`。
- 最近三个提交已经完成文档对齐和上一个 Trellis task 归档：
  - `49ff72e Align environment generation docs`
  - `df05158 chore(task): archive 06-28-document-project-alignment`
  - `99dc110 chore: record journal`
- 当前 dirty worktree 分成几类：
  - Trellis/Codex/Claude/project agent bootstrap：`.trellis/`, `.agents/`, `.codex/`, `.claude/`, `AGENTS.md`。
  - 核心 framework 修改：`agent_world/agents.py`, `agent_world/artifacts.py`, `agent_world/workflow.py`, `agent_world/gates.py`, `agent_world/package.py`, `agent_world/replay.py`, `agent_world/review.py`, `agent_world/__init__.py`。
  - Goal 02-04 support-desk runtime/consumer/CLI/HTTP/online/export files。
  - Goal 05-06 pipeline/source/store/project-board source family files。
  - Goal 07-11 generated bundle、agent codegen/runner、independent verifier、packaged runtime consumer files。
  - Goal 12 request-driven booking/library files and tests。
  - `research/papers/*.pdf` contains about 76 MB of local paper PDFs.
- Existing local verification previously passed with `uv run --offline pytest tests/agent_world` after the documentation alignment commit, but this task must re-run validation before committing the implementation baseline.

## Requirements

1. Do not add new product functionality under this task.
2. Preserve the project boundary from `docs/agent-world-environment-generation.zh.md`: environment generation must mean executable backend/runtime packages with tasks, surfaces, verifiers, gates, release metadata, and downstream consumer entrypoints.
3. Inventory all uncommitted and untracked files into commit groups that reflect real dependencies, not just chronological Goal numbers.
4. Keep local-only or bulky research artifacts out of the implementation commit by default; paper PDFs should remain local evidence or be replaced by lightweight notes/metadata unless the user explicitly asks to version them.
5. Use `uv` for all Python validation commands.
6. Verify that the current implementation still passes the relevant tests before committing.
7. Prefer a small number of coherent commits:
   - Trellis/platform bootstrap and project instructions.
   - Implementation baseline for the already-developed environment-generation slice.
   - Current audit task/journal or cleanup record.
   If staging by finer-grained Goal groups proves safe and low-risk, split further; if the code is too interdependent, keep the implementation baseline together and document why.
8. Do not revert or rewrite unrelated user changes. If a file is risky or unrelated, leave it uncommitted and document the reason.
9. Keep `awm` CLI compatibility claims and tests intact.
10. Update `docs/project-progress-and-corrections.zh.md` only if the audit discovers a new factual correction; do not turn this task into another broad documentation rewrite.

## Acceptance Criteria

- [x] `prd.md`, `design.md`, and `implement.md` exist for this audit task and have no placeholder sections.
- [x] Dirty worktree inventory is captured with explicit include/exclude decisions.
- [x] `research/papers/*.pdf` are not accidentally staged into a normal code commit.
- [x] Validation commands are run with `uv`; failures, skips, or environmental limits are recorded.
- [x] The committed baseline includes the project-relevant Trellis/platform files needed to reproduce this workflow, unless a clear reason is found to leave a subset local-only.
- [x] The committed baseline includes the existing Goal 02-12 implementation slice only after tests prove it is executable.
- [x] Final status reports any remaining untracked/modified files and why they remain.
- [x] No generated runtime, cache, secret, API key, personal identity file, or bulky binary research dump is committed.
- [x] The task can be archived after completion without losing the audit rationale.

## Out Of Scope

- Implementing a new Goal or third/fourth request-driven domain.
- Generalizing request-driven strategy selection beyond the current code.
- Adding live network search/discovery.
- Integrating real trainer loops, GPU workers, Ray/vLLM/SGLang, verl, TRL, OpenRLHF, or LLaMA-Factory as core dependencies.
- Rewriting Trellis itself beyond small ignore/config hygiene needed for this repository.
- Deleting local research PDFs from disk.

## Notes

- Recommended default: commit Trellis/Codex/Claude/project-agent bootstrap because the user explicitly wants future sessions to follow Trellis-style workflow. Keep paper PDFs local/ignored because they are large binary evidence, not executable project state.
- Bootstrap commit: `550b7a4 chore: add trellis workflow bootstrap`.
- Implementation baseline commit: `886c21d Implement environment generation baseline`.
- Remaining local artifact: `research/papers/` is ignored by `.gitignore` and remains on disk as local research evidence.
