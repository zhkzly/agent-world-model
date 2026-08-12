# Diagnosis — repeated Direct format failure after Feedback

- Date: 2026-08-12
- Real diagnostic run: `run_5d7bd3a844d4458daa56670f4c0003b9`
- Coordinate: `design/tool_semantics[reserve_tool]`
- Terminal: `direct_response_not_json`, rejected, not published

## Expected behavior

The same exact Direct task uses the official SDK with JSON-object response mode.
A completed first answer that alone fails strict object parsing may receive one
format-only user Feedback turn in the same logical conversation. The replacement
must be one complete JSON object. A second format failure must terminate with no
third call. This leaf is only one prerequisite for the product target:
natural-language need -> executable environment -> independent Judge ->
immutable Registry package.

## Observed chronology

1. Framework cold-read the exact three parent Artifact bytes from failed public
   run `run_bb8b2474bfd34507b1b73f7856c77ee3` and dispatched Luna through the
   official SDK, Direct/no-Skill route.
2. Attempt one completed with `finish_reason=stop`, nonempty content and measured
   usage, but the content did not strictly decode as one JSON object.
3. Framework retained it only in memory as the prior assistant turn and sent
   the approved format Feedback. The second request's input usage increased
   from 5,885 to 7,131 tokens, consistent with that additional context.
4. Attempt two also completed with `stop`, nonempty content and measured usage,
   but again did not strictly decode as one JSON object.
5. Framework correctly stopped after two calls, persisted only safe facts,
   emitted one blocking Finding and published nothing.

## Five lenses

1. **Project Agent view — supported.** Observe and five evidence refs identify
   exact attempts, model, usage, dependency closure and non-release.
2. **Effective Prompt/input — supported for delivery, outcome uncertain.** The
   complete output shape and exact format Feedback were sent; neither call was
   truncated. The evidence does not reveal the safe structural subtype of the
   non-JSON content.
3. **Direct no-Skill — supported.** Both operations are `direct_llm`; no Skill,
   tool, Agent session or workspace existed.
4. **Code/execution — weakened at the provider-format boundary.** The local
   OpenAI-compatible route accepted `response_format=json_object` but returned
   content that the strict SDK-side parser rejected twice. The current facts do
   not distinguish a fenced object, one object plus prose, a JSON non-object, or
   genuinely non-JSON content.
5. **Feedback/observability — sufficient to stop safely, insufficient to select
   a repair.** Raw content correctly remained private/ephemeral, but no closed
   in-memory shape classification survived. Guessing parser relaxation, model
   fallback or more Feedback from the generic code would be unjustified.

## Break-loop analysis

- **Category:** B/E — cross-layer contract plus implicit assumption. The SDK
  request shape was tested, but the earlier fix assumed the local compatible
  provider would reliably enforce inner JSON-object content on the real large
  ToolSemantics request.
- **Why the previous fix was incomplete:** official SDK plus one format Feedback
  fixed transport/protocol ownership and bounded retry, but did not prove the
  route's actual malformed-content subtype. Deterministic doubles cannot expose
  that provider behavior.
- **Not selected:** no third Luna call, no broad parser extraction, no Spark
  fallback, no validator weakening, no prompt rewrite, no Skill, no new node or
  generic response-normalization service.

## Competing hypotheses and next discriminating observation

- H1 (45%): Luna/local 8317 does not reliably honor `json_object` for this large
  request and returns genuinely non-JSON content.
- H2 (40%): the semantic object is present but wrapped in one Markdown fence or
  bounded outer prose, which the intentionally strict Direct parser rejects.
- H3 (15%): the response is valid JSON but not an object, or contains multiple
  JSON values.

The smallest read-only next observation is one exact-input Luna capability
probe through the same SDK request, classifying the ephemeral result only as
`strict_object`, `single_fenced_object`, `single_object_with_outer_text`,
`json_non_object`, `multiple_objects`, or `other`. Persist no raw text and make
no graph commit. If the call returns a strict object, record the behavior as
stochastic and do not infer a parser fix. This diagnostic is not a retry,
successful node, E2E or release proof; any logical repair still requires a new
plan and critic allow.

## 2026-08-12 recipient-facing Feedback clarification

The exact implementation audit found a narrower defect than “the model ignored
Feedback.” The retry correctly reconstructed `original user -> rejected
assistant -> Feedback user`, but the final user turn said only that the answer
was not one JSON object. `_direct_json_object` discarded the safe distinction
between a Markdown fence, outer text/extra data, a non-object JSON root and a
JSON syntax location. Therefore the recipient was told the desired end state,
but not the most specific safely observed change it should make to its own
previous answer.

Feedback is not a failure label. It is the next actionable user instruction to
the same LLM/Agent: name the safely observed rejected condition, say exactly
what to change, request one complete replacement rather than a patch, and ask
for a whole-result self-check while keeping the original objective, frozen
input and output contract unchanged.

The live facts do not establish an input-capacity failure: both Luna calls
ended with `finish_reason=stop`; the first request used 5,885 input tokens and
the output used 1,976 tokens; and ToolSemantics is already physically sharded
to one tool per call. No current topology split is selected. If a future real
terminal proves a context/output-capacity problem, the framework may partition
the work at independent schema-owned semantic coordinates, validate each call,
and deterministically assemble the results. It must not raw-token-chunk an
object or use Feedback to conceal a topology change.

The smallest selected repair is therefore local to the Direct parser-to-
Feedback handoff: preserve one safe closed parse condition in memory/typed
correction evidence, render it as an explicit user action, retain the existing
single format-correction budget, and rerun only the exact ToolSemantics leaf.
