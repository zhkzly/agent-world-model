# Plan — minimal semantic Feedback and ToolSemantics strict progress

- Diagnosis: `diagnosis-tool-semantics-feedback-progress.md`
- Lineage: revision 1/2
- Scope: current Direct `tool_semantics[reserve_tool]` A -> B terminal

## Product and authority

The goal remains natural-language need -> executable, independently judged,
publishable `EnvironmentPackage`. This repair only lets one uncommitted Direct
ToolSemantics proposal use actionable bounded Feedback. Framework still owns
validation, attempt admission, issue comparison, commit and release; Direct
owns only complete replacement proposals.

## Minimal implementation

1. Reuse the existing Direct `previous_assistant + feedback` adapter path for
   parsed semantic corrections. Keep the original system/user task byte-for-byte
   unchanged. Retain only the immediately previous parsed proposal as ephemeral
   canonical JSON, then append one user Feedback message containing the existing
   safe `code/path/violated_condition/expected_category`, a complete-replacement
   request and one whole-result self-check. Persist neither proposal text nor the
   rendered Feedback.
2. Let `NodeSpec.local_corrections` declare `0`, `1` or `2`; set only
   `tool_semantics` to `2`. All other existing nodes retain their current value.
3. Let the existing GraphRunner execute at most `1 + local_corrections`
   proposals. The second correction is eligible only when:
   - the same ToolSemantics coordinate remains uncommitted;
   - attempts 1 and 2 both have safe parsed semantic CorrectionPackets;
   - the exact packet identity `(code,path,condition,expected)` changed;
   - neither packet is `direct_response_not_json`.
   The third proposal is final. Same issue, format, transport, retryable or
   non-model failure terminates without another call.
4. Keep compiler acceptance, CorrectionPacket, graph topology, semantic
   revision, Artifact/WorkRecord/Observe schemas and downstream inputs exactly
   unchanged. Recovery policy is not model-authored semantic identity.

## Deterministic checks

- Direct semantic correction reconstructs exactly four messages: unchanged
  system, unchanged original user, ephemeral prior assistant JSON, concise user
  Feedback. The old JSON `correction` field is no longer the semantic handoff.
- ToolSemantics A -> B -> valid commits with three operation/attempt records.
- A -> A stops after two calls; A -> B -> invalid stops after three; a format
  correction never receives a third call.
- Other Direct nodes retain one correction; framework/candidate/transport
  terminals retain none; no rejected proposal or Feedback text appears in the
  Artifact store or Observe.
- Run focused tests, full pytest, Ruff, mypy, compileall and legacy firewall.

## Real proof

After an independent implementation check, replay only the exact frozen
`reserve_tool` parent closure through Luna and read Observe. If it commits, run
one fresh public Direct E2E and stop at its first terminal. A new failure starts
a new diagnosis; it does not broaden this plan.

## Explicit non-scope

No issue aggregation, generic Feedback abstraction, prompt framework, context
manager, memory/RAG layer, Agent feedback/session change, model fallback,
validator relaxation, new node/graph, cross-node Repair, Candidate, Judge,
Registry, Expand or Consumer change. No token/output limit is added.

No plan, test or isolated leaf proves E2E or release.
