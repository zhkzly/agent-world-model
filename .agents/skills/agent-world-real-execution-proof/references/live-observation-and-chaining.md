# Live Observation and Chaining

For each real Provider, Agent, or LLM node, record dispatch identity and start
time. Around five minutes without a terminal **or meaningful progress**, read
only:

- safe scene and telemetry;
- active operation and invocation-control record;
- owner process/birth identity;
- last Provider event, first progress, and first workspace write; and
- any safe route or network terminal fact.

Process existence alone is not meaningful progress. This is an observation
cadence, not a replacement logical deadline: keep the node's declared
envelope. If evidence shows bounded work is progressing, leave it running and
inspect again within five minutes. If the owner is absent, terminal is closed,
progress is uninterpretable, or durable state is running without ownership,
stop chaining and investigate liveness with agent-world-debugging.

Do not retry or change Prompt/Skill semantics until the stalled boundary has a
concrete owner hypothesis. Do not hard-kill a normal Generate because it is
slow; record any resulting recovery policy through the controller rather than
creating an adapter-local retry loop.

For every proof report, retain:

- exact behavior, input/profile provenance, and expected versus actual result;
- safe scene/evidence path;
- elapsed time and last completed phase; and
- what remains unproven, especially repair, downstream Integration, and E2E.
