# Check — SharedTool policy-bound implementation

- Decision: allow
- Reviewer: independent `gpt-5.6-terra` / max, read-only
- Date: 2026-08-12
- Base: PAC-139 and `shared-tool-ordering-bound-implementation-check.md`

## Evidence

Against the explicit PAC-139 base, current code, node card and tests match the
authorized policy-only delta: the SharedTool `error_policy` validator and
rendered output shape move from 280 to 500 code points; the card says 500; the
expected shape says 500; invalid input uses 501; and the focused test proves
the exact correction followed by a committed 500-code-point policy. Ordering
remains 500 and compensation remains 160.

The stated base resolves the prior evidence-only block caused by wholly
untracked cleanroom files being absent from plain `git diff`.

## Role boundary

SharedTool remains Direct LLM and has no Skill, tools or workspace. The model
authors only policy meaning. Framework owns the fixed bound, validation,
frozen-member binding, digest computation, graph/Work commit and all existing
downstream gates. Agent, candidate-process, ABI and graph seams are unchanged.
Fresh value-level digests may differ while field sets and digest recipes stay
unchanged.

## Independent commands

- `uv run pytest -q tests/test_design_semantics.py` — 55 passed.
- `uv run ruff check agent_world/design.py tests/test_design_semantics.py` —
  passed.
- `uv run mypy agent_world` — passed.
- Production Python count — 10,318 lines, within the 10,320 ceiling.

## Non-claims

No live proof was run by the reviewer. This allow does not prove the 500 bound
is sufficient for Luna, any remaining Design node, candidate execution, Judge,
Registry publication, public E2E, Repair, Expand or Consumer behavior.
