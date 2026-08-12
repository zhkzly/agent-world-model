# Live proof — Direct outer-content replacement action

- Date: 2026-08-12
- Status: passed
- Run: `run_2099d3669a4b4963bc2b4ae7eb7d4eea`
- Boundary: `design/tool_semantics[manage_equipment]`
- Model: Direct `gpt-5.6-luna`, official OpenAI SDK JSON-object mode,
  no Skill/tool/workspace
- Frozen parents: WorldArchitecture `043ca6b8...0549d`,
  SharedToolSemantics `18bb5ca5...fb9d9`, EvidenceGraph
  `93350b0a...680c4` from public run
  `run_804e6cc894674e69b7ea72d0714c8daa`

## Falsifiable claim

The exact shard that previously repeated one `outer_content` condition must
receive the new concrete next-user deletion/replacement action and either
strictly compile within the unchanged two-format-call ceiling or stop honestly
without release. No parser extraction, fallback or third format call is
allowed.

## Result

The proof passed in 81.84 seconds and exercised the changed Feedback:

1. Luna proposal 1 used 6,117 input / 2,699 output tokens and was safely
   rejected at root for non-JSON outer content or extra JSON data.
2. Framework sent the original frozen task, the immediately preceding
   ephemeral answer and the concrete replacement/deletion user instruction.
3. Luna proposal 2 used 7,535 input / 1,523 output tokens, strictly parsed and
   passed the unchanged ToolSemantics compiler.

Framework committed:

- Artifact `design.tool_semantics:cba69d5863417bfb`
- WorkRecord `control.work_record:d52202215e3d35f3`
- compiled digest
  `sha256:d0b881cb8b32930331d1a29b8dedd4806e5abb3de7ae424995c95ae28b33397f`

Immediate Observe shows the shard passed, no Finding and
`release=not_published`. This proves the changed Feedback transaction at this
frozen Direct leaf. It does not prove remaining ToolSemantics, WorldRules,
Curriculum, Tasks, Candidate, Judge, Registry, E2E, Repair, Expand or Consumer.
