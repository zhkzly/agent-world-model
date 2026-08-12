# WorldArchitecture purpose normalization — implementation check

- Decision: allow
- Reviewed plan / allow: `world-architecture-purpose-normalization` revision
  2/2, digest
  `a3ed41405a5597299fcc7f7e669489304541ebfff5042f0ab45885afb562e0a8`.
  `check.jsonl` references the matching current `Decision: allow` record.
- Scope reviewed: `agent_world/design.py`,
  `tests/test_design_semantics.py`, and this task's `node-contracts.md` only.

## Findings

No findings. No code or contract changes were needed.

- Ownership remains exact: `world_architecture` remains a Designer-owned
  `DIRECT_LLM` transaction; its compiler, correction packet, Artifact commit,
  WorkRecord, identity, and release-adjacent facts remain framework-owned.
  No Agent Skill/tool/workspace, candidate-process authority, or Registry/Judge
  authority was added.
- `boundary.purpose` is locally stripped once, rejected unless nonempty and at
  most 4096 Python Unicode code points, and stored as the entire stripped
  value. It is never sliced. `name`, `system_of_record`, and `authority` still
  use their separate 160-code-point `_text` validation.
- The recipient shape is exactly split between the 160-code-point identity
  fields and `purpose:stripped_text[1..4096_unicode_code_points]`. The
  whitespace/non-string and over-limit correction packets use the required
  code, path, condition, and category.
- The rendered output shape remains part of WorldArchitecture semantic
  material, so the acceptance-policy change rotates its semantic revision.
  Focused regression coverage proves the same full committed purpose reaches
  the Architecture Artifact, WorldRules/Curriculum projections, Builder
  projection, and packaged WorldSpec metadata; the existing package/Registry
  cold-read comparison remains on that same canonical metadata path.
- The selected implementation introduces no helper, route/model/retry change,
  Skill, Node/Edge, candidate, Judge/Registry authority, compatibility path,
  or additional design surface. The task-contract wording now specifies the
  4096 Python-Unicode-code-point unit.

## Verification

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_design_semantics.py` | pass — 26 passed |
| `uv run pytest` | pass — 184 passed |
| `uv run ruff format --check .` | pass — 22 files already formatted |
| `uv run ruff check .` | pass — All checks passed |
| `uv run mypy agent_world` | pass — no issues in 13 source files |
| `uv run python -m compileall -q agent_world` | pass |
| `git diff --check` | pass — no output |

## LOC

`find agent_world -type f -name '*.py' -print0 | xargs -0 wc -l` reports
**10,296** production Python lines, within the **10,298** cap.

## Proof non-claims

This static and deterministic check does not prove a real WorldArchitecture
provider invocation, full Design, Candidate, Integration, Judge, Registry,
Repair, Expand, Consumer, or end-to-end EnvironmentPackage release.

## Next gate

Run the critic-prescribed fresh WorldArchitecture Direct invocation with the
same evidence class, then inspect its WorkRecord, committed Artifact, and safe
Observe scene. It must show an accepted stripped purpose longer than 160 and no
longer than 4096 code points without correction or truncation. Do not run the
fresh public Direct CLI proof until that boundary proof passes.
