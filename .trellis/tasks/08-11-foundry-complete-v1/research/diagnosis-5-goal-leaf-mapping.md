# Diagnosis Record 5: materializer_public_goal_invalid (goal leaf mapping)

Date: 2026-08-14 (session)
Real event: run_386e4f07c70d4f61be9cafbf82edcc55, pure resume after the
one-shot transport fix. Terminal: rejected / materializer_public_goal_invalid,
subject build.environment_candidate:702c42bc1708.

## Safe Observe facts

- Integration now reaches task materialization validation (call_once fix
  worked); it fails in _validate_materialization for families 2 and 4.
- Offline repro (/tmp/repro_mat2.py, same materializer + same venv):
  materialize+_safe pass 8/8, but _validate_materialization fails families
  2/4 with materializer_public_goal_invalid.
- Family 2 evidence: schema [('/goal/19','boolean'),('/goal/24','identifier'),
  ('/goal/25','list')] but the materializer returns
  {'19': true, '24': ["offer-2002"], '25': "offers_found"} — the field
  semantics are swapped (24 got the offers list, 25 got the result_status
  enum). Leaf paths match; categories do not.

## Root cause

The Task Materializer v3 contract gives the agent goal leaf paths whose leaf
names are SEMANTIC INDEXES (/goal/24), plus public_goal_fields indexes, but
no explicit index -> field-name/source/category mapping. The agent inferred
meaning from its own task-type branches and mis-assigned values. The
framework's category gate correctly rejected it (the candidate is wrong, not
the gate).

## Five-lens status

Lens 4 (contract projection) supported; lens 2 (what the codegen agent sees)
weak — the missing mapping made the task unnecessarily guessy. The agent's
value generation (difficulty-dependent etc.) is otherwise fine.

## Fix direction (small, framework-owned contract projection)

- candidate.py _materializer_tasks: add "public_goal_fields":
  [{index, name, source, category}] per goal leaf (resolved from the task's
  public_goal_fields + the architecture catalog bindings).
- engineer-environment-codegen skill: instruct the agent to map every
  public_goal leaf to its declared field via that mapping (never via path
  suffix), and to derive values per the mapped name/category.
- The skill digest change re-invalidates candidate_build, so a pure resume
  re-dispatches the codegen agent with the corrected contract.
