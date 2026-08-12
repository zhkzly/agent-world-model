# Independent cross-layer review — Direct R9-C7

- Date: 2026-08-11
- Reviewer: fresh read-only `trellis-research`, Codex `gpt-5.6-terra`
- Reviewer run: `019fef1f-3a8d-70c3-88e8-85ffefb592ff` (Boyle)
- Decision: `allow`

## Exact planning identity

- Direct nine-file aggregate independently reproduced as
  `254ffcb209e320b5849f789ad91049592a2809ff013e21bc90f53ffcf1947aff`.
- Parent twenty-file aggregate independently reproduced as
  `c0473577fd55a103f014fe36943a99967c4ad165234686e9a65bc64099bf403d`.
- This is the first plan revision after the C6 whole-diff `block`; one further
  revision remains available in this block lineage.
- The trigger is a static pre-proof check. No Observe scene or Diagnosis Record
  is invented.

This allow expires if either digest, the correction/Runtime trust boundary, or
a relevant real-execution scene changes.

## Product and trust-boundary result

The canonical goal remains an arbitrary natural-language need becoming an
evidence-grounded executable environment, independently exercised and judged,
atomically published as an immutable EnvironmentPackage, and safely inspected
through Observe. C7 closes only two facts needed before that result can be
attempted:

1. one rejected model/Agent proposal can receive one exact, safe, causal local
   correction before commit; and
2. CandidateBuild and framework supervision share the same closed five-response
   Runtime ABI.

Framework compilers remain the only correction-packet producer and
`GraphRunner` remains the only eligibility/attempt owner. Model and Agent output
is still a proposal. Framework supervision alone validates untrusted candidate
responses; candidate processes cannot commit, Judge cannot route, Controller
alone packages, and Registry alone cold-reads and publishes.

## Correction compatibility

The one first compiler-detected `CorrectionPacket(code, path,
violated_condition, expected_category)` is sufficient for this R9 local
boundary and is the smallest causal implementation. It preserves the same
frozen projection and typed output while deliberately avoiding issue
aggregation, progress scoring, a feedback Artifact, another retry counter or
cross-node re-entry.

Every correction-enabled Direct LLM/Agent node must provide both halves of the
contract: a safe exact compiler packet and delivery to the second physical
invocation. This includes DesignGraph Agent/Direct helpers plus CandidateGraph
BuildPlan, VerifierIntent and advisory CandidateCompletion. CandidateBuild may
correct only its completion JSON. Source scan, dependency, process,
Integration, Judge, Package and Registry failures remain terminal.

## Runtime and later-consumer compatibility

The five closed response envelopes are sufficient:

```text
handshake -> exact ordered five-operation list
reset     -> exact {status: "ok"}
invoke    -> exact {status: "ok", result: frozen keys/types}
snapshot  -> exact {state: safe JSON object}
close     -> exact {status: "ok"}
```

The private snapshot object is the smallest safe contract for Integration,
Judge and the future framework-owned Consumer. It is not exposed through
PublicTask, candidate inputs, package metadata, telemetry, Observe, SFT or RL.
Package/Registry bind the exact passed protocol evidence; they do not need a
sixth operation or another schema owner.

Repair later consumes route-free Findings, not local packets. Expand supplies a
complete Design to the same CandidateGraph without inheriting a verdict or
feedback loop. Consumer uses the released package privately and does not alter
Runtime or release authority. Therefore C7 does not redesign later children.

## Minimality and required checks

The allowed implementation surface is only `design.py`, `candidate.py`,
`graph.py`, `runtime.py`, at most one sentence in the existing code-generation
Runtime Skill, focused tests, and `contracts.py` only if the current packet
cannot express an exact path. No new module, graph, node, schema engine,
feedback subsystem, permission/configuration layer, repair budget, Campaign,
Consumer or compatibility path is allowed.

Required deterministic evidence:

1. correction-enabled Direct/Agent nodes expose exact packets, keep input
   frozen and dispatch at most once more;
2. BuildPlan, VerifierIntent and CandidateCompletion use the common Candidate
   Agent correction path while non-model failures never correct;
3. all five Runtime operations reject missing or extra top-level fields and
   match the frozen Builder contract;
4. one conforming candidate still passes Integration/Judge;
5. full pytest, Ruff format/check, mypy, compileall, diff check and legacy
   firewall pass, followed by a fresh independent whole-diff check.

## Non-claims and next gate

This allow proves plan identity and cross-layer compatibility only. It does not
prove C7 implementation, provider availability, a real Direct LLM call, Codex
Agent Skill isolation, CandidateBuild, installation, Integration, Judge,
Registry release, automatic Repair, Expand/multi-parent, Consumer/SFT/RL or
OS-level sandboxing.

The next permitted action is bounded C7 implementation, then a fresh
independent whole-diff check. Ordered real proofs remain forbidden until that
check allows them. Any later real terminal follows Observe -> diagnosis ->
revised plan -> critic -> smallest proof -> Observe.

