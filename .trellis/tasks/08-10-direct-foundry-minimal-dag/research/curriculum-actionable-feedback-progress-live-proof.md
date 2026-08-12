# Live proof — Curriculum actionable Feedback and strict progress

- Date: 2026-08-12
- Status: failed safely
- Boundary: `design/curriculum_plan`
- Route: Direct `gpt-5.6-luna` via the official OpenAI Python SDK, with
  `response_format={"type":"json_object"}` and no Skill/tool/workspace
- Frozen parent source: `run_fb7f87b4307346b3ae2e6843b27f650a`
- Frozen parents:
  - WorldArchitecture `design.world_architecture:e227e876c35c13b0`
  - WorldRules `design.world_rules:828296357d588c0a`
  - EvidenceGraph `design.evidence_graph:cd42b13682753abd`

## Falsifiable claim

Before this change, the first Curriculum proposal failed one exact object-shape
condition; its Feedback produced a semantically distinct second proposal, but
that proposal stopped at a combined task-family-ID/actor condition and no final
correction was available. After this change, each of those fields must produce
its own actionable recipient instruction, and a parsed Direct proposal that
makes strict A-to-distinct-B semantic progress may receive exactly one third
and final proposal. A repeated issue, a format issue, a Provider failure, or a
post-compile validation failure must not receive that third proposal; no fourth
proposal is possible.

The proof passes only if the exact frozen-parent Curriculum leaf commits one
unchanged `CurriculumPlan` Artifact within at most three Luna proposals. Any
new terminal is recorded honestly and ends the proof.

Passing establishes only the Direct Curriculum correction transaction. It
does not establish TaskRequirement, ModelingGate, Candidate, Integration,
Judge, Registry, full E2E, Repair, Expand/multi-parent, or Consumer/SFT/RL.

## Result

Run `run_16b5772c5d2c45d787ec3057b4b3a96c` stopped safely after two
Luna proposals in 93.66 seconds. Both proposals were parsed JSON and reached
the strict Curriculum compiler. Proposal 1 used 10,945 total tokens and was
rejected at `$.families[0]` with condition `object must use exactly the
declared fields`. The next-user Feedback preserved the complete original input,
the complete preceding proposal and that condition. Proposal 2 used 13,867
total tokens and reached the same path and same condition.

Because the complete correction tuple was unchanged, the framework correctly
classified this as no semantic progress and did not admit proposal 3. No
Curriculum Artifact was committed; WorkRecord
`control.work_record:ae3bc7a94e10668b` failed, Observe contains one blocking
Finding, and `release=not_published`.

The proof disproves the leaf-pass claim. It also shows that the new third-turn
authority is not a blind retry: it remains unavailable when Feedback does not
move the validator frontier. The new evidence is a recipient-information
defect—the safe correction names an exact path but says only that the field set
is wrong, while the deterministic compiler already knows the complete expected
field set.
