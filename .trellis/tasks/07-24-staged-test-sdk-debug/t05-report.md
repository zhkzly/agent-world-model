# T0.5 minimum report — dual `InvocationBackend` routing

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Request and execution identity

- Scope/request: `generate-job:77330c4603201205c648ad65`.
- Target: `design|world_architecture|world_architecture||`.
- Git `HEAD`: `26ae43481c2226312a1f84028cf978f1563f01f1`; this work remains
  intentionally uncommitted.
- Gitignored Spark configuration digest:
  `sha256:301bac21e513ad4aba7b45000e058f7a9bf26a1c0fc32f48af12d86fa2b7451c`.
- Model/provider/profile: `gpt-5.3-codex-spark` /
  `agent_world_api_key` /
  `sha256:858bf3bba0df433c6ee6d847a1761ae08d222589a87fbb95bb7a927f479f53ef`.
- Authorized fallback order: `grok-4.5` → `gpt-5.3-codex-spark` →
  `gpt-5.4-mini`. Grok's earlier target-level A→B→A stop remains in force;
  Spark was the authorized fallback. No mini run was used here.

## Implementation and deterministic evidence

- `DirectLlmBackend` is an `InvocationBackend` implementation using the
  official `AsyncOpenAI` Responses API only inside
  `agent_world/invocation/direct_llm.py`. It requests strict
  `text.format=json_schema`, uses the existing transport schema, bounds output
  tokens, sets `store=False`, and sets the SDK's `max_retries=0`.
- The zero-retry setting is deliberate: Scheduler/RepairLedger remains the
  only retry and budget authority. A deterministic client-factory regression
  asserts that every Direct request receives `max_retries=0`.
- `RoutedInvocationBackend` is the only application routing point. Direct is
  selected only for an explicit `single_shot_structured`, tool-free,
  session-free request with an output schema. All other requests remain on
  `CodexSdkBackend`; a Direct failure never silently falls back to Codex.
- `designer/one_shot.py` and the standalone verifier-compile batch mark their
  physical one-shot requests explicitly. Builder, reachability, and every
  session/repair loop remain agentic Codex calls.
- The strengthened request contract exposed two fake verifier `Profile`
  fixtures missing the newly required direct eligibility fields. The fixtures
  now declare their tool-free/output-schema contract and assert the emitted
  request mode. This is a deterministic test-fixture compatibility repair,
  not a production semantic or model repair.
- Static audit finds `AsyncOpenAI` only in `direct_llm.py`; pipeline modules
  still use `InvocationBackend.invoke()`.

## Quality evidence

- Focused Direct/Scheduler/Verifier regressions: `20 passed`; the full
  verifier-contract module: `32 passed`.
- Final complete suite: `678 passed, 2 skipped` in `871.92s`; it emitted only
  two known Python multiprocessing-fork deprecation warnings.
- `uv run ruff check agent_world tests/agent_world`, `uv run mypy agent_world`
  (`137` source files), and `git diff --check` passed.
- Scoped format checks for every file changed in this phase passed. Repository-
  wide `ruff format --check` reports `94` pre-existing, out-of-scope format
  drifts; they were not bulk-rewritten in the user's dirty worktree.

## Real one-node diagnostic evidence

- Labeled diagnostic root:
  `.agent-world-live/test-node-20260724T165538Z-e59acca2f12d`.
- The rig copied the original scope state, retained committed ancestors as
  inputs, superseded only the target head, and invoked the real target leaf.
  It did not replay the captured target output.
- The real span records `backend=direct_llm`; its safe model field is
  `gpt-5.3-codex-spark`, with one recorded Direct completion event. Fresh
  target attempt: `attempt:a54b349778579958092b5bc9`; evaluation:
  `evaluation:c07096450aefda31deb6b634`; validation report:
  `validation-report:attempt:a54b349778579958092b5bc9`.
- Actual usage was one Agent turn / `37,165` LLM tokens; unknown upper bound
  was `28,371`; the single-node reservation was `65,536` tokens / `2,730`
  seconds. The result was `diagnostic_only=true` and `releasable=false`; no
  Registry or consumer path was entered.
- Terminal result was the honest deterministic validation failure
  `architecture_resource_missing` at `state_entities`.
- This live run predated the explicit SDK zero-retry correction. It therefore
  proves real Direct routing and structured execution, but is not claimed as
  evidence of exactly one underlying HTTP attempt. The zero-retry guarantee is
  instead deterministic and code-enforced. Repeating the same semantic target
  merely to re-observe transport would violate the recorded A→B→A stop rule.

## Frontier and stop discipline

- The earlier Direct observation at
  `.agent-world-live/test-node-20260724T164958Z-0e8cb27deee7` consumed one
  real turn / `32,710` actual tokens and reached
  `fidelity_claim_reference_unknown`. It lacked the subsequently added safe
  adapter label, so it is diagnostic evidence only.
- The labeled Direct run returned `architecture_resource_missing`, the same
  root issue seen in the preceding Spark T0 run. The frozen-input sequence is
  `architecture_resource_missing → fidelity_claim_reference_unknown →
  architecture_resource_missing` (**A→B→A**).
- Classification: semantic/contract variability, not a Direct transport,
  credential, isolation, retry, or release failure. No prompt/skill change,
  retry-ceiling change, gate relaxation, or semantic repair was made in T0.5.
  Per the plan, further identical target runs stop here. Any semantic remedy
  is deferred to ordered T1 work, beginning with deterministic BC-44.

## Credential and release audit

- The labeled diagnostic root scanned `9,820` regular files. API-key and
  base-URL value matches were both `0`; neither environment value was printed.
- There were `0` surviving `/dev/shm/agent-world-codex-sqlite-*` directories.
  Direct starts no subprocess; the check remains a shared redline audit.
- No raw prompt, transcript, credential value, base URL value, sealed case,
  Registry artifact, or consumer result is recorded here.

## Phase boundary

T0.5 is complete as a transport/routing phase: both backends remain real
implementations behind `InvocationBackend`, Direct has an enforced no-hidden-
SDK-retry boundary, and the real target evidence remains diagnostic-only rather
than a success replay. The target's semantic failure is not renamed as success.
The next allowed work is T1, beginning with the deterministic BC-44
classification regression; T2 and T3 remain blocked.
