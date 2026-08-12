# Diagnosis — Direct SDK, context and Feedback boundary

- Date: 2026-08-12
- Failed run: `run_dc28dcded7fe49ce9a2d9a017511831d`
- Failed coordinate: `design/tool_semantics[route_tool_to_maintenance]`
- Safe terminal: `direct_response_not_json`, rejected, not published
- Supersedes the repair scope of the one-field response-format plan; the prior
  chronology and static evidence remain historical facts.

## Product expectation

An arbitrary natural-language need must become an evidence-backed Design, an
executable Candidate, an independently judged result and an immutable Registry
package before publication. Direct semantic nodes are Prompt-only LLM calls:
they have no Skill, tools, workspace or release authority. Framework code owns
the official SDK adapter, output contract, deterministic validation, bounded
correction, routing, evidence, Judge and release.

When an uncommitted LLM result is safely correctable, Feedback means the next,
more specific user wish in the same logical task: keep the objective, frozen
input and complete output contract unchanged; state every safely known issue;
request one complete replacement rather than a patch or explanation; recheck
the whole replacement. The model proposes again; code alone accepts or stops.

## Observed chronology

1. Public Observe shows ResearchPlan, ResearchAcquire, ResearchSynthesis,
   WorldArchitecture, SharedTool and seven ToolSemantics shards passed. The
   final ToolSemantics shard failed after one Direct invocation with
   `direct_response_not_json`. Candidate, Judge and Registry never ran.
2. `DirectChatBackend` still hand-writes `urllib` requests to
   `/chat/completions`, sends `max_tokens=4096`, ignores `finish_reason`, and
   manually decodes the OpenAI-compatible envelope. This is not the required
   official SDK adapter and adds an application output cap that is absent from
   the product contract.
3. An exact-input diagnostic probe with official `openai==2.54.0`, an API-root
   base URL, `max_retries=0`, JSON-object mode, a physical 300-second timeout
   and no output-token argument produced complete `stop` responses from Luna
   and Spark. A different Luna call still produced malformed inner content.
   Therefore the route and model are usable, while JSON mode alone is not a
   proof of the business object contract.
4. Current semantic correction is passed as a nullable JSON field or an
   `Authorized correction packet` inside a fresh request. It does not present
   the failure as a clear next user instruction, does not ask for a complete
   replacement, and does not preserve the immediately rejected Direct answer
   as the prior low-authority assistant turn.
5. `direct_response_not_json` raises before `InvocationResult` exists. The
   first completed call's safe route/model/usage evidence is therefore lost,
   and `GraphRunner` cannot authorize the existing bounded correction.
6. Current correction-capable compilers generally fail on the first issue.
   Safe history contains A-to-B cases where Luna fixed the disclosed issue but
   an independent issue consumed the only turn. This is a framework feedback
   completeness defect, not evidence of poor instruction following.

## Attribution

1. **Model route:** supported. Both configured models completed official-SDK
   probes; malformed inner JSON remains a stochastic output possibility.
2. **Context/Prompt:** weakened. The initial output contract exists, but the
   current correction is serialized control data rather than a recipient-facing
   user wish, and a Direct correction does not reconstruct the preceding turn.
3. **Skill:** not causal. Direct correctly has no Skill. Editing an Agent Skill
   cannot repair this Direct boundary.
4. **Framework/SDK:** causal. Raw HTTP, the fixed output cap, incomplete finish
   classification and pre-evidence parse failure occur before business
   compilation.
5. **Validation/Feedback:** causal for semantic A-to-B cases. One fail-fast
   issue does not expose the bounded safely discoverable same-object frontier.
6. **Observe/release:** supported. The run failed closed and was not published;
   Observe identifies the reached coordinate without exposing raw output.

## Causal hypothesis

The current terminal is best explained by the Direct adapter and feedback
handoff, not by Luna instruction following, Candidate code, Judge, Registry or
an Agent Skill. JSON mode improved the request but did not make inner content
schema-safe. Because the wrapper parses before producing evidence and classifies
the result as non-correctable, a completed, attributable model-format failure
cannot become the user's one bounded correction wish.

For parsed semantic failures, the independent audit establishes a related but
separate defect: incomplete validator feedback can make perfect compliance with
issue A end at undisclosed issue B. The smallest common fix is a bounded tuple
of safe issues at the existing compiler frontier, not more attempts or another
critic/model node.

## Rejected alternatives

- Do not loosen or heuristically extract JSON.
- Do not hide retry inside the SDK or retry malformed output through the
  provider fallback.
- Do not convert Direct to an Agent or add a Skill.
- Do not add a context manager, feedback service, validator Agent, prompt
  registry, memory/RAG layer, new graph node or unbounded loop.
- Do not increase Prompt bulk, reinstate an output-token cap, or weaken
  compiler/Judge/release gates.
- Do not persist raw provider content, prompts, transcripts or secrets.

## Smallest falsifiable repair and proof

Replace raw Direct HTTP with one official SDK adapter. Preserve every physical
attempt's safe model/usage-or-unknown/code evidence. For only a complete,
non-refusal, `stop` result with nonempty content that fails strict JSON-object
parsing, retain that content ephemerally and permit the existing one correction
turn. The second request reconstructs system + original user + rejected
assistant + new user Feedback, then strictly validates the complete replacement.
All other response, transport, credential and second-attempt failures remain
terminal under their closed classifications.

At the same existing validation boundary, a correction packet carries a small
bounded tuple of safely discoverable issues; no new validation service or call
is introduced. Prove the transport and two-turn contract deterministically,
then prove one real Direct node and read Observe. Only after that may a fresh
public E2E run proceed. A repaired Direct node is still not Candidate, Judge,
Registry, Expand, SFT/RL or product completion.
