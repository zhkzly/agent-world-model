# SharedTool ordering-bound implementation check

Decision: **allow**

Checked against revision 2/2 plan
`sha256:377db0d17fe74c459112f40a749fe702e5a24766d777296ba99647c25cc977d7`.
Its SHA-256 matches the plan bytes, and the latest `check.jsonl` entry points
to the matching `allow` review.

## Scope and implementation evidence

- The latest ordering diagnosis attributes the public terminal only to
  `$.ordering` exceeding the disclosed 160-code-point limit. Revision 2
  correctly narrows the repair to that field; it does not adopt the diagnosis's
  superseded suggestion to widen compensation.
- `agent_world/design.py` validates `ordering` items at 500 code points and
  keeps `compensation` at 160. Both remain arrays of 0..8 items.
- The rendered Direct output shape and the SharedTool node card disclose the
  same `ordering <=500` / `compensation <=160` contract.
- The output shape remains semantic material for the Direct work commit, so
  changing 160 to 500 rotates the SharedTool semantic revision. The focused
  regression verifies that a changed output shape changes the semantic
  revision; it also verifies the compiled SharedTool digest and both ToolDraft
  shared-contract digests.
- `SharedToolContract` construction/order/digest input, ToolSemantics shared
  projection, ModelingGate `shared_tools` input, and the Direct execution order
  remain intact. The focused graph and release/Observe regressions passed,
  covering the unchanged Candidate, `rule-ir@1`, `envpkg@1`, Registry, and
  Observe seam. Expand remains only the unchanged shared-graph compatibility
  seam/non-claim.
- The SharedTool node remains `direct_llm`, route `direct`, with no Skill and
  one local correction (therefore at most two calls). Focused tests assert the
  route/Skill/port topology and exact two-call correction behavior.

## Focused boundary regressions

- 500-character ordering is accepted after an exact `$.ordering` correction
  from a 501-character proposal.
- A 161-character compensation proposal still fails with the exact
  `$.compensation` / 160-code-point correction.
- The cardinalities, compiled SharedTool fields, digest behavior, ToolDraft
  linkage, ModelingGate dependency, candidate/package/Registry checks, and
  read-only Observe checks remain covered by the focused test files.

## Verification

- Focused SharedTool tests: `3 passed, 51 deselected`
- Full test suite: `212 passed`
- Firewall + Direct release: `31 passed`
- Ruff: pass
- mypy: pass (`13 source files`)
- `compileall -q agent_world`: pass
- `git diff --check`: pass
- Production Python LOC: `10,318` (limit `10,320`)

## Diff note and non-claims

The worktree was already broadly dirty and `agent_world/design.py` is an
untracked cleanroom file, so Git cannot provide a patch-level before/after
attribution for this narrow change. The allow is based on the exact current
source/card/test contract above and the matching plan/review, not on an
assertion that the entire pre-existing worktree is clean. This check made no
product or test changes.

This deterministic check does not prove the planned live SharedTool suffix,
full Direct E2E, Candidate/Judge/Registry publication, Repair, or Expand.
