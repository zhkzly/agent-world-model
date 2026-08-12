# Direct R9-C7 — exact correction and Runtime response closure

## Why this revision exists

The independent C6 whole-diff check passed every deterministic gate but blocked
two still-open parts of the already approved C6 contract: correction feedback
was generic or dropped at several model/Agent nodes, and the Builder-visible
Runtime ABI plus Integration validators did not close response envelopes. C7
changes only those two boundaries. It adds no node, graph, repair loop, schema
engine, permission/configuration layer, compatibility path or later-child code.

## 1. One exact local correction, no correction subsystem

- Keep `CorrectionPacket` as one safe issue with exactly `code`, an exact
  model-output JSON path, a short violated condition and a closed expected
  category. Direct R9 reports the first compiler-detected issue; it does not add
  issue aggregation, progress scoring or another feedback Artifact.
- Every `DIRECT_LLM` or `AGENT` node whose `NodeSpec.local_corrections == 1`
  must do both halves of the same contract: its compiler may raise a rejected,
  non-retryable `NodeExecutionError` carrying an exact packet, and its second
  physical invocation must receive the identical frozen projection plus that
  packet. No packet means no second invocation.
- Replace the generic Design root packet with path-bearing compiler errors.
  Paths point to the actual rejected output field/item; whole-object shape
  errors may use `$`. Provider/transport/JSON parse failures remain
  non-correctable.
- Candidate Agent invocation gets one shared optional correction argument.
  `build_plan`, `verifier_intent`, and the advisory
  `CandidateCompletionDraft` pass it through rather than each constructing a
  separate prompt convention. CandidateBuild enables the same one correction
  only for its bounded completion JSON; physical source scan, dependency,
  process, Integration, Judge, Package and Registry failures never retry.
- Attempt/evidence persistence and the two-invocation maximum remain exactly as
  implemented by `GraphRunner`; C7 adds no retry counter or cross-node repair.

## 2. Close the five Runtime response envelopes

`implementation-contract.json` must disclose these exact top-level responses,
with no missing or additional fields:

```text
handshake -> {operations: [handshake, reset, invoke, snapshot, close]}
reset     -> {status: "ok"}
invoke    -> {status: "ok", result: exact frozen tool result keys/types}
snapshot  -> {state: safe JSON object}       # framework/Judge private
close     -> {status: "ok"}
```

- The contract records each response's exact fields, literals and value/type
  constraints. The code-generation Skill only reminds the Agent to implement
  the supplied exact ABI; it does not duplicate the schemas.
- Runtime supervision checks the same closed envelopes before consuming any
  value. `invoke.result` remains closed to the frozen public step; snapshot
  state remains private and is checked only as a safe object. Close is an exact
  acknowledgement.
- This is validation of the existing five operations, not a generic JSON
  Schema runtime or a new protocol version.

## 3. Minimal implementation and tests

Implementation surface is limited to `design.py`, `candidate.py`, `graph.py`,
`runtime.py`, at most one sentence in the existing code-generation Runtime
Skill, and focused tests. `contracts.py` changes only if the existing packet
type itself cannot express an exact path; no new feedback type is allowed.

Add small hostile regressions that prove:

1. Design, BuildPlan, VerifierIntent and CandidateCompletion compiler failures
   expose a precise packet and the second call sees it with unchanged input;
2. malformed provider/framework/candidate-process failures never correct;
3. every Runtime operation rejects an additional top-level field, and the
   frozen contract describes exactly what the supervisor enforces;
4. a conforming five-operation candidate still passes Integration/Judge.

Then run the full deterministic gate and one fresh independent Terra
whole-diff check. Real Direct/Agent/Candidate/E2E proofs remain forbidden until
that check allows them. A real terminal still follows Observe -> diagnosis ->
revised plan -> critic; C7 is not automatic Repair.

