# Repair Plan: complete the composition view with reset_state

Lineage: diagnosis-9-composition-view-reset-state.md. Continues the
direct-completion lineage after fe33df95 / 0ff3ae1d / 58a29e92 / 3fd31254 /
c0fe624d allows (all spent).

## Scope classification

Local. Producer: _run_recipe composition view (runtime.py); consumer: the
reference evaluation used by integration/judge. No design, schema, artifact,
package, or Registry change.

## Changes

1. agent_world/runtime.py _run_recipe composition block: add
   "reset_state": {index: task_trace["reset_state"][index]} to the
   evaluation view so reset_state-binding references resolve identically in
   the reference evaluation and the runtime.
2. Deterministic test: a tool whose transition references a reset_state
   binding (name collapsing to reset_state) composes correctly in
   _run_recipe — extend the rendered-runtime test in test_direct_release.py
   with a reset_state-referencing rule driven through integrate().

## Compatibility

- Trace shape unchanged; judge task evaluation unchanged.

## Checks and proofs

- pytest full suite green.
- Offline bench: integrate() against the frozen regenerated design must
  pass (expected post_state status not_ready).
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  and observe the terminal.

## Non-claims

- We do not claim judge/package/registry pass; further terminals are new
  observations.
