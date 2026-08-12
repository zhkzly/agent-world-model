# Research: cross-layer review — ToolSemantics Feedback progress

- Query: Independently review the post-E2E repair plan for parsed Direct semantic Feedback and ToolSemantics-only A->B strict progress.
- Scope: internal
- Date: 2026-08-12
- Decision: allow
- Plan digest: `sha256:a8431783859b3875786dc3bdc8320b0100309149372b558aad931db480d241e9`
- Plan revision: `1/2` (revision count: 1 of 2)
- Scope classification: coordinated cross-node, but tightly contained to the Direct design correction boundary: the shared Direct message reconstruction changes for parsed semantic corrections, while only the `tool_semantics` physical family may receive a second semantic correction.

## Decision

Allow the exact plan digest above. It is the smallest coherent repair for the failed Direct leaf: it reuses the existing four-message Direct adapter capability, preserves the original task and acceptance contract, and gives exactly one already-authorized `ToolSemantics` strict-progress continuation. It does not create a feedback service, a new node, a generic retry loop, a route/model fallback, or a downstream semantic change.

This allow is limited to the stated plan. The implementation must make the `2`-correction value structurally unavailable to every node other than the `direct_llm` `tool_semantics` node (or equivalently enforce that restriction in the third-proposal eligibility predicate), and must test that restriction. That is the plan's stated “only ToolSemantics” invariant, not a new framework feature.

## Trigger and evidence

- Trigger: real Direct terminal `run_bb8b2474bfd34507b1b73f7856c77ee3` at `design/tool_semantics[reserve_tool]`.
- The persisted Diagnosis records parsed semantic issue A on attempt 1, a different parsed semantic issue B on attempt 2, normal measured provider completion for both, no format/transport/credential/Skill/Candidate/Judge/Registry failure, and rejected/not-published terminal state (`research/diagnosis-tool-semantics-feedback-progress.md:24-46`).
- The same record identifies the first causal deviation: `NodeSpec.local_corrections` accepts only `0|1`, and `GraphRunner` executes only two proposals despite A->B progress (`research/diagnosis-tool-semantics-feedback-progress.md:69-77`).
- PAC-164 independently records the fresh public E2E stopping at the same ToolSemantics shard, with no publication, and names this exact plan digest as the next gate (`research/product-alignment-checkpoints.md:3377-3396`).
- The plan file hashes to the exact supplied digest; its revision is `1/2` (`research/tool-semantics-feedback-progress-plan.md:1-65`).

## Product target and affected trust boundary

The target remains: an arbitrary natural-language `EnvironmentRequest` becomes an evidence-grounded executable environment, is independently verified in a real isolated boundary, is released as an immutable Registry `EnvironmentPackage`, and is exposed only through safe Observe facts.

The changed boundary is the framework-owned local correction admission between an uncommitted Direct `ToolSemantics` proposal and the next Direct invocation. Designer owns the semantic proposal/compiler boundary; GraphRunner/framework owns eligibility, issue comparison, attempt counting, validation, commit, terminal Finding, and release control. The Direct LLM has no Skill, tools, workspace, routing, budget, Gate, Judge, or release authority.

## Files found

