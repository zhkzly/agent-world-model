# Research: cross-layer review — ce30e40c Design text correction

- Query: Independently review plan `sha256:ce30e40cd25b65758400e27636c3a7df85ea4bb27658fb8fbe9f1a6376b5f669`, revision 1/2, after the real SharedTool text-feedback failure.
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan digest: `sha256:ce30e40cd25b65758400e27636c3a7df85ea4bb27658fb8fbe9f1a6376b5f669` (verified against the complete plan file).
- Plan revision: `1/2`.
- Scope classification: local feedback/observability repair at the existing common Design text-validation boundary. It has common-helper reach across current Design recipients, but does not change an Artifact schema, graph edge, owner, route, retry authority, release decision, or downstream ABI.

## Product Target and Trigger

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in an isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. This repair advances only the bounded Design correction handoff; it does not establish a Design, Candidate, Judge, Registry, or product completion.

The real evidence is `run_f3a75200f65f4c93b84aa749eadac11e`. Its safe Observe projection records one failed Designer-owned Direct `shared_tool_semantics` Work at shard `1-2-3-4-5-6-7`, no output, one blocking Finding, and `release=not_published`. The two persisted attempts show invocation 1 authorized a correction with `$.ordering`, expected `string`, and the collapsed condition; invocation 2 then failed under the existing two-call bound. The failure evidence contains no Provider text.

The Diagnosis correctly attributes this to the common `_text` predicate rather than to a SharedTool semantic contract, schema, bound, route, Skill, model, or retry-policy defect. See [diagnosis-design-text-correction-collapsed.md](diagnosis-design-text-correction-collapsed.md:17), especially its three-branch attribution and no-leak requirement at lines 27-47.

## Files Examined

- `AGENTS.md` — product source-of-truth, real-failure gate, safe Observe, and no-cross-authority rules.
- `docs/agent-world-environment-generation.zh.md` — canonical ownership, exact correction-brief, Direct/Agent, and immutable-work contracts.
- `docs/direct-rewrite-execution-map.zh.md` — Direct LLM versus tool-enabled Agent boundary.
- `.agents/skills/agent-world-cross-layer-critic/SKILL.md` — independent critic decision and proof requirements.
- `.trellis/spec/guides/foundry-product-alignment.md` and `agent-llm-node-debugging.md` — local evidence/non-claim discipline.
- `node-contracts.md` — fixed `CorrectionPacket` and SharedTool text contract.
- `design-text-correction-precision-plan.md` — reviewed revision 1/2 plan.
- `diagnosis-design-text-correction-collapsed.md` — persisted causal diagnosis.
- `agent_world/design.py`, `agent_world/graph.py`, and `agent_world/contracts.py` — validator, packet, invocation, identity, and correction consumers.
- `config/.agent-world-runs/runs/run_f3a75200f65f4c93b84aa749eadac11e/` — latest safe Observe/Work/attempt/failure evidence only.

## Findings

### Acceptance and safe feedback

`_text` currently accepts exactly a `str` whose stripped value is nonempty and has `len(stripped) <= limit`, then returns that stripped value; all three rejected cases collapse into one condition (`agent_world/design.py:110-118`). The plan preserves that predicate, caller limit, path, expected category, and normalized return while making only the safe `violated_condition` branch-specific. Therefore the common acceptance contract is unchanged if and only if the focused tests prove all accepted boundary cases still return the same stripped text.

The proposed conditions are the smallest safe observations available without original Provider content:

- wrong type: `value must be a string`;
- empty after strip: `value must be nonempty after stripping`;
- over the caller-declared limit: `value must use at most <limit> code points`.

The runtime already evaluates those facts locally; emitting the exact branch neither reveals the rejected value nor its actual length. It satisfies the canonical requirement to preserve a safe code, exact path, violated condition, and expected category rather than authorize a blind retry (`docs/agent-world-environment-generation.zh.md:428-438`).

### Owners and consumers

The producer/consumer chain is unchanged:

```text
_text -> DesignError/CorrectionPacket -> GraphRunner local-correction decision
      -> same Direct or Agent invocation, at most once -> compiler -> Work/Artifact
      -> later Design/Candidate/Judge/Registry consumers only after a commit
```

`CorrectionPacket` remains the same four-field, bounded, framework-owned data contract (`agent_world/contracts.py:95-110`). `GraphRunner` alone decides eligibility, persists the safe packet, and performs the existing second physical invocation (`agent_world/graph.py:481-515`); it does not route on the text of `violated_condition` (`agent_world/graph.py:516-538`). The existing Direct request carries that packet as data only (`agent_world/design.py:546-572`); the Agent request does the equivalent only for an already-authorized correction (`agent_world/design.py:525-540`). No Agent gains a Skill, tool, workspace, route, retry, graph, or release authority.

