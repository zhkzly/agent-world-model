# Direct C6 whole-diff check — block

Date: 2026-08-11
Reviewer: independent `trellis-check`, Codex `gpt-5.6-terra`
Decision: `block`

## Authorization and scope

The active Direct C6 digest was independently reproduced as
`ed917488dc2ba845c7577a4bf7770c66ff4691a6412650fa2af8a55a9e8fe570` and
the parent C6 digest as
`6e3d4c9cebc4836ce7a872cce11e7fe687e1d3d6154d0ce77460371811186f0e`.
They match `plan-digest-r9-c6-contract-closure.md`,
`plan-digest-contract-closure-c6.md`, and the current `allow` record
`cross-layer-review-ed917488-c6.md`.

The full diff was reviewed from baseline
`9562c058b61562c11f76d8127f56b68b0f5be2d9`, including untracked Direct
modules and tests. No real provider, Agent, Jina, generated candidate, or E2E
service was invoked. The mandated full pytest suite did run its existing
deterministic fixture wheel-install regression.

## C5 closure audit

- Graph named-port and literal-edge enforcement is present in
  `agent_world/graph.py`; focused hostile binding tests pass.
- The private four-family verifier, operation-evidence telemetry, physical
  package/SBOM/Registry/Observe cold reads, strict source scanning, and scrubbed
  candidate environment are present and their deterministic tamper tests pass.
- The code-generation Runtime Skill now permits exact locked registry wheels,
  leaving framework admission authoritative.
- C5 findings 2 and 4 are **not fully closed** for the reasons below; their
  required C6 contract meaning remains unmet despite green deterministic tests.

## Blocking findings

1. **The local correction contract is not exact or complete across model/Agent
   nodes.** `direct-c6-contract-closure-plan.md` requires a packet with the
   exact model-output path, violated condition, and expected category, and
   `node-contracts.md` makes the correction input common to model calls.
   `agent_world/design.py:57-82` instead creates every `DesignError` packet as
   the generic root `$` plus the generic condition “the output must satisfy this
   node's closed contract”, even where the compiler knows a field-level failure.
   `agent_world/candidate.py:611-657` accepts the runner correction argument
   for `build_plan` but drops it before invoking the Agent; its build-plan
   compiler does not create a packet. `candidate_build` constructs a packet in
   its completion validator (`agent_world/candidate.py:354-397`) but its
   `NodeSpec.local_corrections` is zero (`agent_world/graph.py:211-224`), so it
   can never be dispatched. Thus the required frozen projection plus an exact,
   bounded correction is not available for every declared model/Agent contract
   and test coverage only proves one `research_plan` example. This is a
   validation/semantic handoff change, not a mechanical lint repair.

2. **The frozen Builder ABI still omits closed Runtime response schemas, and
   the runtime supervisor accepts the omission.** The C6 plan and critic
   require the frozen `implementation-contract.json` to state every Runtime
   request/**response** shape. `compile_implementation_contract()` records only
   partial `required` fragments for `handshake`, `reset`, `invoke`, and `close`,
   and only `private_framework_only` for `snapshot`
   (`agent_world/candidate.py:199-238`). Correspondingly,
   `agent_world/runtime.py:251-287` checks only `.get("operations")`,
   `.get("status")`, and the nested invoke result; it permits additional
   top-level fields on every operation. A Candidate can therefore return an
   undeclared authority/private field in a Runtime envelope without the frozen
   ABI or Integration rejecting that envelope. This leaves C5's missing exact
   CandidateBuilder protocol disclosure only partially resolved and violates
   the C6 approved plan. Closing it changes the candidate/runtime validation
   contract and needs a bounded revised plan and fresh critic review.

## Whole-diff checks that passed

- `uv run pytest`: `70 passed`
- `uv run ruff format --check .`: pass
- `uv run ruff check .`: pass
- `uv run mypy agent_world`: pass
- `uv run python -m compileall -q agent_world`: pass
- `git diff --check 9562c058b61562c11f76d8127f56b68b0f5be2d9`: pass
- Legacy firewall: `uv run pytest tests/test_legacy_firewall.py` — `2 passed`

The legacy scan found no active `awm`, `StateGraph`, replay, ABI-v1,
compatibility, scheduler/plugin, Repair/Expand, or Consumer runtime path. The
telemetry implementation derives only committed operation evidence; no
hard-coded success telemetry or secret value was found in the reviewed
production path.

## Minimality audit

`agent_world/candidate.py` is 2,335 lines. Its major sections correspond
directly to C6-required Builder ABI compilation, private verifier expansion,
admitted dependency/package closure, Registry cold read, and atomic
publication. No third graph, generic workflow engine, dynamic plugin system,
second release owner, dormant Repair/Expand/Consumer path, or future-only
runtime abstraction was found. The blocking issues are missing contract
closure, not line count or avoidable architectural expansion.

## Required next gate

Revise the C6 plan to specify the closed Runtime response envelopes and precise
per-node correction construction/dispatch, add hostile regressions for both,
obtain a fresh child-specific cross-layer `allow`, then repeat this whole-diff
check. The ordered real proofs remain forbidden.
