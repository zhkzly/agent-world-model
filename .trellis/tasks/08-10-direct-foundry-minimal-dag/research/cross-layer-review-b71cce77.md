# Research: cross-layer review — Direct JSON-object wire contract revision 2

- Query: Independently re-review final revision 2/2 of
  `direct-non-json-local-correction-plan.md` after the block recorded in
  `cross-layer-review-f1cbad92.md`.
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan digest: `sha256:b71cce7776e1ab2d061391dcd86b829e6a4cb008a8cd73ccfabce70dfde1e94c`
- Digest verification: the supplied digest exactly matches the current bytes of
  `research/direct-non-json-local-correction-plan.md`.
- Plan revision: `2/2`, final revision in this Diagnosis/plan lineage.
- Scope classification: local common-Direct transport repair. The physical
  request shape changes for the six Direct semantic nodes, but their semantic
  input/output contracts, validation, committed Artifacts, and consumers do not.
- Trigger: public run `run_dc28dcded7fe49ce9a2d9a017511831d`
  stopped at `design/tool_semantics[route_tool_to_maintenance]` after seven
  sibling ToolSemantics commits with terminal `direct_response_not_json`, one
  call, no output, one blocking Finding, and no release.
- Affected trust boundary: fixed Direct route configuration ->
  `DirectChatBackend._call` request body -> provider JSON-object response ->
  strict `_json_object` parsing -> unchanged typed compiler/Artifact commit.

## Product Alignment

The product target remains: turn an arbitrary natural-language
`EnvironmentRequest` into an evidence-grounded executable environment,
independently verify it in a real isolated boundary, publish an immutable
Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This plan advances only the Direct response-transport boundary before a Design
proposal can be parsed and compiled. The adapter field, its unit test, or one
successful Direct node is not Design, Candidate, Judge, Registry, Repair,
Expand, Consumer, SFT, or RL completion. Only the proposed fresh public E2E can
establish this Direct product path, and only for that run.

## Block Closure

The revision closes both reasons for the prior block:

1. It abandons root-object semantic correction. `direct_response_not_json`
   remains a non-retryable, non-correctable terminal; the binding rule that
   provider/transport/JSON parsing failures never consume local semantic
   correction remains intact (`node-contracts.md:125-148`). The source-of-truth
   distinction between generic root mechanics and exact compiler feedback is
   therefore preserved (`docs/agent-world-environment-generation.zh.md:421-445`).
2. It adds no second physical turn. The prior successful-two-turn provenance
   hole cannot occur: a successful first call still returns one
   `InvocationResult`, and the existing operation evidence records its resolved
   route model and reported usage. A malformed result still fails before output
   and is not converted into a hidden successful transaction.

The superseding Diagnosis correctly relocates the defect from feedback policy
to the earlier mechanical recipient contract: the backend currently asks for an
object in prose but sends only model/messages/temperature/max-tokens even though
its consumer strictly requires a JSON object (`agent_world/invocation.py:105-162`).

## Evidence and Route Compatibility

The bounded probe used the exact failed ToolSemantics system prompt, frozen
input bindings, committed SharedTool contract, citation catalog, and output
shape. Its only request change was
`response_format={"type":"json_object"}`. Both checked-in configured routes at
the actual localhost-8317 product endpoint accepted that request and returned
an object with the exact four ToolSemantics roots plus reported usage:

- primary `gpt-5.6-luna`;
- fallback `gpt-5.3-codex-spark`.

The checked-in configuration and focused configuration test identify those
same routes (`config/agent-world.example.toml:4-12`;
`tests/test_agent_route_config.py:92-105`). This is sufficient compatibility
evidence for one fixed request contract shared by the current supported Direct
profile. Capability negotiation, route-specific branching, fallback
compatibility code, or a profile framework would add no evidence or authority.
Changing either configured route or endpoint invalidates this allow and requires
a fresh profile-matched probe.

The probe establishes acceptance and parse-level compatibility, not semantic
compiler or release success. Raw provider content was intentionally neither
printed nor persisted; the critic relies on the supplied safe probe record and
did not make another provider call.

## Impact Chain and Consumer Compatibility

