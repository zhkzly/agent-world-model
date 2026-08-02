# Liveness Control Ladder

Keep the node's declared logical envelope. First-event and first-write are
observations, not arbitrary short death clocks.

## Layer 1 — Direct raw Provider control

Use only for a Direct LLM node. Issue one tiny harmless real request through
the same configured model and Provider route, without adding diagnostic input,
output-token, or short timeout ceilings. Retain only safe terminal class,
elapsed time, completion state, and output length/predicate.

If this fails, investigate credentials, routing, network, or Provider
availability before adapter, Prompt, Skill, or business code.

## Layer 2 — same-family InvocationBackend control

- Direct node: use `DirectLlmBackend` with a minimal prompt-only profile.
- Codex Agent node: use the real Codex SDK/app-server, actual model/route,
  mounted Skill, and a small task that uses the granted tool when relevant.

This layer proves worker spawn, profile materialization, SDK/app-server start,
transport, native response handling, and tool dispatch independently of the
business node.

If raw Direct Provider passes but this layer fails, investigate worker
lifecycle, SDK, adapter, profile materialization, or transport. Do not retry the
business node.

## Layer 3 — frozen node

Only after the applicable control passes, execute the exact frozen node once.
This is the first evidence that can select its Prompt/input, Agent Skill,
business profile, parser, feedback, or semantic boundary.

## Active observation

For every real call, record dispatch identity and start time. At roughly five
minutes without a terminal **or meaningful progress**, perform a read-only
check:

- safe scene and telemetry;
- active operation and Invocation Control record;
- owner process/birth identity;
- last Provider event, first progress, and first workspace write;
- safe route/network terminal fact.

Process existence alone is not progress. If evidence shows continuing bounded
work, leave it running and inspect again within five minutes. If owner is
absent, terminal is closed, progress is uninterpretable, or durable state stays
running without ownership, stop chaining and investigate reconciliation. Do
not wait one or two hours without new evidence and do not hard-kill a normal
generate run.

Retry is a consequence of typed terminal evidence, not a substitute for
diagnosis. Keep same-route retry count and fallback authority visible in the
node definition or central configuration, preserve every failed attempt, use a
fresh physical session, and increase backoff by retry ordinal. A newly observed
Provider bad case may justify evolving that bounded policy; it does not justify
an adapter-local loop, retrying an untyped failure, or consuming semantic
repair turns.

## SDK startup is not model behavior

`sdk_session_open` with zero Provider events means the model has not seen the
Prompt or Skill. Keep those lenses unknown. Inspect app-server launch, SDK
arguments, generated config, profile materialization, adapter, and safe
diagnostics first.

If the normal phase cannot identify the startup cause, use an opt-in bounded
redacted local sidecar. Never put its raw stderr, Provider message, endpoint,
credential, or private path into normal scene, Artifact, Scheduler feedback, or
runtime correction.