- `AGENTS.md` — project source-of-truth and pre-change/real-failure gates.
- `docs/agent-world-environment-generation.zh.md` — canonical feedback, bounded-correction, Direct, and downstream product contract.
- `docs/direct-rewrite-execution-map.zh.md` — Direct-vs-Agent ownership and fixed-graph boundary.
- `.trellis/workflow.md` — failed-real-proof sequencing and fresh critic gate.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — same-conversation Feedback and true-boundary proof rules.
- `.trellis/spec/agent_world/backend/index.md` — Direct no-Skill, actionable diagnostics, ToolSemantics correction, and native structured-output rules.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd.md,design.md,implement.md,node-contracts.md}` — active child contracts and Direct downstream seams.
- `research/diagnosis-tool-semantics-feedback-progress.md` — Diagnosis Record for the failed E2E.
- `research/tool-semantics-feedback-progress-plan.md` — plan under review.
- `research/product-alignment-checkpoints.md` — safe persisted Observe/PAC summary for this run.
- `agent_world/{invocation.py,design.py,graph.py,candidate.py,observe.py}` — current implementation boundary and consumers.

## Code patterns and review facts

### Parsed Direct semantic Feedback

The plan's feedback shape is required and compatible.

- `DirectChatBackend` already reconstructs `system -> original user -> previous assistant -> feedback user` and keeps the same strict JSON-object response mode (`agent_world/invocation.py:129-180`). No new provider API, context manager, memory layer, Agent session, or hidden instruction surface is necessary.
- The current design helper uses that path only for `direct_response_not_json`; parsed semantic corrections instead mutate the original JSON task with a `correction` field (`agent_world/design.py:567-603`). This is the observed protocol defect.
- The existing closure retains raw malformed output only in memory for format Feedback (`agent_world/design.py:621-670`). The allowed parsed semantic extension is to retain only the immediately preceding parsed object as ephemeral strict canonical JSON, pass it as the assistant turn, and place only the safe four-field packet plus complete-replacement/self-check instruction in the next user Feedback.
- The original system message, original user task bytes, frozen projection, output shape/model, compiler, and strict JSON-object transport must remain unchanged. The old JSON `correction` field must not carry the semantic packet on that follow-up. Neither rejected proposal text nor rendered Feedback may enter ArtifactStore, WorkRecord, package, or Observe.
- This follows the explicit same-conversation rule: Feedback is the next user turn; the rejected answer is only the prior ephemeral assistant turn; no Direct provider `instructions`, server continuation, Agent workspace/session, or durable transcript is authorized (`.trellis/spec/guides/agent-llm-node-debugging.md:17-50`).

### ToolSemantics-only strict progress

The plan's bounded A->B rule is required and sufficiently narrow.

- Current `NodeSpec` permits only `0|1` local corrections and the graph declares `tool_semantics` as a Direct node with the default one correction (`agent_world/graph.py:38-76`, `agent_world/graph.py:171-181`).
- Current GraphRunner hard-codes two attempts and authorizes only attempt-one correction for a model node (`agent_world/graph.py:466-555`, `agent_world/graph.py:671-680`). That exactly explains the recorded terminal; it is not evidence for a validator, route, model, Skill, or candidate change.
- A second correction is allowed only for the same uncommitted `tool_semantics` coordinate after two parsed semantic `CorrectionPacket`s whose exact `(code, path, violated_condition, expected_category)` tuples differ. The third proposal is absolute final: a third invalid result produces terminal evidence/Finding and no fourth invocation.
- Same tuple A->A stops after two proposals. Any first or second `direct_response_not_json` path may use only its pre-existing first format Feedback turn and never unlocks a third call. Provider/transport/retryable/framework/candidate terminals do not become semantic corrections. The existing transport policy and configured fallback are not changed or newly exercised by this approval.
- This is consistent with the source contract: A->B is progress rather than success, the second correction needs code-proven strict progress, and the no-progress key is the full safe issue tuple (`docs/agent-world-environment-generation.zh.md:423-441`; `.trellis/spec/guides/agent-llm-node-debugging.md:39-50`).

## Impact chain and compatibility

```text
unchanged frozen ToolSemantics input + original Direct task
  -> ephemeral prior assistant + framework-authored Feedback user turn
  -> unchanged Direct output model and ToolSemantics compiler
  -> same ToolDraft/ArtifactEnvelope/WorkRecord output on success
  -> WorldRules -> CurriculumPlan -> TaskRequirement -> Modeling Gate
  -> unchanged EnvironmentDesign -> CandidateBuild/Integration/Verifier/Judge
  -> Package -> Registry -> safe Observe projection
