# T0 minimum report — one-node diagnostic rig

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Request and execution identity

- Scope/request: `generate-job:77330c4603201205c648ad65`.
- Target: `design|world_architecture|world_architecture||`.
- Git revision: `26ae43481c2226312a1f84028cf978f1563f01f1`.
- Spark configuration: gitignored
  `.agent-world-live/doctor-gpt53-codex-spark/config.toml`, digest
  `sha256:301bac21e513ad4aba7b45000e058f7a9bf26a1c0fc32f48af12d86fa2b7451c`.
- Model/provider/profile: `gpt-5.3-codex-spark` /
  `agent_world_api_key` /
  `sha256:858bf3bba0df433c6ee6d847a1761ae08d222589a87fbb95bb7a927f479f53ef`.
- The model order is `grok-4.5` → `gpt-5.3-codex-spark` → `gpt-5.4-mini`.
  Grok was stopped at the plan's A→B→A condition; Spark is the first
  authorized fallback, not a replacement replay.

## Reproducible single-node evidence

- The harness copied the frozen source state, retained the complete committed
  ancestor closure, superseded only the target head, and performed one real
  `dispatch_one`. The new attempt is
  `attempt:a54b349778579958092b5bc9`.
- Target evaluation: `evaluation:c07096450aefda31deb6b634`; validation
  evidence: `leaf-validation:attempt:a54b349778579958092b5bc9`.
- Invocation completed on the real Codex SDK path in 173,592 ms with one Agent
  turn and 61,427 actual LLM tokens. Unknown upper bound was 4,109 tokens;
  the single-node reservation was 65,536 tokens / 2,730 seconds.
- The isolated result is `diagnostic_only=true` and `releasable=false`; no
  Registry or consumer path was entered.

## Result, classification, and frontier

- Terminal result: deterministic validation failure
  `architecture_resource_missing` at `state_entities`.
- Deterministic owner: `designer/service.py`'s world-architecture contract;
  it requires at least one state entity to own a core world resource.
- Bad-case route: semantic/contract output failure, not provider
  infrastructure, credential, retry, or release evidence. No repair was
  authorized or attempted in T0.
- Frontier transition: provider A→B→A on Grok stopped as non-progress;
  Spark then exposed one precise semantic blocker (`0 → 1`), classified as
  **advance** because it is a new, deterministic, owner-addressable issue.

## Credential and release audit

- The diagnostic root scanned 9,873 files with zero API-key/base-URL value
  matches and zero surviving `/dev/shm/agent-world-codex-sqlite-*` directories.
- No raw prompt, transcript, credential value, base URL value, sealed case,
  Registry artifact, or consumer result is recorded here.

## Phase boundary

T0 is complete: it has deterministic harness tests and a real target execution
that produced a fresh validation report rather than replaying a captured
output. The T0 execution is a failure by design, not a released environment.
The next phase is T0.5, followed only by the ordered T1 bad cases.
