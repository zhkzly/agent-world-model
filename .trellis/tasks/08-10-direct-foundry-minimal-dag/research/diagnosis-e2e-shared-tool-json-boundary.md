# Diagnosis — SharedToolSemantics lacks a usable JSON contract and correction route

## Expected behavior and role ownership

After a compiled WorldArchitecture commits, each derived multi-tool group is a
prompt-only Direct LLM transaction. The model receives exact frozen tool
semantics plus evidence and proposes shared atomicity, concurrency,
idempotency, ordering, compensation, and error-policy semantics. Framework code
owns the group, JSON grammar, cardinalities, exact membership, compilation,
digest, correction budget, Artifact/Work/Finding, route, Judge and release.

## Real scene and chronology

Fresh public run `run_4528cf8a411a4d8a82b6390465c6d138` passed real
Research Plan (Agent), acquisition (framework), synthesis (Agent), and
WorldArchitecture (Direct LLM, one attempt). Architecture committed six tools
and the current framework-derived group `(1,2,3,4,5,6)`.

The first `shared_tool_semantics[1-2-3-4-5-6]` Luna call returned content that
`DirectChatBackend` could not parse as one JSON object. It produced
`direct_response_not_json`, no `InvocationResult`/usage evidence, no safe local
correction, one failed WorkRecord and one blocking Finding. Observe reports the
run `rejected` and Registry `not_published`.

The recipient had no Skill, tools, workspace, Hook or profile instruction. It
used `gpt-5.6-luna`, the Direct chat-completions route, `max_tokens=4096`, a
120-second physical timeout, the six compiled tool projections and six-entry
citation catalog. Raw provider text is intentionally not persisted, so its
exact length/content is unknown.

## Causal attribution

The model-visible `output_shape` is only:

```text
{tool_indexes,atomicity,concurrency,idempotency,ordering,compensation,error_policy}
```

It omits every value type, bound, exact group echo, partition form, ordering and
compensation text bounds, per-tool error-policy object, objective and whole-
object self-check that the compiler actually enforces. The task's human-facing
node contract describes a different older `domains` draft, so it cannot safely
guide implementation either. This is a proven incomplete recipient contract,
not evidence that Luna, the API, Research Skill, or the committed Architecture
is defective.

There is also a feedback ownership defect. `_json_object` has already
distinguished valid provider transport from model content that is not JSON, but
`_direct_json` converts that proposal-format defect into an uncorrectable
`DesignError`. The existing GraphRunner one-correction transaction therefore
never gets the safe `$`/object correction it already owns.

No evidence establishes token truncation, an unsuitable model, a bad six-tool
group, a parser bug, or a transient transport failure. Those remain rejected
repair hypotheses for this scene.

## Minimal repair boundary

Expose the exact current SharedToolContract source grammar and concise
whole-object objective beside its compiler. Route only
`direct_response_not_json` from a Direct semantic node into that node's existing
single safe correction; keep response-empty/API-envelope/transport failures
unchanged. Align only the stale SharedTool node-contract prose and add focused
regressions.

Do not accept or scrape arbitrary prose, persist raw output, add response modes,
change max tokens/timeouts/models/routes, split the group, alter the compiler or
typed contract, add a node/helper/retry counter, or touch later children. This
Diagnosis authorizes no edit or provider retry.
