# Implementation check — SharedTool conservative partition

- Decision: **allow**
- Plan SHA-256: `85bd13a73024d4accd7e7b2cdcb066c016b594a7807e815124a495b16d56c2a3`
- Reviewed scope: `agent_world/design.py` SharedTool recipient/correction wording,
  the matching `node-contracts.md` card, and `tests/test_design_semantics.py`.

## Scope and authority review

The plan digest recomputes exactly and `check.jsonl` names the matching
`cross-layer-review-85bd13a7-shared-tool-conservative.md` allow.  The current
implementation stays inside that allow:

- The Direct prompt discloses the exact frozen `tool_indexes`, exact-once
  partition requirement, and the permitted conservative one-domain construction
  for the complete ordered group.  The correction for an invalid partition
  carries the same actionable condition.
- `_shared_tool_shards()` still validates and returns the model-proposed
  partitions unchanged.  It does not synthesize, sort, fill, or normalize a
  semantic partition.  The frozen group and validation remain framework-owned;
  grouping, ordering, compensation, and policy text remain Direct-LLM semantics.
- `shared_tool_semantics` remains `designer/direct_llm/direct`, with
  `skill=None`; its Direct backend call takes only system/user text, not a Skill,
  tool, or workspace.  The Agent and candidate-process paths are untouched.
- The six source fields, compiler acceptance, `SharedToolContract`, ToolDraft
  digest binding, ModelingGate shared references, Candidate package projection,
  Registry revalidation, graph topology, route, and retry policy are unchanged.
  The runner still permits only ordinal 1 to request the one local correction,
  so this work has at most two calls.
- The focused regression asserts the new visible shape, unchanged compiled
  contract digest and downstream ToolDraft consumers, an actionable correction
  with exactly two calls, and a changed semantic revision when the output shape
  changes.  Existing cold-read/Registry regressions retain exact partition and
  digest rejection.

The canonical SharedTool rule and the Direct-versus-Agent execution map align
with the card wording.  No product code changed after the plan other than
`agent_world/design.py`; the paired card and test are the plan's two allowed
non-production files.  The three reviewed file hashes were unchanged before
and after verification.

## Verification

- Focused: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -q tests/test_design_semantics.py tests/test_graph_contracts.py tests/test_direct_release.py` — pass (`110 passed`).
- Full: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -q` — pass (`204 passed`).
- Legacy firewall: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -q tests/test_legacy_firewall.py` — pass (`2 passed`).
- Ruff format/check: pass (`22 files already formatted`; `All checks passed!`).
- Type check: `uv run mypy --no-incremental agent_world` — pass (`13 source files`).
- Compileall: `PYTHONDONTWRITEBYTECODE=1 uv run python -B -m compileall -q agent_world` — pass.
- Diff whitespace: tracked and staged `git diff --check` pass; the three named
  untracked review files have no trailing whitespace.
- Production Python: `10,315` lines, within the inherited `10,320` Direct
  ceiling.

## Non-claims and next gate

No real provider, Agent, candidate, Judge, Registry, or E2E invocation was run
by this check.  The next permitted proof remains the immutable-parent Luna
SharedTool suffix, then only `tool_semantics[register_member]`, followed by an
Observe read; a fresh public Direct E2E requires that suffix to pass.
