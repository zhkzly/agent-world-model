# Plan — minimal official SDK and one Direct format Feedback

- Diagnosis: `diagnosis-direct-sdk-format-feedback-minimal.md`
- Lineage: new Direct-only lineage, revision 1/2
- Scope: current `direct_response_not_json` terminal only

## Product and authority

The goal remains natural-language need -> executable, independently judged,
publishable `EnvironmentPackage`. This change only helps one Direct Design
proposal cross its declared JSON boundary. Framework owns SDK transport,
validation, one correction and release; Direct owns only the proposal.

## Implementation

1. Add and lock `openai==2.54.0`. Replace only Direct's raw `urllib` adapter
   with a context-managed official `OpenAI` client using the configured API
   root, `timeout=300`, `max_retries=0`, Chat Completions and
   `response_format={"type":"json_object"}). Pass no output-token limit.
   Delete the raw Direct endpoint/envelope path.
2. Change Direct configuration examples to `http://localhost:8317/v1` and
   reject a Direct base URL ending in `/chat/completions`; do not add suffix
   compatibility or capability negotiation.
3. Accept only one typed choice with nonempty content and
   `finish_reason=stop`. Keep strict JSON-object parsing. Authentication,
   permission, transport, HTTP, refusal, empty/invalid result, truncation and
   other finishes retain closed safe terminal/fallback classifications; SDK
   performs no hidden retries.
4. For a completed `stop` answer that alone fails strict JSON-object parsing,
   return the existing invocation metadata plus the malformed text to the
   current in-memory node transaction instead of losing the call before
   evidence persistence. Persist only model, measured usage-or-unknown and safe
   code; never persist raw text.
5. On node attempt one only, render one separate user Feedback message:
   “Same task and complete output contract. The previous answer was not one
   valid JSON object. Return one complete replacement as exactly one JSON
   object, with no Markdown, patch or explanation; recheck it before
   answering.” Reconstruct only this Direct conversation as unchanged system,
   unchanged original user task, ephemeral rejected assistant answer, then the
   Feedback user message.
6. The second answer is strictly parsed and compiled as usual. If it is still
   malformed or otherwise rejected, the existing two-attempt ceiling makes it
   terminal. Do not add a third call, another model, another retry policy or
   workflow Repair.
7. Coordinate the one policy sentence in
   `docs/agent-world-environment-generation.zh.md`, the task's
   `node-contracts.md`, and focused tests. The exception is Direct-only,
   first-attempt-only and format-only.

## Tests

- SDK double: API root, client close, `max_retries=0`, 300-second timeout,
  JSON-object mode, no output-token argument and safe error mapping.
- Direct conversation: malformed first content -> exact four messages ->
  complete valid replacement; both calls have safe model/usage evidence and
  raw content appears in no Artifact/Observe file.
- Terminal matrix: second malformed, non-`stop`, empty/refusal and transport
  failures receive no semantic correction and no third call.
- Existing parsed-semantic correction, Agent route/Skill/workspace, Candidate,
  Judge, Registry and release tests remain unchanged.
- Full pytest, Ruff, mypy, compileall and legacy firewall.

## Real proof

After independent implementation review, run one real Luna ToolSemantics node
through the product SDK adapter and read Observe. If it passes, run one fresh
public Direct E2E and read terminal Observe. Stop and diagnose the first new
failure.

## Non-scope

No multi-issue packet, compiler aggregation, Agent feedback change, context
manager, feedback service, validator Agent, prompt platform, memory/RAG layer,
new graph node, Candidate/Judge/Registry change, compatibility path, Expand or
Consumer work.

No plan, test or isolated node proves E2E or release.

