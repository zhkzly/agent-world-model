# Live proof — official Direct SDK at the failed ToolSemantics boundary

- Date: 2026-08-12
- Result: **pass; allow one fresh public Direct E2E**
- Proof run: `run_bd73c8f6968a4ae19af5789f71718db1`
- Source parents: exact immutable Architecture, SharedToolContract and Evidence
  from failed public run `run_dc28dcded7fe49ce9a2d9a017511831d`
- Frozen model-visible projection digest:
  `sha256:3cd2f9233e6ff60ef260ba975caaae90bcc10c63993192d95156ffefc0e409ea`
- Node/shard: `design/tool_semantics[route_tool_to_maintenance]`
- Backend/model: official OpenAI Python SDK, Direct `gpt-5.6-luna`; no Skill,
  tools, workspace or Agent

## Safe result

- One real call, zero correction.
- Usage: 6,431 input, 1,723 output, 8,154 total tokens.
- Strict compiler committed
  `design.tool_semantics:2b064c4a0e1f3165`.
- WorkRecord: `passed`; one passed attempt; one
  `assurance.operation` with model and measured usage.
- Observe: one passed Direct Work, no Finding,
  `release.status=not_published`.
- A run-directory scan found no `raw_content`, prior-assistant, Feedback
  message, raw-response or transcript field/text.

The provider returned a valid object on attempt one, so this live proof did not
exercise the stochastic malformed-first-result branch. That branch remains
covered by deterministic two-call tests, not relabelled as a live recovery.

One harness preflight created
`run_a5aa513f66a947b292b090af92703f27` before rejecting an invalid sliced
Architecture. It crossed no provider boundary, produced no Work, was explicitly
closed as `diagnostic_harness_invalid`, and is not product evidence.

## Claim boundary

This proves the official Direct SDK adapter, exact current Prompt/input,
strict ToolSemantics compiler, operation evidence, Artifact commit and Observe
projection for the previously failing leaf. It does not prove remaining
Design, Candidate, Integration, Judge, Registry, release, live format recovery,
Repair, Expand or Consumer/SFT/RL.

The next permitted proof is one fresh natural-language public Direct E2E. Read
Observe immediately at its first terminal and stop there on failure.

