# Real proof — semantic ResearchPlan Agent

## Result

- Run: `run_c180b70173214a6b86e48b4bedaa7fb8`
- Node: `design/research_plan`
- Execution: real Codex SDK Agent
- Model: configured primary `gpt-5.6-luna`
- Runtime Skill: `research-world-evidence`
- Skill digest: `sha256:0fe96de91a5bf3695c6fa3aeb1cc91dc2dda52bc140bde4648e6a6f8bd8425bb`
- Work status: `passed`
- Invocation count: 1; correction: none
- Output: 4 queries and 12 questions
- SDK usage: 14,539 input, 435 output, 68 reasoning-output, 14,974 total tokens

Observe reports the committed `design.research_plan`, one passed WorkRecord, no
Finding and `release=not_published`. The backend used its existing disposable
workspace/home and singleton Runtime Skill checks; no credential value was
printed or persisted.

This proves the current semantic Agent graph boundary, not Search/Fetch/Extract,
ResearchSynthesis, remaining Design, Candidate, Integration, Judge, Registry,
Expand, Consumer or E2E. The partial proof run intentionally remains running.
