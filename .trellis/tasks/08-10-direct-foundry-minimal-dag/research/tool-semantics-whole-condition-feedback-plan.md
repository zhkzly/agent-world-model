# Repair plan — whole-condition ToolSemantics Feedback

- Date: 2026-08-12
- Revision: 1
- Trigger: `run_9916d45626bf4ab3b11535c96fe50aa1`
- Scope: existing Direct semantic Feedback wording and one effect diagnostic

## Product checkpoint

The target remains natural-language need -> evidence-grounded executable
environment -> independent Judge -> immutable Registry package. This repair
may establish only `design/tool_semantics[reserve_tool]`; it proves no later
Design, Candidate, Judge, release, Expand or Consumer boundary.

## Minimal implementation

1. In `agent_world/design.py`, change the existing semantic next-user Feedback
   so the exact path is explicitly one observed occurrence. Tell the model to
   fix that occurrence and inspect/fix every other occurrence governed by the
   same condition and expected category in the complete previous proposal.
   Continue to request one complete replacement object and whole-contract
   self-check. Keep format Feedback concrete and root-wide.
2. At the existing effect-value rejection, replace only its safe condition text
   with the exact accepted construction: a literal is written directly as a
   finite JSON scalar/scalar-list without a literal wrapper; only a semantic
   reference uses the exact `{kind:"semantic_ref",semantic_index:<frozen>}`
   object. Do not change accepted values, source shape or compiler behavior.
3. Add focused regressions proving the next user instruction treats the path as
   an observed occurrence, requests all same-condition repairs, and carries the
   precise effect construction. Preserve the original conversation, raw
   secrecy, complete replacement, self-check and current attempt ceilings.

## Explicit non-scope

- No fourth proposal, retry/fallback/model/route/profile change.
- No issue aggregation framework, parser relaxation, normalization or compiler
  acceptance change.
- No per-field/per-section ToolSemantics split. The live calls completed; this
  is not a capacity terminal and the node already has one tool per shard.
- No graph, Artifact, Candidate, Judge, Registry, Observe, Repair, Expand or
  Consumer change.

## Verification

Run focused tests, then full pytest, Ruff, mypy, compileall and legacy firewall.
After independent check, rerun only the exact frozen-parent `reserve_tool` Luna
leaf and immediately read Observe. Success is one unchanged ToolSemantics
Artifact. Any new terminal starts a new diagnosis; no blind retry or E2E.