```text
checked-in primary/fallback ChatRoute
  -> DirectChatBackend._call fixed JSON-object request field
  -> existing retryable-only primary/fallback selection
  -> existing provider-envelope checks
  -> strict _json_object
  -> DesignExecutor._direct_json (all InvocationError values non-correctable)
  -> DesignExecutor._direct_commit
  -> unchanged node-specific compiler
  -> committed typed Design Artifact + Work/operation evidence
  -> existing Design/Candidate/Judge/Package/Registry consumers
```

`_direct_commit` is the common boundary for `world_architecture`,
`shared_tool_semantics`, `tool_semantics`, `world_rules`, `curriculum_plan`, and
`task_requirement` (`agent_world/graph.py:151-211`; `agent_world/design.py:599-642`).
The one body field therefore coherently reaches every Direct semantic node.
There is no node-specific prompt, schema, edge, or output ABI fork.

Consumer compatibility is fail-closed: only an object that passes the unchanged
strict parser and the node's unchanged compiler can commit and cross an edge.
Malformed/non-object content still yields `direct_response_not_json`; invalid or
empty provider envelopes keep `direct_response_invalid`/
`direct_response_empty`; HTTP/transport behavior and retryable-only fallback
remain unchanged (`agent_world/invocation.py:97-162`). Parsed compiler failures
retain the existing one-correction/two-call ceiling; this transport change does
not spend, widen, or bypass that budget (`agent_world/graph.py:487-555,671-680`).

Later Candidate, Judge, Package, Registry, Repair, Expand, and Consumer seams
consume only already-compiled Artifacts. They neither observe nor need to
understand the request field. Future reuse of the same DesignGraph therefore has
no hidden representation incompatibility.

## Role Audit

- **Framework / hardcoded code:** owns the fixed `response_format` request
  mechanic, credentials and route selection, strict parse, error taxonomy,
  retryable-only fallback, compiler, correction authorization, Work/Finding,
  graph edges, Judge, and release. The field is not model-selectable and adds no
  runtime policy surface.
- **Direct LLM:** still owns only bounded business semantics in one complete JSON
  object. It receives the same rendered system/user input and no Skill, tool,
  workspace, route, budget, Gate, Judge, Registry, or release authority.
- **Codex Agent:** uses the separate `CodexAgentBackend`; Agent malformed JSON
  remains independently terminal and is outside this Diagnosis. No evidence
  justifies changing it, and the Direct body field cannot reach it.
- **Candidate process:** remains untrusted and does not run until compiled Design
  Artifacts reach CandidateGraph. It neither produces nor consumes this request
  mechanic.
- **Judge/Registry:** retain independent evidence and release authority; neither
  is bypassed or changed.

## Semantic Revision and Provenance

The plan's wording is honest when read as a semantic-versus-physical
distinction. The physical HTTP request gains one framework-owned transport
field. The rendered Prompt/input, disclosed output shape, parser acceptance,
typed compiler, NodeSpec, route identity, and Artifact ABI remain unchanged.
The task design explicitly treats transport-only fixes as non-invalidating for
semantic Artifacts (`design.md:218-221`), so no semantic-revision rotation is
required.

For each successful fresh call, existing `InvocationResult` and
`OperationEvidence` continue to persist the actual route model and reported
usage (`agent_world/invocation.py:146-162`;
`agent_world/design.py:589-597`; `agent_world/graph.py:487-492,683-697`). Fresh
model output and resulting Artifact digests may naturally differ. This allow
does not claim that the request field becomes a new durable semantic-revision or
operation-evidence field, nor does it repair the pre-existing lack of
model/usage evidence when parsing itself terminates before an
`InvocationResult` is returned.

The backend guidance's broader phrase “native strict JSON Schema” is not a claim
of this plan. The approved change is only native JSON-object response mode for
the observed root-format defect; the unchanged strict parser and node compiler
remain authoritative for exact shape and semantics. A per-node JSON Schema
generator or SDK migration would change a broader contract, lacks causal need
here, and requires a separate plan and proof.

## Smallest Allowed Implementation and Proof

1. In the existing request-body literal in `DirectChatBackend._call`, add exactly
   `"response_format": {"type": "json_object"}`. Do not edit another
   production boundary.
2. Extend the focused Direct adapter test to decode the outgoing request and
   assert that field together with the unchanged model, messages, temperature,
   and token setting. Preserve the existing non-JSON terminal regression and
   full suite.
