# Research: Cross-layer review — whole-condition ToolSemantics Feedback

- Query: Independently review revision 1 of the whole-condition Feedback repair after real Direct run `run_9916d45626bf4ab3b11535c96fe50aa1`, including chronology honesty, correction authority, compiler acceptance, cross-node consumers, and the smallest proof.
- Scope: internal
- Date: 2026-08-12

## Decision

- Decision: **allow**
- Plan digest: `76c57a0fd6aff39b39f105936d9952b14539a9917aa193a08ae0bab1ab478cd8` (SHA-256 verified against the complete plan file)
- Plan revision: 1
- Revision count: 1 of at most 2 for this Diagnosis/plan lineage.
- Scope classification: coordinated but bounded within the Direct Design feedback boundary. The shared Direct Feedback renderer reaches current Direct semantic nodes, and the shared RuleDraft effect-value diagnostic reaches ToolSemantics, WorldRules, and TaskRequirement; no committed Artifact, graph edge, acceptance rule, or downstream ABI changes.
- Trigger: the safe terminal at `design/tool_semantics[reserve_tool]` in real Direct run `run_9916d45626bf4ab3b11535c96fe50aa1`.
- Affected trust boundary: framework-authored, next-user Feedback after an uncommitted Direct proposal. Designer/framework owns diagnosis text and compilation; GraphRunner owns correction admission, the hard ceiling, commit, terminal Finding, and non-release. The Direct model only returns a complete replacement.

## Product Target

Turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This allow advances only the uncommitted `reserve_tool` Direct leaf. It neither proves nor authorizes a later Design suffix, Candidate, Integration, Judge, Package, Registry, Direct E2E, Repair, Expand, or Consumer result.

## Findings

### Evidence and chronology

- The real leaf used Direct `gpt-5.6-luna`, JSON-object response mode, and no Skill/tool/workspace. All three responses parsed as JSON objects; the old format terminal did not recur (`research/direct-actionable-feedback-live-proof.md:35-48`).
- The safe Observe facts show: A at `$.preconditions[2].when` (array cardinality), then B at `$.transitions[3].effects[2].value`, then C at `$.transitions[4].effects[2].value` with B's same condition; it stopped after the third proposal with no fourth call, no ToolSemantics Artifact, and no publication (`research/direct-actionable-feedback-live-proof.md:37-48`; `config/.agent-world-runs/runs/run_9916d45626bf4ab3b11535c96fe50aa1/run.json`).
- Raw proposals are intentionally unavailable. C may have already existed in proposal two or may have been introduced by complete regeneration; the evidence cannot distinguish those alternatives and this review does **not** claim otherwise (`research/diagnosis-tool-semantics-feedback-global-repair.md:87-90`).
- The safe failure evidence records only the terminal C path, condition, and expected category. It does not contain a second observed B-path occurrence or rejected proposal text.

### Whole-condition Feedback remains bounded and actionable

The approved wording must make two facts explicit: the packet path is **one observed occurrence**, and the model must inspect the complete immediately preceding proposal and correct every occurrence governed by that same reported condition and expected category before returning one complete replacement. It must not say or imply that framework already observed any additional occurrence.

This is actionable next-user Feedback, not an issue-aggregation, validator, or retry system:

- Current Direct R9 intentionally carries one first compiler-detected `CorrectionPacket`, rather than an issue-aggregation subsystem (`node-contracts.md:125-152`). The packet remains exactly `code`, `path`, `violated_condition`, and `expected_category`.
- The shared renderer currently has the path-local sentence “Change the response at that path” (`agent_world/design.py:111-120`); the diagnosis identifies that wording as the supported causal weakness (`research/diagnosis-tool-semantics-feedback-global-repair.md:94-108`).
- The model already receives only the original frozen task, the immediately preceding proposal in ephemeral assistant position, and the framework Feedback user message (`agent_world/design.py:575-604`, `626-675`). The revised sentence therefore instructs the model how to self-check the complete replacement; it does not add model-visible framework authority or undisclosed diagnostics.
- GraphRunner still receives one packet, still owns eligibility, and still permits a second semantic correction only for the existing ToolSemantics A-to-B strict-progress case. Its third proposal remains terminal (`agent_world/graph.py:494-550`, `684-724`). No new call, counter, route, fallback, or retry authority is introduced.
- Format Feedback must remain concrete and root-wide. The implementation may not reinterpret a root parse condition as evidence of multiple semantic issues, and it must preserve the existing format-versus-semantic hard-stop behavior.

