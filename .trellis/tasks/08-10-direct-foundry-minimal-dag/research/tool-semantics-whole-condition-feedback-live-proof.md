# Live proof — whole-condition ToolSemantics Feedback

- Date: 2026-08-12
- Status: passed
- Boundary: `design/tool_semantics[reserve_tool]`
- Route: Direct `gpt-5.6-luna` via official SDK, no Skill/tool/workspace
- Frozen parent source: `run_bb8b2474bfd34507b1b73f7856c77ee3`
- Parent digests: WorldArchitecture `24a4f0ed...9784e1ae`,
  SharedToolSemantics `1abaa04c...c2a8d79`, EvidenceGraph
  `72f033b3...961f793`

## Falsifiable claim

Before the change, exact path Feedback removed one effect-value issue but the
same condition recurred at another path before the existing three-proposal
ceiling. After the change, Feedback must call the path one observed occurrence,
state the exact accepted effect-value construction, and ask Luna to inspect and
repair every same-condition occurrence in the complete previous proposal. The
leaf must either commit the unchanged ToolSemantics Artifact or stop safely
after at most three proposals. No fourth call or release is possible.

This proves only this Direct leaf and its correction transaction, not the
remaining Design, Candidate, Judge, Registry, E2E, Repair, Expand or Consumer.

## Result

The exact frozen-parent leaf passed in `run_1c2c30385a1842d89449e1072e9db5de`
after three Luna proposals (203.65 seconds wall time). Attempt 1 reported one
invalid condition literal, attempt 2 reported one invalid effect value, and
the actionable Feedback asked for the observed occurrence plus every
same-condition occurrence in the complete previous proposal. Attempt 3 passed
strict framework compilation and committed:

- Artifact: `design.tool_semantics:3d912f62acd894d1`
- WorkRecord: `control.work_record:f5de2feb2511fecd`
- Validation: `control.validation:ecd5c3c3468453b7`
- Model: `gpt-5.6-luna`
- Usage: `9779`, `12778`, and `12825` total tokens across the three proposals

Immediate `agent-world observe` showed `tool_semantics[reserve_tool]` as
`passed`, with no Finding and `release=not_published`. The diagnostic harness
intentionally leaves the enclosing run open because it proves one leaf only.
This establishes the changed Feedback transaction at this Direct leaf. It does
not establish the remaining Design suffix, Candidate, Judge, Registry, E2E,
Repair, Expand, or Consumer paths.
