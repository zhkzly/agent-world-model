# Implementation Plan

## Checklist

- [x] Create Trellis audit task.
- [x] Re-read the primary task source and living progress log.
- [x] Inspect dirty worktree, untracked files, diff scale, and research PDF size.
- [x] Write PRD/design/implementation plan.
- [x] Start the Trellis task.
- [x] Add ignore hygiene for local paper PDFs if still untracked.
- [x] Re-run targeted and full `uv` validations.
- [x] Review staged file lists and cached diff stats.
- [x] Commit tooling/bootstrap files if they contain no secrets or local-only runtime state.
- [x] Commit implementation baseline after tests pass.
- [ ] Commit or archive this audit task record.
- [x] Report final git status and residual risks.

## Commands

Use `uv` for Python validation:

```bash
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --offline pytest tests/agent_world/test_goal12_request_driven_pipeline.py
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --offline pytest tests/agent_world/test_goal08_agent_backed_codegen.py
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --offline pytest tests/agent_world/test_goal09_code_agent_runner.py
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --offline pytest tests/agent_world
```

Inspect before committing:

```bash
git status --short
git diff --cached --stat
git diff --cached --name-only
```

Commit candidates:

```bash
git commit -m "chore: add trellis workflow bootstrap"
git commit -m "Implement environment generation baseline"
git commit -m "chore(task): record implementation audit"
```

Commit names may be adjusted after staging reveals the exact scope.

## Commits Created

- `550b7a4 chore: add trellis workflow bootstrap`
- `886c21d Implement environment generation baseline`

## Final Status Before Archival

- `git status --short`: only `.trellis/tasks/06-28-audit-implementation-state/` remained untracked.
- `research/papers/` is ignored and intentionally left local.

## Validation Results

Executed on 2026-06-28 with `PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python`:

- `uv run --offline pytest tests/agent_world/test_goal12_request_driven_pipeline.py`: 9 passed.
- `uv run --offline pytest tests/agent_world/test_goal08_agent_backed_codegen.py`: 12 passed, 1 skipped.
- `uv run --offline pytest tests/agent_world/test_goal09_code_agent_runner.py`: 2 passed.
- `uv run --offline pytest tests/agent_world`: 100 passed, 1 skipped.

## Risky Files

- `.codex/config.toml`: must not include user secrets or machine-specific paths beyond project-safe comments/settings.
- `.claude/` and `.agents/`: generated platform skill files are numerous; commit only if they are project workflow assets rather than local cache.
- `agent_world/agents.py`: contains command runner and OpenAI-compatible backend logic; verify redaction, permission gates, and shell-free subprocess behavior with tests.
- `agent_world/request_driven.py` and `agent_world/library_lending.py`: large domain strategy modules; do not refactor in this audit unless tests expose a direct blocker.
- `research/papers/*.pdf`: do not stage by default.

## Done Definition

The task is done when:

- validation results are recorded,
- project-relevant files are committed or explicitly left out,
- no large binary research PDFs are staged,
- final status is understandable,
- and the audit task can be archived without losing context.
