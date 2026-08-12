# Implementation check — actionable Direct Feedback

- Date: 2026-08-12
- Decision: **allow**
- Approved plan digest: `d94bba5476f326f34778c0cff4b602fed697e9cd09c482bc258bdb59e4b35f90`
- Matching critic: `research/cross-layer-review-d94bba54-actionable-feedback.md`

## Scope and files reviewed

The active `check.jsonl` references the matching current critic record.  The
raw SHA-256 of `research/direct-actionable-feedback-plan.md` is exactly the
approved digest above.  Review was restricted to the requested implementation
delta:

- `agent_world/invocation.py`
- `agent_world/design.py`
- `tests/test_agent_route_config.py`
- `tests/test_design_semantics.py`
- `tests/test_graph_contracts.py`

Files fixed: none.  No unrelated dirty-worktree file was edited or reverted.

## Contract review

- Feedback carries the safe root path, observed violated condition, and expected
  object category; it asks for the condition-specific change, one complete JSON
  object replacement rather than a patch/explanation/Markdown, and a whole-
  object self-check.
- Direct parsing remains strict.  A fenced object, outer/extra content,
  non-object JSON root, and invalid JSON syntax are classified only for the
  private correction path; none is stripped, extracted, coerced, or accepted.
- Rejected text remains in `_DirectFormatFailure.raw_content` only long enough
  to become the immediately preceding in-memory assistant turn.  Persisted
  attempt/failure/operation artifacts contain only the safe `CorrectionPacket`
  and operation facts, and the focused artifact-byte checks exclude raw text.
- The original system text, frozen user payload, output shape, official SDK
  `response_format={"type":"json_object"}`, route, and four-message sequence
  (`system`, original `user`, rejected `assistant`, Feedback `user`) remain
  unchanged apart from the authorized user Feedback content.
- The existing ceiling remains intact: malformed Direct output returns a private
  format failure rather than invoking the fallback, and GraphRunner's existing
  `direct_response_not_json` guard prevents a third ToolSemantics proposal.
  No graph, retry policy, model, Skill, compiler, topology, downstream ABI, or
  sharding implementation changed in this review scope.

## Verification

- Focused: `uv run pytest tests/test_agent_route_config.py tests/test_design_semantics.py tests/test_graph_contracts.py` — **133 passed**.
- Full: `uv run pytest` — **236 passed**, including **2 legacy-firewall tests**.
- Format: `uv run ruff format --check .` — **pass** (22 files already formatted).
- Lint: `uv run ruff check .` — **pass**.
- Type check: `uv run mypy agent_world` — **pass** (13 source files).
- Compile: `uv run python -m compileall -q agent_world` — **pass**.
- Diff whitespace: `git diff --check -- agent_world/invocation.py tests/test_agent_route_config.py` — **pass**.

## Compatibility and non-claims

This check establishes only deterministic conformance of the private
parser-to-Feedback handoff.  It does not prove that Luna will produce a strict
object, that `reserve_tool` will compile, or any DesignGraph suffix,
Candidate/Integration/Judge/Package/Registry, repair, Expand, Consumer, or
end-to-end outcome.  It does not establish a capacity failure or authorize
semantic sharding.

## Next permitted proof

The exact frozen-parent `design/tool_semantics[reserve_tool]` proof is
**permitted** under the matching allow.  It is limited to the existing two
format calls, must read Observe immediately after its terminal, and must not be
reported as an E2E or release proof.
