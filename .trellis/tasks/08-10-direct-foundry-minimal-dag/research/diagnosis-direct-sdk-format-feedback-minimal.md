# Diagnosis — minimal Direct format Feedback

- Date: 2026-08-12
- Real terminal: `run_dc28dcded7fe49ce9a2d9a017511831d`
- Coordinate: `design/tool_semantics[route_tool_to_maintenance]`
- Safe result: `direct_response_not_json`, rejected, not published
- New lineage reason: the mixed SDK/Feedback plan exhausted two revisions and
  was blocked for overdesign. This lineage addresses only the observed Direct
  format failure and the user's explicit Feedback policy.

## Expected

Direct is a Prompt-only LLM node. A completed model answer that fails the
declared JSON-object format may receive one actionable next-user-turn
Feedback: same task and output contract, return one complete JSON object, no
patch or explanation. The framework owns the one-correction ceiling and
strictly validates the replacement. A second failure terminates.

## Observed

The current adapter hand-writes `urllib`, sets `max_tokens=4096`, parses
before returning operation evidence, and turns malformed inner content into a
non-correctable exception. The real run therefore stopped after one call.
Official-SDK probes showed both configured local routes can complete the same
request with JSON-object mode and reported usage, while one Luna response was
still malformed. This makes the failure attributable and stochastic rather
than a credential, network, Skill, Candidate or Judge failure.

## Minimal policy decision

The existing source text treats every generic root error as a framework defect.
That conflicts with the user's repeated explicit requirement that observable
LLM/Agent format failures can be fed back as a user-like correction. Narrowly
revise the rule for Direct only:

- eligible: completed, nonempty, `finish_reason=stop` model content whose only
  root failure is strict JSON-object parsing, on the first node attempt;
- correction: one format-specific user message in the same in-memory logical
  conversation;
- terminal: refusal, truncation, empty/invalid envelope, transport/auth,
  unknown finish, second malformed answer, or any exhausted node budget.

The rejected text exists only in memory until the attempt ends. It is never
persisted or exposed through Observe. The replacement still goes through the
unchanged compiler, Judge and release gates.

## Explicitly separate findings

The parsed-semantic A-to-B feedback audit is valid but not needed to cross this
terminal. Do not change Agent feedback, `CorrectionPacket`, compiler
aggregation, Candidate, Judge, Registry, graph topology or public Observe.
Address a later parsed-semantic failure only if a new real terminal reaches it.

## Smallest proof

Deterministically prove one malformed first answer produces exactly one
format-Feedback turn and that both physical calls retain safe model/usage
evidence without raw output persistence. Then prove one real Direct
ToolSemantics node and read Observe. Only a passing node permits a fresh E2E.

