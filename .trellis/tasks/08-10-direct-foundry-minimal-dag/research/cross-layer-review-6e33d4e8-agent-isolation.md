# Research: cross-layer review — 6e33d4e8 agent isolation

- Query: Review whether appending two fixed Codex SDK isolation overrides and updating the exact tuple regression is the smallest coherent repair for the real singleton-Skill preflight failure.
- Scope: internal / pinned-SDK configuration evidence
- Date: 2026-08-11

## Decision

**Decision: allow**

- Plan digest: `6e33d4e88c9fc7f20442189d8b429cd3222cd8f4c062357ca863c85484bc27ff`
- Plan revision: `agent-preflight-isolation-plan.md`, first submitted repair-plan revision for this Diagnosis Record.
- Revision count: 1 of at most 2 for this diagnosis/plan lineage.
- Scope classification: local adapter-isolation repair.
- Trigger: a real pinned-SDK singleton-Skill preflight completed and closed but failed the adapter's post-turn physical surface check with `agent_skill_surface_unverified`.
- Affected trust boundary: framework-owned `CodexAgentBackend` SDK launch configuration and the model-visible Runtime-Skill surface. This is not a graph node, Agent authority change, Candidate process change, or release decision.

## Product target and plan digest

The product target remains: turn an arbitrary natural-language
`EnvironmentRequest` into an evidence-grounded executable environment,
independently verify it in a real isolated boundary, publish an immutable
Registry `EnvironmentPackage`, and expose only safe facts through Observe.

The proposed repair advances only the prerequisite that every tool-enabled
Agent turn used on that path begins with exactly its selected product Runtime
Skill. It does not claim any semantic Agent result or downstream product
completion.

The allowed implementation is exactly:

1. Append `skills.bundled.enabled = false` and `features.plugins = false` to
   the existing `_private_provider_overrides(route)` tuple.
2. Update the one exact `CodexConfig.config_overrides` tuple assertion.

No other source, test, configuration surface, or plan artifact is within this
allow.

## Diagnosis and evidence

The persisted Diagnosis Record establishes a causal hypothesis before this
plan: the target bundle digest remained unchanged, the fresh isolated home
contained only the target before the turn, and the post-turn mounted names
became `(.system, target)`. The SDK created bundled system Skills and plugin
startup state; both temporary homes and the proof fixture were cleaned up.
The existing rejection must remain fail-closed and must not ignore `.system`.

Pinned-SDK configuration evidence recorded by the diagnosis says
`skills.bundled.enabled=false` prevents `skills/.system`, and adding
`features.plugins=false` prevents plugin cache startup. The local pin is
`openai-codex==0.144.4`.

## Impact chain and compatibility

```text
Agent Node (ResearchPlan/ResearchSynthesis/BuildPlan/VerifierIntent/CandidateBuild)
  -> DesignExecutor or CandidateExecutor
  -> one CodexAgentBackend.invoke_json call
  -> _private_provider_overrides(route)
  -> ephemeral AsyncCodex SDK thread and one mounted Runtime Skill

Direct LLM -> DirectChatBackend                         (unchanged)
Candidate process -> Integration -> Judge -> Package -> Registry -> Observe (unchanged)
```

- Producer/owner: `CodexAgentBackend` remains the sole framework owner of
  private provider setup, temporary `CODEX_HOME`, session close, cleanup, and
  before/after singleton validation.
- Immediate consumers: both DesignGraph Agent work and CandidateGraph Agent
  work call that same backend; the change is applied inside `_call`, therefore
  covers both primary and fallback route launches without changing `AgentRoute`
  or their Skill/workspace/instruction projections.
- Later consumers: Candidate, Integration, Judge, ReleaseKernel, Registry and
  Observe consume committed framework artifacts, not SDK config overrides. No
  Artifact, WorkRecord, lineage, package, or receipt schema changes.
- Repair compatibility: current R9 persists route-free Findings and stops;
  this change creates no Finding route, retry policy, budget authority, or
  repair mechanism. The later bounded-repair child remains compatible.
- Expand compatibility: future Expand reuses DesignGraph/CandidateGraph Agent
  boundaries. It obtains the same fixed isolation behavior without a new
  policy/profile/plugin system; no Campaign behavior is implemented or claimed.
