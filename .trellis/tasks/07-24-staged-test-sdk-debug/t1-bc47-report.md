# T1 / BC-47 minimum report — compact aliases reach a fresh frozen Rule binding commit

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Classification and deterministic gate

- Classification from the plan's bad-case table: provider-boundary failure with a
  representation hypothesis, not a licence to retry, relax validation, or
  manufacture a semantic result.  The bounded causal revision is compact,
  frozen Rule-binding aliases; materialization and the executable Rule compiler
  remain unchanged acceptance authorities.
- Focused deterministic gate passed: `4 passed`.
  It covers compact prompt projection, alias-to-frozen-binding expansion,
  rejection of a raw Rule pointer before compilation, and compilation through
  the compact ToolSemantics protocol.
- The diagnostic-harness plus BC-47 regression gate passed: `14 passed`.
  This includes the successor-node no-replay/diagnostic-only harness cases.

## Request, revision, and model identity

- Scope: `generate-job:486c39821f4a285994b086ef`.
- Target: `design|world_behavior|tool_semantics_batch|tool-semantics-batches|tool-batch-3`.
- Git `HEAD`: `26ae43481c2226312a1f84028cf978f1563f01f1`; the causal working-tree
  changes remain intentionally uncommitted.
- Plan digest: `sha256:eb47dec325822bbc8a7f7a57f73882ee5c73c3242fef0e019632213bac6a847f`.
- Gitignored configuration digest:
  `sha256:8f49adaaa55c69de0071444b0332f459b21f0b23054eae8d39f5c81dccb6cc1b`.
- Confirming profile/model/provider: profile
  `sha256:83342a2ef81291123fea75a8e656ca2f94480861f2efcdb76c0a9e07bcfd2a60`,
  `grok-4.5`, `agent_world_api_key`.
- Fallback order is `grok-4.5` → `gpt-5.3-codex-spark` → `gpt-5.4-mini`.
  Grok completed the request, so no fallback was authorized.

## Fresh single-node evidence

- Marked diagnostic predecessor:
  `.agent-world-live/test-node-20260724T191056Z-643230057620`.
- Fresh child state:
  `.agent-world-live/test-node-20260724T203336Z-e4b376845294`.
- The successor runner copied only the marked diagnostic predecessor, asserted
  that the derived target had no existing head, froze a new Design epoch, and
  executed one `dispatch_one`.  The preceding Architecture commit was input
  only; no historic target result was replayed.
- Architecture input: `work-commit:ad667d5cff82a1fdf1184673`.
- Fresh target artifacts:
  - attempt `attempt:217760b8cf507269e0f3dfa5`;
  - validation `validation-report:attempt:217760b8cf507269e0f3dfa5` (`passed`);
  - evaluation `evaluation:910ca830136d31cd6f97c66a`;
  - commit `work-commit:2f0551ccd38e22d24f60b4c5`.
- The proposal began at `2026-07-24T20:33:46Z`, finished at
  `2026-07-24T20:35:18Z`, and persisted a completed Agent execution.  This is
  independent fresh execution evidence even where deterministic artifact ids
  are the same logical ids inside separately copied state roots.
- Attempt, validation report, evaluation, and commit are all
  `diagnostic_only=true` and `releasable=false`.  No Registry or consumer path
  was entered.

## Usage, frontier, and stop boundary

- Reservation: 1 Agent turn, 32,768 LLM tokens, 2,710 seconds.
- Actual usage: 1 Agent turn / 20,244 LLM tokens / 91,496 ms.
  Unknown upper bound: 12,524 LLM tokens.
- No RepairAction, hidden retry, budget-ceiling increase, or model fallback
  occurred.
- Frontier transition: the BC-47 predecessor's safe
  `agent_backend_turn_failed_provider_rejected` terminal became a fresh target
  with zero validation issues and `design.tool_semantics.compiles` passed:
  **shrink to zero**.  It is not a claim that an old failed target was healed
  or replayed.

## Quality and credential audit

- Focused Ruff passed for the harness, frozen Rule context, compact protocol,
  ToolSemantics leaf, and their tests; `git diff --check` passed.
- The fresh diagnostic root scanned 10,063 regular files.  Value-match file
  counts were `0` for `OPENAI_API_KEY` and `OPENAI_BASE_URL`; values were never
  printed.  Surviving Codex SQLite runtime directories: `0`.
- This report retains no raw prompt/transcript, credential/base-URL value,
  sealed case, evaluator goal, expected state, Registry artifact, or consumer
  result.

## Phase boundary

BC-47 is green for its required fresh real request, and the ordered T1 sequence
BC-44 → BC-14 → BC-17 → BC-47 is complete.  This is still non-releasable
diagnostic evidence, not a Registry claim.  Per T2's first required action, the
next stage must locate and verify a **complete** legal semantic commit suitable
as downstream input; Build, Judge, Registry, and the full E2E have not yet
been started.
