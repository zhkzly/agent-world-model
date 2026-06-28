# Design

## Scope

This is a repository-state audit and baseline task. It should turn already-existing implementation work into a clean continuation point.

It should not introduce new architecture. The architectural source remains:

- `docs/agent-world-environment-generation.zh.md`
- `docs/project-progress-and-corrections.zh.md`
- `AGENTS.md`
- Goal 02-12 documents under `docs/`

## Audit Model

Use three decisions for every dirty file:

1. Commit now: required project state, executable implementation, tests, Trellis workflow files, or task evidence.
2. Keep local/ignored: bulky papers, runtime caches, personal state, generated outputs, credentials, or files that are useful locally but not a source artifact.
3. Defer with note: files that appear unrelated or unsafe to stage without a separate review.

## Commit Grouping

Preferred dependency order:

1. Tooling and workflow bootstrap:
   `.trellis/`, `.agents/`, `.codex/`, `.claude/`, and `AGENTS.md`.

   Rationale: future sessions need the same Trellis workflow, skills, task system, platform hooks, and project instructions before more feature work is delegated or resumed.

2. Implementation baseline:
   `agent_world/` framework/runtime/source/codegen/verifier/package modules plus `tests/agent_world/` and `tests/fixtures/`.

   Rationale: the uncommitted code is highly interdependent across Goal 02-12. The package, pipeline, agent backend, generated bundle, independent verifier, and request-driven strategy tests cross-reference each other. Splitting this too finely risks intermediate commits that cannot pass tests.

3. Audit task and local hygiene:
   `.trellis/tasks/06-28-audit-implementation-state/`, optional `.gitignore` update for paper PDFs, and journal updates if needed.

   Rationale: the audit should explain why the baseline was formed and leave clear next steps.

If inspection shows a finer split can pass tests independently, use it. Otherwise prefer a tested implementation-baseline commit over fragile partial commits.

## Exclusions

Do not stage:

- `research/papers/*.pdf` by default. They are about 76 MB of local binary research evidence.
- `.trellis/.developer`, `.trellis/.current-task`, `.trellis/.runtime/`, `.trellis/.agents/`, or other paths ignored by `.trellis/.gitignore`.
- Python caches, pytest cache, generated `outputs/agent_world/`, or temporary workdirs.
- Credentials, base URLs with secrets, API keys, auth tokens, or local machine state.

## Validation Strategy

Minimum validation before implementation baseline commit:

```bash
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --offline pytest tests/agent_world
```

If offline resolution fails because the environment does not already have dependencies cached, rerun with explicit approval for network or record the failure and run the best cached subset available.

Targeted checks that are especially relevant to the current baseline:

```bash
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --offline pytest tests/agent_world/test_goal12_request_driven_pipeline.py
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --offline pytest tests/agent_world/test_goal08_agent_backed_codegen.py
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --offline pytest tests/agent_world/test_goal09_code_agent_runner.py
```

## Risk Controls

- Stage with explicit paths or pathspec files, not broad `git add .`, so local PDFs are not swept in.
- Review `git diff --cached --stat` before each commit.
- Use non-interactive `git commit -m ...` commands.
- If tests fail, do not commit the implementation baseline as passing. Record the failure in this task and fix only if the fix is directly in scope.
- If a platform bootstrap file looks personal or credential-bearing, leave it uncommitted and document it.

## Next Work After This Task

After the baseline is committed, the next product task should continue from the progress log's "下一优先级":

- generalize request/domain planning beyond keyword probes,
- make local source planning less domain-specific,
- extract schema-driven/codegen inputs,
- build a generic packaged-runtime rollout/online adapter,
- then consider training/evaluation feedback loops as explicit downstream workflows.