### Exact effect-value diagnostic is acceptance-equivalent

The plan's requested condition text is accurate only when scoped to `EffectDraft.value`:

- A direct literal is a JSON scalar (`null`, boolean, integer, finite float, or string) or a list of at most 32 such scalars; it is not wrapped in `{kind:"literal", value:...}` (`agent_world/design.py:172-176`, `213-216`).
- The only accepted object at this effect-value branch is exactly `{kind:"semantic_ref", semantic_index:<one-based frozen binding index>}`. A semantic-ref object with a non-frozen index takes the separate `semantic effect reference must be frozen` failure (`agent_world/design.py:443-465`).
- `preserve` and `reject` retain their separate `null`-only condition (`agent_world/design.py:466-472`).

Thus the approved wording may clarify direct finite scalar/scalar-list versus the exact semantic-reference object, but it must not change the accepted set, `expected_category="semantic_draft"`, list bound, frozen-index check, or special `preserve`/`reject` rule. The shared RuleDraft declaration already states this direct effect-value form (`agent_world/design.py:328`; `node-contracts.md:286-306`).

### Impact chain and compatibility

```text
shared RuleDraft compiler / safe DesignError
  -> unchanged CorrectionPacket schema
  -> shared Direct next-user Feedback rendering
  -> unchanged Direct request shape and ephemeral prior assistant turn
  -> unchanged GraphRunner eligibility and three-proposal hard stop
  -> [valid only] unchanged ToolSemantics Artifact
  -> WorldRules / Curriculum / TaskRequirement / Modeling Gate
  -> CandidateGraph -> isolated Judge -> Package -> Registry -> Observe
```

| Boundary | Sole owner | Compatibility fact |
| --- | --- | --- |
| Effect-value validation -> `CorrectionPacket` | Designer/framework | `_compile_rules` changes only safe diagnostic text; scalar/list/ref acceptance and `RuleDraft` output shape stay fixed. The helper is shared by ToolSemantics, WorldRules, and TaskRequirement (`agent_world/design.py:1475-1514`, `1574-1610`, `1947-1984`). |
| Packet -> Direct Feedback | Designer/framework | `_direct_feedback` remains an in-memory rendering of the same four safe fields. Direct remains no-Skill/no-tool/no-workspace and keeps its original system/user payload. |
| Feedback -> another proposal | GraphRunner/framework | Existing tuple-based strict-progress admission, format exclusion, and three-proposal maximum are unchanged. The model cannot request a fourth call or select a route. |
| Successful ToolSemantics -> later Design | DesignGraph | Later nodes consume only a successfully compiled ToolSemantics Artifact; its schema and content semantics are unchanged. A failed leaf produces no output and leaves downstream unreachable. |
| Candidate/Registry/Observe and future children | Their existing framework owners | They receive no Feedback text, raw proposal, changed Artifact kind, package field, lineage field, or release decision. Observe may display the revised safe condition as failure evidence, but its schema and read-only authority are unchanged. |

The current correction presentation is attempt-local policy/observability, not a change to the accepted source contract, frozen initial projection, output shape, route, or Skill. Keeping the existing semantic-revision declaration is therefore allowed only within this exact acceptance-equivalent Feedback scope; any change to acceptance, model-visible base projection, output model, route, or Skill requires a new plan and review.

## Smallest Allowed Implementation and Proof

