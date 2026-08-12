# Real proof — SharedTool policy bound to first consumer

- Date: 2026-08-12
- Run: `run_83585dd10e854697b4ba5b83f9a41419`
- Scope: exact run-358 immutable Evidence and Architecture parents; fresh Luna
  SharedTool `[1-2-3-4-5-6]`; only `tool_semantics[register_member]`; no release.
- Result: passed.

SharedTool committed
`design.shared_tool_semantics:cd7cff6cfa9ebcf3` after one Direct LLM call.
The immediate consumer committed
`design.tool_semantics:d03a8bc01cc0d8dc` after one Direct LLM call. Observe
shows both Work records passed, with exact parent/output IDs, no Findings, and
`release.status=not_published`.

The diagnostic run remains `status=running` by design because the bounded
harness stops before tool two and does not synthesize a terminal release. This
run is non-adoptable and non-publishable. It proves only that the 500-code-point
SharedTool source contract can feed its first real ToolSemantics consumer on
the exact previously failing parents. It does not prove the remaining tools,
Design, Candidate, Integration, Judge, Registry, public E2E or later children.
