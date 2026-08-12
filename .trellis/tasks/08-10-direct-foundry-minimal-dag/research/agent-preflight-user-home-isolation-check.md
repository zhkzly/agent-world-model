# Independent check — Agent child HOME isolation

Date: 2026-08-11

## Verdict

**Decision: allow (targeted).**

The matching independent allow is
`cross-layer-review-577e7369-agent-user-home.md`. Its plan digest matches the
raw SHA-256 of `agent-preflight-user-home-isolation-plan.md`:
`577e7369b4f118b88e393cef0597412e7c6ca0c3d4e050477d2f396d7f002b43`.

The inspected implementation is exactly the authorized child-environment
change. In `CodexAgentBackend._call`, the sole `CodexConfig.env` mapping now
sets both `CODEX_HOME` and `HOME` to the same already-created disposable
directory. The selected credential handle remains the only conditional third
entry. It does not change the workspace (`cwd`), route, prompt, mounted Skill,
SDK lifecycle, fixed full-access sandbox, fallback policy, Artifact contracts,
or candidate/runtime path.

The existing backend spy now sets an ambient `HOME`, captures the actual SDK
config, and proves all of the following:

- `HOME == CODEX_HOME`;
- `HOME != /ambient-user-home`;
- the env mapping contains only `CODEX_HOME`, `HOME`, and the configured
  credential handle;
- the mounted Skill, `cwd`, fixed sandbox, one session close, cleanup, and
  no persisted credential/endpoint assertions remain intact.

`DirectChatBackend` does not construct this SDK environment, and the candidate
runtime environment is constructed separately. Thus the exact hunk has no
observed cross-route or candidate-process effect.

## Scope and diff review

`git diff --check` passed. The worktree contains extensive concurrent,
uncommitted changes beyond this one-entry allow (including other `agent_world/`
modules, tests, docs, skills, and task artifacts). Per the requested
independent scope, they were neither reverted nor certified by this result.
Within the two target files, the HOME-isolation hunk is limited to the one
environment entry and its matching ambient-home assertions; it introduces no
new helper, resolver, profile/permission mechanism, SDK route/config field, or
real invocation.

## Verification

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_agent_route_config.py -q` | pass — 20 passed in 1.15s |
| `uv run pytest` | pass — 101 passed in 6.23s |
| `uv run ruff format --check .` | pass — 21 files already formatted |
| `uv run ruff check .` | pass — all checks passed |
| `uv run mypy agent_world` | pass — no issues in 13 source files |
| `uv run python -m compileall -q agent_world` | pass |
| `git diff --check` | pass |

## Findings (fixed)

None. No code change was needed during this check.

## Findings (not fixed)

None for the authorized HOME-isolation hunk.

## Still unproven

No real model/API call was made. Deterministic tests prove only the intended
`CodexConfig.env` projection, not that pinned `openai-codex==0.144.4` honors
the redirected HOME during live discovery. The required next true-boundary
proof remains a fresh temporary nonce-marker SDK preflight that demonstrates
the exact singleton Skill surface, target bundle digest, no ambient user
Skills, one session close, and cleanup. That preflight would still not prove a
semantic Agent node, CandidateBuild, Integration, Judge, Registry, or Direct
E2E.
