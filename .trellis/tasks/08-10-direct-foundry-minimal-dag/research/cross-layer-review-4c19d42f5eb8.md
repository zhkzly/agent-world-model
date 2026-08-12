# Research: cross-layer review — Direct outer-content Feedback action

- Query: Review plan revision 1 for the failed Direct
  `tool_semantics[manage_equipment]` format-correction boundary.
- Scope: internal
- Date: 2026-08-12

## Decision

Decision: `allow`

- Plan digest: `4c19d42f5eb87e0ca872f1a3e7084557cd12df2b6102fd07b9bfe7d345099dba`
- Plan revision: 1 (review count: 1)
- Scope classification: local — one existing shared Direct Feedback renderer at
  an in-memory same-conversation boundary; no Artifact, graph, route, or
  downstream ABI change.
- Trigger: public Direct run `run_804e6cc894674e69b7ea72d0714c8daa`
  stopped with `direct_response_not_json` at
  `tool_semantics[manage_equipment]` after the existing Feedback repeated one
  safe outer-content condition.

## Product target and impact chain

The product target remains an arbitrary natural-language EnvironmentRequest
compiled into an evidence-grounded executable environment, independently
verified in a real isolated boundary, published as an immutable Registry
`EnvironmentPackage`, and exposed only through safe Observe facts.

The permitted local chain is:

`strict parser -> safe CorrectionPacket -> _direct_feedback -> ephemeral
assistant + next-user Feedback -> same strict parser -> unchanged two-call
GraphRunner terminal policy`.

The plan translates the already-safe condition into a concrete
replacement/deletion operation without changing what the compiler accepts.

## Owner, compatibility and secrecy

- Invocation keeps ownership of strict whole-response parsing, official SDK
  `json_object` mode, safe subtype classification and ephemeral rejected
  content.
- `_direct_feedback` remains the framework-owned producer of the next-user
  instruction.
- GraphRunner retains the two-call format ceiling; a second format failure
  cannot authorize a third call.
- No compiled Artifact, graph edge, Candidate, Judge, Registry, Observe, route,
  model, configuration or public ABI changes.
- Feedback contains only safe code/path/condition/category and the replacement
  operation; rejected content, Provider body, endpoint and credentials remain
  absent from Feedback and durable files.

## Smallest allowed implementation and proof

1. Change only the `direct_response_not_json` repair sentence to require one
   complete parseable JSON object, deleting prose, labels, Markdown fences and
   second JSON values, with `{` and `}` as first/last non-whitespace characters.
2. Update the existing exact conversation/secrecy assertion; keep the unchanged
   two-call terminal test.
3. Add one concise debugging-guide sentence that a safe subtype still needs a
   recipient-executable replacement/deletion operation.
4. Run deterministic checks, then only the frozen `manage_equipment` leaf and
   immediate Observe.

Parser relaxation, fence/prose extraction, JSON-schema infrastructure, extra
retry/fallback, Prompt/projection rewrite, node split, SDK mode, graph, ABI or
release changes are disallowed.

## Non-claims and next gate

This is not E2E, Judge, Registry, release, Repair, Expand or Consumer evidence.
It permits only the exact implementation, deterministic checks and frozen-leaf
proof. A repeated live terminal requires a new Observe-led diagnosis.
