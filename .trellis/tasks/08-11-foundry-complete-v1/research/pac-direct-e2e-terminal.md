# Product Alignment Checkpoint — Direct e2e proof terminal

Run: run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆)
Trigger: real-execution proof terminal of the direct-completion slice
(plans fe33df95 + 0ff3ae1d; reviews cross-layer-review-fe33df95.md and
cross-layer-review-0ff3ae1d.md).

## Canonical goal restated

Natural-language need -> evidence-grounded design -> real isolated runtime
executing state transitions -> independent Judge (all required hard claims) ->
immutable Registry EnvironmentPackage -> safe Observe; the released package
feeds SFT/RL through the fixed episode protocol.

## Trust boundary and evidence

- Designer language: tool_semantics guards (no effects) and when-only task
  rules, regenerated under the corrected prompts (prompt ids bumped) — frozen
  artifacts in heads.json (positive guards verified on all 4 tools; task
  rules when-only verified).
- Builder runtime: framework-rendered design-driven runtime evaluates when
  conditions, honors initial_config, exits cleanly on close — verified by
  integrate() against the real venv (offline bench /tmp/e2e-trace.py:
  INTEGRATE passed, 4 recipes) and by 285 deterministic tests.
- Judge: reference-composition tool semantics + reset-view initial rules +
  ambiguity detection — same code path the live run executes.
- Resume: candidate source closure bytes persisted (0032be9b artifact, 9
  files) and materialized by _ensure_workspace on skip — verified live and by
  the round-trip test.

## What is proven at this terminal

<FILL: terminal status/release and node evidence from observe>

## What remains unproven / non-claims

- <FILL>
- Expand/Consumer/auto-capture not implemented; rollout untouched.
- Graph/test progress alone is not product completion; the release verdict is
  the Registry receipt, not this checkpoint.
