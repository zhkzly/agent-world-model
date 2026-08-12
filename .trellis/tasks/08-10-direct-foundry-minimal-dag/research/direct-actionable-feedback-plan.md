# Repair plan — actionable Direct Feedback

- Date: 2026-08-12
- Revision: 1
- Trigger: `run_5d7bd3a844d4458daa56670f4c0003b9`
- Coordinate: `design/tool_semantics[reserve_tool]`
- Scope: Direct response parsing -> one existing local Feedback turn

## Product checkpoint

The product target remains natural-language need -> evidence-grounded
executable environment -> independent Judge -> immutable Registry package.
This repair may establish only one Direct ToolSemantics leaf. It does not prove
the remaining Design graph, Candidate, Integration, Judge, Package, Registry,
Repair, Expand or Consumer/SFT/RL.

## Minimal implementation

1. In `agent_world/invocation.py`, keep the rejected answer ephemeral and add
   only one safe closed parse condition to `_DirectFormatFailure`:
   Markdown fence, non-JSON leading/trailing content, non-object JSON root, or
   invalid JSON syntax with line/column. Do not persist or echo raw content,
   provider exceptions, credentials or model-private text.
2. In `agent_world/design.py`, compile that condition into the existing
   `CorrectionPacket`. Render both format and semantic corrections as a natural
   next-user instruction: identify the exact path/condition/category, state the
   concrete requested change, request the entire corrected JSON object rather
   than a patch/explanation, and require a whole-object self-check. Keep the
   original system message, frozen user payload, output shape, previous
   ephemeral assistant answer, route and compiler unchanged.
3. Keep exactly the current retry policy: one format Feedback call; no third
   format call, fallback, parser extraction, validator weakening, new node,
   generic response service or runtime Skill.
4. Add focused tests for the safe parse conditions and the exact four-message
   conversation. Prove that Feedback contains an actionable condition and
   complete-replacement instruction, while raw output is present only in the
   ephemeral assistant turn.
5. Persist the reusable development rule concisely in
   `.trellis/spec/guides/agent-llm-node-debugging.md`: Feedback is a recipient-
   executable next user wish, not an error label. When a real capacity terminal
   proves a model-visible unit is too large, split only at independent semantic
   contract coordinates and let framework code validate and deterministically
   assemble; do not token-chunk or turn sharding into Feedback.

## Compatibility and non-changes

- Producer output contract, ToolSemantics Artifact, graph ports and all later
  consumers remain byte/shape compatible; only rejected-answer diagnostics and
  the authorized next user message change.
- Direct remains Prompt-only with no Skill/tool/workspace. Framework retains
  validation, retry and commit authority.
- ToolSemantics remains one tool per physical shard. The current live evidence
  is not a capacity terminal, so this repair does not split preconditions,
  transitions, postconditions or errors into additional calls.

## Checks and real proof

1. Focused tests for Direct parsing, Feedback conversation and bounded graph
   correction, then full pytest, Ruff, mypy and compileall.
2. Run only the exact frozen-parent `reserve_tool` Direct leaf through Luna and
   read Observe immediately.
3. Success requires either a compiled ToolSemantics Artifact within the two
   existing format calls or a new safe terminal whose Feedback contains the
   exact closed condition; no third format call and no release.
4. A successful leaf still permits only the next Design node/proof. A new
   terminal starts a fresh diagnosis; it does not authorize blind retry or E2E.