All current `_text` call sites are internal to `agent_world/design.py`: Research plan/synthesis, Architecture, RuleDraft rationale, SharedTool policy/ordering/compensation, and Curriculum text fields (for example `agent_world/design.py:477`, `657-663`, `857-883`, `979-1187`, `1300-1317`, and `1614-1784`). This is why a SharedTool-only special case is not the smaller repair: it would duplicate the same three-way predicate and leave identical existing Design correction recipients opaque. The common helper is allowed only because it keeps every caller's supplied limit and all accepted values unchanged.

### Semantic identity and reuse

The current runner derives `semantic_revision_digest` from the node declaration plus effective projection, output shape, prompt identity, route, and mounted Skill digest (`agent_world/graph.py:441-460`). The failed correction packet is dynamic attempt evidence, not part of that semantic material. The reviewed plan therefore may retain the current semantic revision and reusable accepted upstream parent artifacts, provided it does not change the acceptance predicate/normalization, model-visible base projection, output shape, prompt identity, route, or Skill.

This is an observability/feedback repair, not permission to reuse a failed SharedTool output: the observed run committed none. The canonical warning still applies: if implementation changes what is accepted, changes an effective model input beyond the existing authorized packet, or introduces an explicit validator-revision field into acceptance/reuse identity, that is a broadened semantic/reuse change and requires a new plan and critic. This allow makes no claim that a future acceptance-digest implementation may silently ignore such a revision.

## Exact Allowed Scope

Only the following is permitted:

1. Split the existing `_text` rejection reporting into the three plan-specified safe conditions, retaining the exact current acceptance predicate and stripped return.
2. Add focused tests in the existing Design test surface for all three rejection classes, accepted normalization, and the `SharedTool $.ordering` 160-code-point correction packet.
3. Leave caller limits, source models, compiler outputs, graph topology, `CorrectionPacket` shape, one-correction/two-call bound, semantic material, Direct/Agent route and Skill setup, Candidate path, Observe schema, and all downstream ABIs untouched.

Forbidden: any value/length persistence, diagnostic Artifact, SharedTool-only schema change, bound relaxation/increase, prompt prose, model/route change, retry change, Agent conversion, new node/helper/module/schema engine, or later-child work.

## Exact Checks and Same-Suffix Proof

Deterministic checks must prove:

1. non-string, blank/whitespace-only, and over-limit inputs produce exactly the three safe conditions at the original code/path/category;
2. accepted values at the relevant boundaries, including surrounding whitespace, normalize to exactly the prior stripped value;
3. a constructed SharedTool `$.ordering` item over 160 code points reaches the existing second Direct call with the exact safe condition, without raw value/actual-length persistence;
4. the two-call bound and all no-output/failure behavior remain unchanged.

Then run the plan's focused/full pytest, firewall, Ruff, mypy, compileall, diff, and 10,320-production-line ceiling checks, followed by an independent implementation check.

The real proof must be a **fresh, non-resume** diagnostic run using exactly the immutable Evidence and WorldArchitecture parent refs recorded by the failed Work (`design.evidence_graph:8cea941a9168ce53` and `design.world_architecture:8b0f1bcda8f37a24`), the same SharedTool shard `1-2-3-4-5-6-7`, Direct/no-Skill route, and existing per-node two-call bound. It may proceed only from a committed SharedTool to the same first ToolSemantics suffix; immediately read Observe after the terminal. A new failure starts a new diagnosis; a suffix pass permits only one fresh public Direct E2E under its normal gate.

## Non-Claims and Next Permitted Gate

This allow does not prove which hidden Provider value caused the prior failure, Luna behavior, complete Design, ToolSemantics completion, Candidate execution, Judge, Registry release, Direct E2E, Repair, Expand, or Consumer/SFT/RL. It also does not authorize interpreting the old failed SharedTool work as reusable or released.

Next permitted gate: implement only the exact scope above; after the independent deterministic check, perform the fresh same-parent suffix proof and read Observe.

## Related Specs

- `docs/agent-world-environment-generation.zh.md:421-445` — exact actionable diagnostics and one bounded correction.
- `docs/agent-world-environment-generation.zh.md:629-633` — correction brief is data-only and does not delegate control authority.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` §2 and §4 — fixed packet and SharedTool Direct contract.
- `.trellis/spec/guides/foundry-product-alignment.md` — deterministic evidence is not product completion.

## External References

None. This review is grounded in the repository's source-of-truth and durable safe run evidence.

## Caveats / Not Found

- Original Provider content and actual rejected text length were intentionally not read or persisted; the diagnosis and proof must remain safe under that uncertainty.
- The latest Observe scene reports the only Work as failed and non-published, while its top-level run status remains `running`. This record therefore requires a fresh non-resume suffix proof and makes no claim about fixing that separate terminal-projection condition.
- This allow expires if the plan digest, common-helper scope, trust boundary, or latest relevant real scene changes.