3. Run the plan's focused/full pytest, Ruff format/check, mypy, compileall,
   firewall/release checks, intended-diff check, production-line ceiling, and an
   independent implementation check. These are deterministic implementation
   evidence, not provider or product proof.
4. Run one actual product `DirectChatBackend` ToolSemantics call with the exact
   failed input. Record only safe parsed four-root, resolved-model, usage, and
   terminal facts; persist no raw content. Read Observe immediately.
5. Only if that narrow proof passes, run one fresh public Direct E2E through
   terminal Observe. Any new terminal begins a fresh Diagnosis; do not retry or
   broaden this implementation under the present allow.

This is smaller and more causal than a parser heuristic, semantic retry,
fallback-on-malformed, capability negotiation, per-route compatibility branch,
SDK migration, JSON Schema generator, helper/module, retry subsystem, Prompt
change, or graph change.

## Non-Claims

- This allow does not claim universal model reliability, that future arbitrary
  OpenAI-compatible routes support the field, or that JSON-object mode enforces
  the node's full semantic schema at the provider.
- It does not authorize `json_schema`, a schema generator, parser relaxation or
  scraping, response coercion, malformed fallback, timeout/token/model/route
  changes, retries, helpers/modules, prompts, output shapes, NodeSpecs, graph
  edges, Skills, Agent behavior, candidate code, Judge, Registry, Repair,
  Expand, or Consumer changes.
- It does not claim the pre-implementation route probes passed the ToolSemantics
  compiler or completed Design; they prove only request compatibility, object
  parsing, expected top-level roots, and reported usage.
- It does not prove Candidate execution, Integration, Judge, Package, Registry
  release, Repair, Expand, Consumer, SFT, or RL. The public E2E remains required.
- This allow expires if the plan bytes/digest, affected transport boundary,
  configured Direct routes, or latest relevant real scene changes.

## Next Permitted Gate

The main planner may add this exact matching allow record to the implementation
and check contexts. The next permitted action is only the one-field adapter
implementation and focused request test above, followed by independent checking
and the stated true-boundary proofs.

## Files Found

- `research/cross-layer-review-f1cbad92.md` — prior block and required revision
  feedback.
- `research/direct-json-response-format-probe.md` — safe exact-input route
  compatibility evidence.
- `research/diagnosis-direct-json-response-contract-missing.md` — superseding
  causal diagnosis.
- `research/direct-non-json-local-correction-plan.md` — reviewed final revision;
  digest verified.
- `agent_world/invocation.py` — fixed Direct request body, strict parser, error
  taxonomy, usage normalization, and retryable fallback.
- `agent_world/design.py` — separate Agent/Direct helpers and common Direct
  commit/operation-evidence boundary.
- `agent_world/graph.py` — six Direct NodeSpecs, semantic revision, and bounded
  correction transaction.
- `tests/test_agent_route_config.py`, `tests/test_design_semantics.py`, and
  `tests/test_graph_contracts.py` — request/usage seam, terminal non-JSON, and
  correction bounds.

## Related Specs

- `docs/agent-world-environment-generation.zh.md:258-271,421-445,596-605` —
  framework/LLM authority, root mechanical errors, bounded exact correction, and
  Direct semantic transactions.
- `docs/direct-rewrite-execution-map.zh.md:16-24,53-60,62-88,114-154` — role
  separation, common node transaction, fixed Direct route, and no Direct Skill.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:125-148` —
  common terminal JSON-parsing rule.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md:143-221,284-317` —
  execution kinds, semantic/transport revision distinction, feedback classes,
  and six Direct node contracts.
- `.trellis/spec/agent_world/backend/index.md:593-705,1813-1868` — Direct
  response-transport ownership and broader native-structured-output guidance.

## External References

None. This review uses only the target worktree's source, contracts, code,
tests, prior block, Diagnosis, and safe probe record.

## Caveats / Not Found

- Raw provider responses and credentials are intentionally absent. The safe
  probe record was not independently reconstructed from raw wire data.
- No provider call, test run, production/test/plan/spec/config edit, task-manifest
  edit, or git operation was performed by this critic. The only write is this
  required bounded research decision record.
