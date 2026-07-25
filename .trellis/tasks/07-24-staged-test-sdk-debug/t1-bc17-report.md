# T1 / BC-17 minimum report — bounded ToolSemantics batch reaches a real diagnostic commit

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Request, revision, and model identity

- Scope: `generate-job:486c39821f4a285994b086ef`.
- Target: `design|world_behavior|tool_semantics_batch|tool-semantics-batches|tool-batch-3`.
- Git `HEAD`: `26ae43481c2226312a1f84028cf978f1563f01f1`; the working tree remains
  intentionally uncommitted, and this diagnostic used those local causal fixes.
- Gitignored configuration digest: `sha256:8f49adaaa55c69de0071444b0332f459b21f0b23054eae8d39f5c81dccb6cc1b`.
- Confirming profile/model/provider: profile
  `sha256:83342a2ef81291123fea75a8e656ca2f94480861f2efcdb76c0a9e07bcfd2a60`,
  `grok-4.5`, `agent_world_api_key`.
- Fallback order is `grok-4.5` → `gpt-5.3-codex-spark` → `gpt-5.4-mini`.
  Grok completed the confirming Direct turn, so no fallback was authorized.

## Reproducible single-node evidence

- Source diagnostic state: `.agent-world-live/test-node-20260724T191056Z-643230057620`.
- Fresh v5 result state: `.agent-world-live/test-node-20260724T202302Z-8e6465ce3636`.
  The runner copied the marked source, retained committed ancestors only as inputs,
  derived a new batch-3 coordinate, and dispatched it once. It did not replay a target result.
- Architecture input: `work-commit:ad667d5cff82a1fdf1184673`.
- Fresh target artifacts:
  - attempt `attempt:217760b8cf507269e0f3dfa5`;
  - validation `validation-report:9c64e2bb3ce0473d97239186` (`passed`);
  - evaluation `evaluation:910ca830136d31cd6f97c66a`;
  - commit `work-commit:2f0551ccd38e22d24f60b4c5`.
- The target commit, report, and evaluation are all `diagnostic_only=true` and
  `releasable=false`; no Registry or consumer path was entered.

## Usage and bounded execution

- Reservation: 1 Agent turn, 32,768 LLM tokens, 2,700 seconds.
- Confirming real proposal: completed in 93,401 ms; actual usage 1 Agent turn /
  20,038 LLM tokens; unknown upper bound 12,730 LLM tokens.
- No `RepairAction`, hidden retry, model fallback, or budget-ceiling increase occurred.

## Classification, repair, and frontier lattice

| Revision | Safe frontier | Lattice result |
|---|---|---|
| compact v3 | duplicated permission actor-set coverage | advance; source map became the sole Agent-owned actor set and core projection is derived |
| compact v4 | equality clauses carried forbidden `ordering` | advance; operator-specific closed clause fields added |
| compact v5 | lookup key had an invalid union tag | advance; lookup-key sub-ADT was made explicit |
| compact v5 fresh run | no blocker; target validation passed and committed | shrink to zero / BC-17 green |

The deterministic regressions cover the physical two-tool cap, source/core permission
projection, compact protocol closure, equality-ordering rejection, lookup-key rejection,
and role-profile instructions. The focused quality gate passed: `176 passed`, target-file Ruff
passed, and `git diff --check` passed.

## Credential and release audit

- The confirming root scanned 10,063 regular files. Value matches were `0` for
  `OPENAI_API_KEY` and `0` for `OPENAI_BASE_URL`; values were never printed.
- There were `0` surviving `/dev/shm/agent-world-codex-sqlite-*` directories.
- No raw prompt, transcript, credential/base-URL value, sealed case, evaluator goal,
  expected state, Registry artifact, or consumer result is recorded here.

## Phase boundary

BC-17 is green for its isolated, fresh, real target: it produced a legal semantic commit under
the unchanged deterministic compiler, but only as non-releasable diagnostic evidence. The next
strictly ordered unit is T1 / BC-47, whose compact-alias → frozen Rule-binding acceptance requires
its own fresh real request. T2 and T3 remain blocked.
