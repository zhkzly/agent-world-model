# Direct C7 final whole-diff check — block

Date: 2026-08-11

Decision: **block**. This independent deterministic review used clean worktree
`foundry-direct-graph` at baseline
`9562c058b61562c11f76d8127f56b68b0f5be2d9`; it did not invoke a provider,
Codex Agent, network/research adapter, candidate process, proof, or E2E.

## Planning identity and allowed C7 closure

- Direct digest recomputed as
  `254ffcb209e320b5849f789ad91049592a2809ff013e21bc90f53ffcf1947aff`.
- Parent digest recomputed as
  `c0473577fd55a103f014fe36943a99967c4ad165234686e9a65bc64099bf403d`.
- The C7 implementation has the exact one safe correction handoff for eligible
  Direct/Agent compiler rejections, confines CandidateBuild correction to its
  completion JSON, and keeps provider/framework/process/Integration/Judge/
  Package/Registry terminals out of correction. Runtime validates the closed
  handshake/reset/invoke/snapshot/close responses, and snapshot state is not
  projected publicly. No C7 feedback/schema/retry framework or unnecessary
  C7-specific abstraction was found; the large `candidate.py` and `design.py`
  sections remain tied to the C6 contract closure.

## Blocking finding: graph ports do not close actual causal inputs

The C5 graph-port finding is only partially closed. `GraphRunner._resolve_inputs`
validates the exact target port set, but validates only a producing *node*;
it discards `EdgeSpec.source_port` (`agent_world/graph.py:538-585`). A single
output envelope can therefore satisfy any target port from the same producer,
without proof of the declared logical source port. The C6 plan explicitly
requires that port identity remain explicit even when a multi-port node stores
one immutable envelope (C6 plan:12-27), and the node contract requires exact
consumed/disclosed port refs in `WorkRecord.input_refs` and causal refs in
`dependency_refs` (node-contracts:50-58).

The executor bindings also omit artifacts they actually use:

- `DesignExecutor._research_synthesis` gives source text to the Agent but binds
  only request, plan and citation catalog (`design.py:515-540,598-606`).
- `DesignExecutor._direct_task` projects architecture and tools, and compiles
  against the first tool, but binds only curriculum and rules
  (`design.py:1056-1189`; `graph.py:194-202,300-301`).
- `DesignExecutor._modeling_gate` consumes evidence and tools but records only
  architecture, curriculum, task and rules (`design.py:1209-1253`; graph
  spec `graph.py:204-210,302-305`).
- Package uses verifier and semantic/implementation lineage refs, but they are
  absent from its bindings (`candidate.py:1278-1380`; `graph.py:268-274,
  314-316`). Registry consumes the actual dossier, telemetry and both lineage
  refs, but binds the package envelope as its `dossier` input and omits the
  others (`candidate.py:1389-1470`; `graph.py:277-283,317-320`).

Thus the committed envelope and WorkRecord do not carry the complete exact
input/dependency closure for transactions whose prompt, compiler, package or
publication behavior used those values. This is semantic provenance/graph
contract work, not a safe mechanical repair. A revised, narrowly scoped plan
and fresh cross-layer review must choose and test the port-bearing artifact
representation and every missing binding; it must add hostile source-port
substitution and complete input-closure tests. Real proofs remain forbidden.

## Deterministic verification

- `uv run pytest`: pass (88 passed)
- `uv run ruff format --check .`: pass (21 files already formatted)
- `uv run ruff check .`: pass
- `uv run mypy agent_world`: pass (13 source files)
- `uv run python -m compileall -q agent_world`: pass
- `git diff --check 9562c058b61562c11f76d8127f56b68b0f5be2d9`: pass
- `uv run pytest tests/test_legacy_firewall.py`: pass (2 passed)

No source files were changed by this review. This record and its `check.jsonl`
entry are the only review writes, both in the clean worktree's active Direct
task.
