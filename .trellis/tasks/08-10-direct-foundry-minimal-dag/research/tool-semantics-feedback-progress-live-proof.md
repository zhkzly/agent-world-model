# Live proof — ToolSemantics Feedback progress

- Date: 2026-08-12
- Status: failed safely; new diagnosis required
- Diagnostic run: `run_5d7bd3a844d4458daa56670f4c0003b9`
- Changed boundary: `design/tool_semantics[reserve_tool]`
- Model/profile: Direct `gpt-5.6-luna`, official OpenAI Python SDK, no Skill,
  tools, workspace or Agent
- Frozen-parent source: failed public run
  `run_bb8b2474bfd34507b1b73f7856c77ee3`
- Exact dependencies:
  - WorldArchitecture
    `sha256:24a4f0ed49e9b02d1ee1f3c926bb5104e4eac9dd82365e1e086e433d9784e1ae`
  - SharedToolSemantics
    `sha256:1abaa04c0de92a80aa1a20198e665227275c03ee5467f5346265fb515c2a8d79`
  - EvidenceGraph
    `sha256:72f033b356d0d3656f1f9ad23be0224518bad8b116a3284386c3d687d961f793`

## Falsifiable claim before execution

Before the change, the exact frozen ToolSemantics request produced safe issue A,
then different issue B, and framework stopped after two completed Luna calls.
After the change, the same uncommitted coordinate must either commit a strictly
compiled ToolSemantics proposal within three total calls or terminate safely
without a fourth call. If A changes to B, only the new user-style Feedback path
may authorize the final call. Original Prompt/input/output contract and all
three parent bytes remain unchanged.

This establishes only the live Direct leaf, correction admission, operation
evidence, Work/Artifact commit-or-terminal and safe Observe boundary. It does
not establish remaining Design, Candidate, Integration, Judge, Package,
Registry, E2E, Repair, Expand or Consumer/SFT/RL.

## Result

The exact-parent leaf made two completed Luna calls and committed no
ToolSemantics output. Attempt one returned completed nonempty content that did
not strictly parse as one JSON object, so framework sent the one authorized
format Feedback turn. Attempt two had the same safe terminal
`direct_response_not_json`; framework made no third call because format failure
is not semantic A-to-B progress.

Operation evidence reports, respectively, 5,885 input / 1,976 output / 7,861
total tokens and 7,131 input / 2,320 output / 9,451 total tokens. Observe reports
one failed Direct Work, one blocking Designer Finding,
`release.status=not_published`, and exact unchanged dependency IDs. No raw
response or Feedback text was persisted.

This proves the repaired graph did not over-retry or publish on a format
terminal. It does not prove parsed-semantic Feedback or a successful leaf. The
new terminal is handled by
`diagnosis-direct-format-feedback-repeat.md`; no public E2E is permitted.
