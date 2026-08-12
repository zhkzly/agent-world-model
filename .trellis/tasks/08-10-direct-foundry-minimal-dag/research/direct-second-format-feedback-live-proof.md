# Live proof — bounded second Direct format Feedback

- Date: 2026-08-12
- Status: passed (proposal one; final Feedback path not consumed live)
- Run: `run_f98e5178e3b04c0c9b7b960a7ac26817`
- Boundary: `design/tool_semantics[manage_maintenance]`
- Model/route: Direct `gpt-5.6-luna`, official OpenAI SDK JSON-object mode,
  no Skill/tool/workspace
- Frozen source run: `run_6df6b3046ae64983847f44621ac81a1c`
- Exact parents:
  - WorldArchitecture
    `sha256:4c6018e7ff9d1115b66576229ffb5df204980514dab622426f14384cbf6587c0`
  - SharedToolSemantics
    `sha256:1bb571d55fc15d6cf991d53e70ed173b3ae6b512cff8a6177feca73eb0937e4d`
  - EvidenceGraph
    `sha256:334af1662f9ef22c1ea6bc1030f89eff1321d58c32a650e82d5a860cf0df116a`

## Falsifiable claim

Before the change, the exact shard stopped after proposal two repeated the safe
outer-content condition even though its node declared two corrections. After
the change, the real transaction must either compile within at most three
proposals or fail honestly after proposal three; a repeated format-first path
must receive the final framework-authored user Feedback and there must never be
a proposal four. Strict parsing, ephemeral rejected content, frozen inputs and
non-release remain unchanged.

This proof establishes only this Direct leaf and its bounded correction
transaction. It does not establish later Design, Candidate, Integration,
Judge, Registry, E2E, Repair, Expand or Consumer.

## Result

The exact frozen leaf passed on Luna proposal one in about 49 seconds, so this
real run did not need either local Feedback turn. Framework committed:

- `design.tool_semantics:8c24aad938fb88ed`
- `control.work_record:2796fc5f4c550689`
- compiled digest
  `sha256:4b7e7ce44944c31d9e58eeed3f3c78558f737f08b754c302556e2b51f833220f`

The operation used 6,397 input and 2,398 output tokens with Luna and
`skill_digest=null`. Immediate Observe shows one passed Direct Work for shard
`manage_maintenance`, no Finding and `release=not_published`; the diagnostic
run itself ended with the explicit non-release code
`diagnostic_scope_complete`.

This establishes that the exact formerly failing shard can compile and commit
without parser or contract weakening. It does **not** live-demonstrate the new
third proposal because proposal one passed. The no-fourth-call and both final
Feedback transitions remain deterministic evidence from the 13 targeted tests.
Per the allowed proof plan, the committed leaf permits one fresh public E2E.
