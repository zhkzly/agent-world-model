# T0 interim stop report — provider A→B→A

Plan authority: `docs/plans/staged-test-and-debug-plan.md`. This is an
execution record, not a replacement for that plan.

## Scope and invariant audit

- Request/scope: `generate-job:77330c4603201205c648ad65`.
- Target coordinate: `design|world_architecture|world_architecture||`.
- Git revision: `26ae43481c2226312a1f84028cf978f1563f01f1` (the worktree had 35
  pre-existing/uncommitted paths; no commit or push was made).
- Agent profile: `environment-engineer` through `CodexSdkBackend` →
  `AsyncCodex`; model `grok-4.5`; provider id `agent_world_api_key`; profile
  digest `sha256:52f64d751bb9049f0e234b1143957958faad6ff05c38b74f09dc13a5276b11a8`.
- All target attempts copied the original scope state, superseded only the
  target coordinate, retained ancestors as inputs, and called the real leaf.
  They are all `diagnostic_only=true` and `releasable=false`; no Registry or
  consumer path was entered.

## T0 mechanism evidence

- Deterministic harness: focused tests prove complete ancestor closure,
  one-target supersede, exactly one real `dispatch_one`, and no release path.
- Real custom-provider doctor: `doctor --live-agent` completed through the
  production InvocationBackend/Codex SDK route after the routing adapter
  repair.
- The first post-routing target execution at
  `.agent-world-live/test-node-20260724T155913Z-ea3c54fc3bd2` completed and
  passed `design.architecture.closed`; it created a new target commit rather
  than replaying the captured target output.
  - Actual usage: 1 agent turn / 20,742 LLM tokens.
  - Unknown upper bound: 44,794 LLM tokens; reserved: 65,536 LLM tokens.

## Credential/base-URL audit

- That successful attempt exposed one materialization defect: Codex 0.144.4
  wrote runtime routing data to `logs_2.sqlite` under the copied profile root.
  The file was cleared immediately without reading its contents; the immediate
  rescan found zero value matches. This attempt is not accepted as the clean
  T0 evidence.
- Causal repair: `CodexSdkBackend` now directs the vendor SQLite plane to a
  private `/dev/shm` directory for one worker lifetime and removes it before a
  durable invocation result returns. There is no disk fallback.
- The repair's deterministic regression, focused tests, ruff, mypy, and diff
  check passed. A real doctor turn then passed; its root had zero value matches
  and no `/dev/shm/agent-world-codex-sqlite-*` survivor.
- The final T0 target root,
  `.agent-world-live/test-node-20260724T161248Z-e8387a9b4f68`, was scanned
  without printing credential/base-URL values: 9,877 files scanned, 0 matches,
  no memory-runtime survivor.

## Frontier and terminal evidence

| Trial | Result | Usage | Lattice state |
|---|---|---:|---|
| Initial builtin-provider target | authentication terminal | bounded | configuration boundary exposed |
| Custom-provider target | `turn_failed_provider_rejected` | 1 turn, unknown 65,536 | advance: provider selection proved |
| Custom-provider target | committed + validation passed | 1 turn, 20,742 actual | advance: true target execution proved |
| SQLite-isolated target | `agent_backend_turn_failed_provider_rejected` | 1 turn, 0 actual / 65,536 unknown | A→B→A; stop |

The last scene was read from the durable diagnostic root: overall `failed`,
frontier size `3`, stuck coordinate `design.world_architecture.world_architecture`,
reason `no_repair_authority`, next action hint `review_design_worldspec`.
Its terminal provider code is non-retryable at the scheduler boundary; no
automatic retry, prompt expansion, or gate relaxation was performed.

## Classification and stop reason

Classification: **budget / infrastructure / provider configuration**. The
failure occurs before semantic output (zero actual LLM tokens), while the same
profile's real doctor turn succeeds. It is not evidence of an
environment-engineer skill/prompt defect, a semantic contract defect, or a
valid reason to enter T0.5/T1.

The observed state is A→B→A for the same target/provider family. The plan's
anti-loop rule therefore stops further identical Grok retries. `grok-4.5`
remains the selected primary model, but is currently unusable for this T0
target until a changed diagnostic proves otherwise. The explicitly requested
fallback order is `grok-4.5` → `gpt-5.3-codex-spark` → `gpt-5.4-mini`.

A `gpt-5.4-mini` doctor probe was prepared only as an earlier fallback
investigation; its subsequently started `test-node` probe was interrupted
before a terminal node result and is discarded as phase evidence. It must not
be used to advance T0 or to replace the Grok evidence. The next model probe is
therefore `gpt-5.3-codex-spark`, beginning with the same real Codex-SDK doctor
route. No full e2e will be run.
