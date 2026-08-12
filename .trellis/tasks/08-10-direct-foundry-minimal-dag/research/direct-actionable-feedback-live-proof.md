# Live proof — actionable Direct Feedback

- Date: 2026-08-12
- Status: failed safely at a new semantic terminal
- Diagnostic run: `run_9916d45626bf4ab3b11535c96fe50aa1`
- Boundary: `design/tool_semantics[reserve_tool]`
- Model/profile: Direct `gpt-5.6-luna`, official OpenAI Python SDK,
  `response_format=json_object`, no Skill/tool/workspace
- Frozen-parent source run: `run_bb8b2474bfd34507b1b73f7856c77ee3`
- Exact dependencies:
  - WorldArchitecture
    `sha256:24a4f0ed49e9b02d1ee1f3c926bb5104e4eac9dd82365e1e086e433d9784e1ae`
  - SharedToolSemantics
    `sha256:1abaa04c0de92a80aa1a20198e665227275c03ee5467f5346265fb515c2a8d79`
  - EvidenceGraph
    `sha256:72f033b356d0d3656f1f9ad23be0224518bad8b116a3284386c3d687d961f793`

## Falsifiable claim before execution

Before the change, the exact leaf completed two Luna responses, but strict
parsing rejected both and the sole format Feedback said only that the answer
was not one valid JSON object. After the change, any first strict-parser
rejection must retain one safe closed condition in its correction evidence and
send a next-user instruction that identifies the condition, says what to
change, asks for the complete replacement object, and requires whole-contract
self-check. The leaf must either commit the unchanged ToolSemantics Artifact or
terminate safely. A format rejection may authorize only its existing second
format call and never borrow the ToolSemantics semantic-progress third call.

This proof establishes only this real Direct leaf, actionable correction
projection, strict validation, Work/Artifact commit-or-terminal and safe
Observe. It does not establish the remaining Design suffix, Candidate,
Integration, Judge, Package, Registry, E2E, Repair, Expand or Consumer/SFT/RL.

## Result

All three Luna responses parsed as JSON objects; the prior
`direct_response_not_json` terminal did not recur. Attempt one was rejected at
`$.preconditions[2].when` for array cardinality. After the first actionable
Feedback that issue disappeared; attempt two was rejected at
`$.transitions[3].effects[2].value`. After the second actionable Feedback that
issue disappeared; attempt three stopped at the same effect-value condition at
the different path `$.transitions[4].effects[2].value`.

Observed usage was 5,885 input / 3,694 output, then 9,032 / 3,430, then 9,038 /
3,234 tokens. Observe reports three Direct operations, two distinct correction
packets, one failed Work/Finding, and `release=not_published`. No fourth call
occurred and no ToolSemantics Artifact committed.

This proves the revised Feedback reached Luna and supported exact A-to-B-to-C
progress while strict parsing and the existing ceiling remained intact. It
also exposes a new recipient defect: the instruction says “change the response
at that path,” and Luna repaired individual occurrences rather than reliably
applying the same condition across the complete replacement. This is not a
successful leaf or E2E. The new terminal is handled by
`diagnosis-tool-semantics-feedback-global-repair.md`.