- Consumer compatibility: future Consumer begins from exact Registry packages
  and has no SDK-launch/config consumer. Its package/private-evaluator boundary
  is unchanged.

The model loses unrelated bundled/plugin surfaces and gains no additional tool,
permission, workspace, control-plane, or release authority. The existing
post-turn physical check continues to reject any residual extra Skill surface.

## Files found and code patterns

- `agent_world/invocation.py:76` — the single private-provider override tuple;
  `:220-259` materializes the one Skill, invokes the SDK, and retains before/
  after singleton checks; `:286-309` owns session close.
- `tests/test_agent_route_config.py:178-303` — backend-spy test asserts the
  exact config tuple, isolated environment, single Skill, session close, and
  cleanup.
- `agent_world/foundry.py:31-35` — composition root creates exactly one
  `CodexAgentBackend` shared by Designer and Builder.
- `agent_world/design.py:271-305` — DesignGraph Agent work delegates to that
  backend; Direct LLM remains on `DirectChatBackend`.
- `agent_world/candidate.py:649-690` — CandidateGraph Agent work delegates to
  the same backend while preserving operation provenance.
- `node-contracts.md:171-197` — exact three-field route, one ephemeral SDK
  thread, singleton Skill, close/cleanup, no profile/capability/plugin system.
- `node-contracts.md:558-587, 720-783` — Candidate, Integration, Judge,
  Package and Registry use separate contracts and do not consume SDK override
  state.
- `research/diagnosis-agent-preflight-bundled-surfaces.md` — Diagnosis Record;
  `research/agent-preflight-isolation-plan.md` — the reviewed plan;
  `research/product-alignment-checkpoints.md:953-992` — PAC-35 and PAC-36.

## External references

- Local dependency pin: `pyproject.toml` and `uv.lock` specify
  `openai-codex==0.144.4`.
- Configuration behavior is evidenced by the pinned SDK `config/read` and
  real preflight recorded in the Diagnosis Record. The reviewed public upstream
  context is [Codex issue #19265](https://github.com/openai/codex/issues/19265),
  which documents `skills.bundled.enabled=false` as the bundled-Skill control;
  it is corroborative only, not a substitute for the pinned local proof.

## Smallest checks and proof

1. Run the focused deterministic route/backend regression that asserts the
   complete fixed override tuple, followed by the normal deterministic suite.
2. Run one fresh, temporary real nonce preflight through the existing adapter.
   It must prove the returned initial Skill list is the exact singleton and
   returns the bundle-only marker; the mounted bundle digest is unchanged; the
   temporary home is non-ambient; the session closes exactly once; cleanup
   succeeds; and neither `.system` nor plugin startup cache appears before
   deletion.
3. Read Observe after that real proof terminal. Because the preflight is
   outside product graphs and creates no Direct run, do not invent an Observe
   scene; record only the safe proof outcome. Any new failed terminal requires
   a new Diagnosis Record and critic review before another change.

## Explicit non-claims and constraints

- This allow does not prove Research semantics, Direct LLM behavior,
  CandidateBuild, Integration, Judge, Package, Registry publication, Observe,
  Repair, Expand, Consumer, or Direct E2E.
- Do not ignore `.system`, delete SDK-created files during the turn, suppress
  the post-turn check, use a per-Skill denylist, dynamically discover SDK
  features, parse plugin catalogs, or add a new preflight runtime node.
- Do not add a user-configurable feature/config/profile system, permission or
  capability matrix, plugin manager, hook/MCP loader, configurable sandbox,
  callback lifecycle, worker protocol, route/fallback change, graph change, or
  downstream Candidate/Package/Repair/Expand/Consumer work.

## Next permitted gate

Implementation is permitted only for the two fixed tuple entries and the exact
tuple regression update. It must be followed by deterministic checks and the
single real adapter preflight above. This allow expires if the plan digest, the
adapter isolation trust boundary, or the relevant real-proof evidence changes.

## Caveats / Not Found

- No graph run, Candidate, package, Registry receipt, release, or Observe scene
  exists for the failed preflight; none may be inferred from adapter cleanup.
- The real preflight remains required evidence. Static tuple coverage alone
  cannot prove the pinned SDK honors both overrides at runtime.