1. Change only the existing Direct Feedback rendering in `agent_world/design.py` and the one shared effect-value `violated_condition` string. Keep the format path concrete/root-wide and do not change `graph.py`, node declarations, `CorrectionPacket`, compiler acceptance, parser behavior, Artifact/WorkRecord schema, routes, Skills, or downstream code.
2. Add focused regressions that prove all of the following:
   - the semantic Feedback calls the path one observed occurrence, requests inspection/correction of every matching same-condition/category occurrence in the complete prior proposal, requests one complete replacement and whole-object self-check, and neither contains raw proposal text nor extra framework control fields;
   - format Feedback remains a root-wide format instruction and retains the current format/semantic call limits;
   - a direct scalar, finite scalar-list (including the existing bound), and exact frozen semantic-reference object remain accepted; a literal wrapper/object is rejected with the revised condition; an invalid semantic reference and `preserve`/`reject` non-null cases retain their separate existing conditions;
   - the generic RuleDraft compiler behavior covers its ToolSemantics, WorldRules, and TaskRequirement consumers without changing their accepted output shape;
   - A -> B -> C still terminates after exactly three proposals with no fourth call, and no rejected proposal or rendered Feedback is persisted.
3. Run the plan's focused tests, full `pytest`, Ruff format/check, mypy, compileall, and legacy firewall. These are deterministic regression evidence only.
4. After independent implementation checking, run only the exact frozen-parent `design/tool_semantics[reserve_tool]` Luna leaf with the recorded EvidenceGraph, WorldArchitecture, and SharedToolSemantics refs. Read Observe immediately. A commit establishes only the unchanged ToolSemantics Artifact under the existing maximum; a new terminal starts a new diagnosis. Neither outcome authorizes a blind retry or E2E.

## Files Found

- `research/direct-actionable-feedback-live-proof.md` — latest real Direct leaf evidence and bounded non-release result.
- `research/diagnosis-tool-semantics-feedback-global-repair.md` — persisted causal diagnosis with explicit raw-proposal uncertainty.
- `research/tool-semantics-whole-condition-feedback-plan.md` — reviewed revision 1 repair plan.
- `agent_world/design.py` — Feedback renderer, Direct conversation reconstruction, RuleDraft compiler, and shared effect validation.
- `agent_world/graph.py` — framework-owned correction eligibility, attempt evidence, and hard-stop logic.
- `tests/test_design_semantics.py` and `tests/test_graph_contracts.py` — current Direct conversation, safety, strict-progress, and hard-stop regression surfaces.
- `node-contracts.md` — current one-packet Direct correction and shared RuleDraft contract.
- `config/.agent-world-runs/runs/run_9916d45626bf4ab3b11535c96fe50aa1/run.json` — safe terminal Observe/run facts.

## Related Specs

- `docs/agent-world-environment-generation.zh.md` — framework owns validation/retry/release; Feedback is a bounded safe correction and not model control authority.
- `docs/direct-rewrite-execution-map.zh.md` — Direct is prompt-only; Candidate/Judge/Registry boundaries remain separate.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — Feedback is the framework-authored next user wish; rejected content stays ephemeral and tests do not replace a real boundary proof.
- `.trellis/spec/guides/foundry-product-alignment.md` — this leaf proof cannot be represented as product completion.
- `.trellis/spec/agent_world/backend/index.md` — Direct no-Skill boundary, actionable safe diagnostics, and bounded correction discipline.

## External References

None. This decision relies on the canonical project contract, persisted safe run evidence, current plan, source, and tests.

## Caveats / Not Found

- No raw proposal was read, reconstructed, or persisted. In particular, there is no evidence that C pre-existed in proposal two.
- The allowed wording can improve a recipient-facing hypothesis; it does not prove Luna will repair every matching occurrence or that all unobserved violations can be found within three proposals.
- This is not capacity evidence. The three calls completed normally, and ToolSemantics already has one frozen tool per shard; no sharding or model/route change is authorized.
- This allow expires if the plan digest, shared Feedback/RuleDraft trust boundary, or relevant real scene changes.

## Next Permitted Gate

The coordinating session may add this exact allow record to both task context manifests and dispatch implementation limited to this digest. After an independent implementation check, only the specified frozen-parent leaf proof is permitted.
