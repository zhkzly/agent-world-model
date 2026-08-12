# Implementation check — SharedTool policy binding

- Decision: **allow**
- Reviewed plan SHA-256: `fa1d572a39fe6c1fd23e4e2a1f67e625cf11e06bcc3030dcff51f7a76fd247ca`
- Matching critic record: `research/cross-layer-review-fa1d572a-shared-policy-binding.md`

## Scope and authority review

`check.jsonl` names the exact plan and matching `allow`; the plan file
rehashes to the recorded SHA-256.  The reviewable post-allow implementation
slice is limited to `agent_world/design.py`, the matching
`node-contracts.md` card, and `tests/test_design_semantics.py`.  The broader
dirty worktree predates this slice and was left untouched and unattributed.

- Direct `shared_tool_semantics` remains
  `designer/direct_llm/direct`, with `skill=None`.  Its backend accepts only
  `system` and `user`; no Skill, tool, or workspace is present.
- The source draft now accepts one stripped nonempty `error_policy` string of
  at most 280 code points.  Framework code repeats that exact model-authored
  text over the frozen ordered members; it does not synthesize, normalize, or
  choose policy semantics.
- The compiled `SharedToolContract.error_policy` remains the ordered
  per-member tuple.  Its serialized payload remains the existing list of
  `{tool_index, policy}` objects and uses the existing digest formula.
- ToolDraft still receives the compiled shared-contract digest, Modeling Gate
  consumes the same shared-tool port, Candidate package projections and
  Registry cold-read retain the compiled representation, and Observe exposes
  neither source policy nor new authority.  The existing hand-built fixture
  with distinct per-member compiled policies remains valid.
- Node/edge/route topology is unchanged.  The runner still permits one local
  correction and at most two calls; the changed source shape participates in
  the SharedTool semantic-revision digest.
- Array, blank, and overlong source values reject at `$.error_policy` with
  expected category `string`.

## Verification

- Focused Design/graph/package/Registry: `113 passed`.
- Package/Registry regression module: `29 passed`.
- Full test suite: `207 passed`.
- Legacy firewall: `2 passed`.
- Ruff format/check: pass (`22 files already formatted`; `All checks passed!`).
- Mypy: pass (`13 source files`).
- Compileall: pass.
- Diff whitespace: `git diff --check` passed; the three untracked scoped
  files have no trailing whitespace.
- Production Python: `10,303` lines, within the inherited `10,320` Direct
  ceiling.

## Non-claims

This is deterministic implementation verification only.  It does not prove
the immutable-parent Luna suffix, a public Direct E2E, Candidate, Judge,
Registry publication, Repair, Expand, or Consumer behavior.  The next
separate permitted proof remains the bounded SharedTool-plus-first-ToolSemantics
suffix with a safe Observe read.
