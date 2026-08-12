# SharedTool JSON contract — implementation check

- Decision: **allow** for the bounded implementation-check scope.
- Reviewed plan: `shared-tool-json-contract-plan.md`, revision `2/2`.
  Raw SHA-256 recomputed as
  `74fb7af2f3efec6e479c2befece2ac83e0a9ffe6704b104bd0c63e5498e563b7`.
- Matching critic record: `cross-layer-review-74fb7af2-shared-tool-json-r2.md`,
  `Decision: allow`, referenced by the active task's `check.jsonl`.
- Review scope: the approved SharedTool Direct recipient grammar in
  `agent_world/design.py`, its focused regression coverage in
  `tests/test_design_semantics.py`, and the corresponding
  `node-contracts.md` section, plus the named unchanged common Direct and
  downstream boundaries.

## Scope and role-boundary evidence

- The model-visible SharedTool shape is the approved seven-field grammar:
  exact frozen ordered `tool_indexes`; three `1..group_size` collections of
  `1..group_size` frozen members with complete coverage; bounded stripped
  `ordering`/`compensation`; and exact ordered per-member `error_policy`.
  The same grammar and whole-object objective are asserted exactly by the
  focused recipient test, and the task contract describes the same compiled
  fields.
- The compiler still requires the exact top-level field set, exact group echo,
  frozen-member membership and full flattened-set coverage. It does **not**
  impose duplicate/disjoint partition checks. A no-provider compiler probe
  successfully compiled `[[1, 2], [1]]` for each shared dimension, which
  confirms that the disclosed grammar makes no stronger unique/disjoint claim.
  The existing safe correction wording containing “partition” remains an
  unchanged error label, not a newly disclosed uniqueness contract.
- A valid compiled `SharedToolContract` still has the current payload digest;
  ToolSemantics receives and exact-echoes the same compiled contract and binds
  its digest to each `ToolDraft`. The current candidate package projection and
  Registry cold-read retain the same `shared_tool_contracts` fields and digest
  reconstruction.
- `_direct_commit` continues to include the effective projection, rendered
  output shape, and prompt identity in semantic material. The focused test
  proves a changed SharedTool shape rotates that node's semantic revision while
  the `shared_tool_semantics` node remains Designer-owned `DIRECT_LLM`, route
  `direct`, no Skill, and one local compiler correction. Its input/output ports,
  coupling-group shard derivation, and DesignGraph edges to ToolSemantics and
  ModelingGate remain unchanged.
- `_direct_json`, `_json_object`, `DirectChatBackend`, and `GraphRunner` retain
  the existing boundary: a non-JSON response is
  `direct_response_not_json`, becomes a non-correctable Direct failure, makes
  one physical call, commits no SharedTool output, and persists a failed
  WorkRecord plus blocking Finding. A parsed invalid object still receives the
  existing one safe compiler correction; a second invalid proposal receives no
  third call. No `response_format`/native-schema request mode was added.
- The other five Direct node declarations retain their current owner/kind/route
  bindings. No Agent Skill/tool/workspace surface, candidate-process behavior,
  compiler abstraction, graph node/edge, route, response transport, or
  business-specific production semantic was added by this checked change.
  Framework code remains sole owner of group derivation, parsing, validation,
  compilation, digests, Artifact/Work/Finding persistence, Judge, and release;
  the Direct LLM only proposes shared business semantics.

## Findings (fixed)

- None. This was a report-only check; no product, test, plan, or contract file
  was edited.

## Findings (not fixed)

- None within the allowed scope.

## Verification

Commands run from `/home/kelong/pycodes/foundry-direct-graph`:

```text
sha256sum .trellis/tasks/08-10-direct-foundry-minimal-dag/research/shared-tool-json-contract-plan.md
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/test_design_semantics.py
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider
uv run ruff format --check .
uv run ruff check .
uv run mypy --no-incremental agent_world
PYTHONDONTWRITEBYTECODE=1 uv run python -B -m compileall -q agent_world
git diff --check
rg --files -g '*.py' agent_world | sort | xargs wc -l | tail -n 1
```

- Focused pytest: **pass** — 31 passed.
- Full pytest: **pass** — 189 passed.
- Ruff format: **pass** — 22 files already formatted.
- Ruff check: **pass**.
- TypeCheck: **pass** — no issues in 13 source files.
- Compileall: **pass**.
- Diff whitespace: **pass**.
- Production Python: **pass** — 10,296 lines, within the `<= 10,296` cap.
- Provider calls: **none**. The additional duplicate-coverage compiler probe
  used the local fake Direct backend only.

## Scope limitation and non-claims

The three reviewed implementation files are untracked relative to `HEAD`, so
Git cannot provide a predecessor-only line diff for them. This is therefore a
current-code and deterministic-behavior approval of the exact allowed repair,
not a claim about unrelated working-tree history.

This check does not prove that a provider will return JSON, native structured
response support, a fresh SharedTool real execution, full Direct completion,
Candidate/Integration/Judge/Registry release, Repair, Expand, Consumer, SFT,
or RL behavior. A repeated or different real terminal requires a new diagnosis
and matching critic gate; no parser, response-mode, correction-topology, group,
or downstream contract change is authorized by this record.
