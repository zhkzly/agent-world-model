# Minimal plan — disclose the SharedTool JSON contract

- Lineage: `shared-tool-json-contract`, revision 2/2
- Diagnosis: `diagnosis-e2e-shared-tool-json-boundary.md`
- Real scene: `run_4528cf8a411a4d8a82b6390465c6d138`
- Addresses: `cross-layer-review-7c47c057-shared-tool-json.md`
- Proposed scope: local SharedTool Direct recipient-contract clarification

## Product target and role boundary

The product target remains an arbitrary natural-language need becoming an
evidence-grounded executable environment, independently exercised as an
untrusted candidate and atomically published as an immutable Registry
`EnvironmentPackage`, with safe Observe facts. This repair only advances the
committed Architecture-to-SharedToolSemantics handoff and proves none of later
Design, Candidate, Judge, Registry, Repair, Expand or Consumer/SFT/RL.

The Direct LLM owns only the shared business semantics. Framework code owns the
exact group, grammar, membership, bounds, parsing, validation, compilation,
digest, one correction, Work/Finding, Judge and release. Agent and candidate
process boundaries are unchanged.

## Exact model-visible contract

Keep the current projection and compiler. Replace only the seven-name shape
with a concise exact grammar equivalent to the existing compiler:

```text
output={
  tool_indexes: exact frozen ordered group;
  atomicity|concurrency|idempotency:
    1..group_size arrays, each containing 1..group_size members,
    using only frozen tool indexes and covering every member;
  ordering: 0..8 stripped nonempty text items, each <=160 code points;
  compensation: 0..8 stripped nonempty text items, each <=160 code points;
  error_policy: exactly group_size ordered objects
    {tool_index: exact corresponding frozen member,
     policy: stripped nonempty text <=280 code points}
}
```

Add one objective sentence: return one compact complete JSON object, echo the
group exactly, cover every member in all three shared dimensions, and recheck
the whole object before return and after correction. Do not ask for IDs,
digests, Artifact refs, byte counts, schemas, gates, Judge or release facts.

The shape must not claim stronger partition uniqueness/disjointness than the
unchanged compiler currently validates. Changing that semantic contract is not
required by this observed parse failure and would need a separate diagnosis.

## Parser and response-transport policy stays unchanged

Do not edit `_direct_json`, `DirectChatBackend`, `_json_object`, operation
evidence, or GraphRunner. `direct_response_not_json` remains a terminal
parser-level failure and never consumes local semantic correction. Existing
correction remains available only after a JSON object reaches the node compiler
and receives a safe path/category rejection. Response-empty, malformed provider
envelopes, HTTP/transport failures and retryable primary/fallback behavior also
remain unchanged.

Native `response_format`/strict JSON Schema support is an unresolved competing
hypothesis because no profile-matched capability probe exists for the Luna
endpoint. This revision neither declares it irrelevant nor adds it. If the same
non-JSON terminal recurs after the disclosed shape change, the next Diagnosis
must evaluate a safe request-shape/profile probe before any response-mode
change. That future possibility is not part of this implementation or proof.

## Documentation and compatibility

Align only the `shared_tool_semantics[group]` section of `node-contracts.md` to
the existing compiled fields above. The typed `SharedToolContract`, Artifact
kind, group identity, graph edges, downstream per-tool semantics, Package and
Registry inputs remain unchanged. The changed shape is already included in
semantic revision material, so stale shared work cannot be silently reused.

No common Direct boundary changes. Other Direct nodes, all Agents and the
candidate process receive byte-for-byte unchanged prompts, feedback and
runtime behavior.

## Deterministic verification

Focused tests must prove:

1. the SharedTool recipient sees the exact grammar/objective and frozen group;
2. valid current SharedTool payloads compile unchanged;
3. `direct_response_not_json` remains one terminal call with its original code,
   no output Artifact, failed WorkRecord and blocking Finding;
4. a parsed invalid SharedTool object still receives only the existing one safe
   compiler correction and a second invalid object still gets no third call;
5. the common `_direct_json` helper, six Direct node declarations,
   response-empty/provider-envelope/transport/fallback paths, Agents and
   candidate code are unchanged;
6. the shape change rotates only SharedTool semantic identity; node, edge,
   route, group and correction topology stay fixed;
7. downstream ToolSemantics receives the same compiled SharedToolContract.

Run focused/full pytest, Ruff format/check, mypy, compileall and diff check.
Keep production Python at or below the current 10,296 lines by replacing the
existing shape text; add no abstraction.

## Real proof

After a fresh independent Terra/max critic `allow` and implementation check:

1. invoke only `shared_tool_semantics[1-2-3-4-5-6]` with the exact committed
   Architecture/Evidence Artifacts from the failed E2E;
2. inspect attempts, model, compiled Artifact, WorkRecord and Observe; success
   may use one call or the existing compiler correction after parsed JSON, never
   a third; a non-JSON response remains terminal;
3. only then run one fresh public Direct request to terminal Observe;
4. any different terminal begins a new diagnosis. No blind retry, output edit,
   model fallback, group split or later-child work is authorized here.