```

- `ToolSemantics` still compiles and commits the same `ToolDraft` artifact from the same frozen architecture/shared/evidence inputs (`agent_world/design.py:1542-1567`). No changed field reaches WorldRules, Curriculum, TaskRequirement, or Modeling Gate.
- Design edges require committed ToolSemantics before WorldRules, TaskRequirement, and Modeling Gate can consume it (`agent_world/graph.py:336-358`). On failure, none of those downstream design nodes may run.
- CandidateGraph is invoked only after a complete Design succeeds; its Build/Integration/Judge/Package/Registry chain therefore has no new input, owner, ABI, or release decision (`agent_world/design.py:2173-2248`, `agent_world/candidate.py:554-655`).
- Observe already projects safe work/finding/release facts from durable records and does not use prompt/proposal text (`agent_world/observe.py:498-537`). One extra allowed Direct operation/attempt uses the existing evidence/attempt schema; no Observe schema or control authority changes.
- Future Repair remains untouched: this is a local uncommitted correction, creates no RepairAction/route/invalidation, and does not claim the bounded-repair child exists. Future Expand consumes only exact released Design/package lineage; future Consumer consumes only an exact released package. Neither receives a new contract, Artifact kind, or behavior from this plan.

## Ownership and consumer compatibility

- **Framework / GraphRunner:** sole owner of attempt count, safe tuple comparison, commit/terminal behavior, and the ToolSemantics-only cap. The model cannot request a third call or choose a route.
- **EnvironmentDesigner / Direct LLM:** owns only a complete replacement semantic proposal for the same frozen tool. Direct remains no-Skill/no-tool/no-workspace.
- **WorldRules, Curriculum, TaskRequirement, Modeling:** consume only a successfully committed unchanged ToolSemantics artifact; otherwise remain unreachable.
- **Builder, Judge, Registry, Observe:** consume the unchanged compiled Design/Candidate/evidence schemas; they receive neither prior proposal nor Feedback text.
- **Repair, Expand, Consumer (future):** compatibility is preserved by intentional non-change to Artifact, package, lineage, Registry, and public Episode seams.

Keeping the current semantic revision is acceptable only in this narrow sense: the accepted source/output contract and the first request's frozen projection remain unchanged, while correction presentation and the bounded local allowance are repair policy. This approval does not authorize reuse or adoption of a historical corrected commit across the changed correction mechanism, nor does it weaken acceptance validation.

## Smallest allowed implementation and proof

1. Reuse the existing Direct backend's `previous_assistant`/`feedback` parameters for parsed semantic correction; do not add an abstraction or modify Direct route/model/fallback behavior.
2. Keep one shared Direct helper, but preserve original task bytes and output contract. Retain one prior parsed proposal only in the in-memory operation closure as strict canonical JSON; discard it after the current node transaction.
3. Permit `local_corrections=2` only for `tool_semantics`; preserve `0|1` behavior for all other current nodes. Change the runner from a fixed two-attempt loop to the declared bounded limit, with the second-correction predicate limited exactly to ToolSemantics A->B safe parsed progress.
4. Leave compiler acceptance, validators, `CorrectionPacket`, topology, ArtifactEnvelope/WorkRecord/Observe/package schemas, Agent nodes, Candidate/Judge/Registry, and future-child seams untouched.

## Smallest deterministic checks

- Inspect the actual Direct request for a parsed semantic correction: exactly four messages, unchanged original system/user strings, canonical prior assistant JSON, and a concise safe feedback user message; no semantic packet in the original task body.
- Assert `tool_semantics` A->B->valid produces exactly three operation and attempt records and one normally shaped committed ToolSemantics artifact.
- Assert A->A stops at two proposals; A->B->invalid stops at three; any fourth invocation fails the test.
- Assert both format combinations (format first, or A then format) do not unlock a third proposal; transport/retryable/framework/candidate terminal cases receive no semantic correction.
- Assert a non-ToolSemantics node cannot be configured or admitted for the second semantic correction, and all other current Direct nodes retain their one-correction limit.
- Assert rejected proposal and Feedback text are absent from persisted artifacts and Observe; run focused tests, full `pytest`, Ruff, mypy, compileall, and the legacy firewall.

## True-boundary proof

After the independent implementation check, run the exact frozen `reserve_tool` parent closure against the real Luna Direct route and read Observe immediately. The proof must show either:

- A then different B authorizes exactly one final ToolSemantics Feedback turn and commits within three total proposals; or
- it terminates safely with no fourth proposal.

The safe proof must retain normal measured/unknown usage and prove the Direct no-Skill context/request shape. Only if that leaf commits may the next gate run one fresh public natural-language Direct E2E; stop at its first terminal and read Observe. A new terminal starts a new Diagnosis Record and invalidates this allow for any broadened repair.

## Non-claims

- No proof of a full Design, Candidate, Integration, Judge, package, Registry publication, Direct E2E success, Expand, or Consumer/SFT/RL outcome.
- No generic feedback service, issue aggregation, prompt framework, memory/RAG, context manager, new graph/node, global scheduler, RepairAction/RepairLedger, model/route fallback change, or Agent/session/Skill change.
- No validator relaxation, format coercion, raw-proposal persistence, extra token/output limit, or new transport retry behavior.
- No claim that A->B establishes semantic success; only a compiled commit does, and downstream product evidence remains separately required.

## Related specs and references

- `docs/agent-world-environment-generation.zh.md:423-460, 601-646` — canonical bounded Direct correction, ToolSemantics, and no-template/no-hidden-context rules.
- `docs/direct-rewrite-execution-map.zh.md:49-60, 62-100` — fixed-node graph, Direct ownership, and downstream Candidate/Judge separation.
- `.trellis/spec/guides/agent-llm-node-debugging.md:12-52, 172-189` — feedback message shape and proof ordering.
- `.trellis/spec/agent_world/backend/index.md:593-705, 1190-1244, 1717-1757` — Direct no-Skill, actionable diagnostics, and bounded ToolSemantics correction projection.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:127-152, 381-400, 731-819` — current local-correction, ToolSemantics, and package/Registry handoffs.
- External references: none; this decision relies on the repository's governing product contract and persisted real-run evidence.

## Caveats / Not Found

- The raw durable state directory for `run_bb8b2474bfd34507b1b73f7856c77ee3` was not present in this worktree or the adjacent staged-state roots at review time. The persisted Diagnosis Record and PAC-164 provide the safe Observe facts; raw proposals are intentionally unavailable and were not sought or reconstructed.
- The A->B evidence proves only a changed first reported safe issue, not that issue B was absent from attempt 1. The source contract defines that tuple change as strict local progress for this bounded policy; it is not a claim about total issue-count reduction.
- This allow expires if the plan digest, Direct message/trust boundary, or relevant real scene changes.

## Next permitted gate

Dispatch the bounded implementation only for this allow and exact digest. Then perform the independent implementation check, the specified deterministic checks, and the smallest real `reserve_tool` true-boundary proof before any fresh public E2E. Add this current allow record to the task's implementation/check context only from the coordinating main session.
