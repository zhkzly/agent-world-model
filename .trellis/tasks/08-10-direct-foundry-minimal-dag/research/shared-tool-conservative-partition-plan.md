# Plan — disclose the conservative SharedTool partition

- Diagnosis: `diagnosis-shared-tool-conservative-partition-undisclosed.md`
- Revision: 1/2
- Scope: local Direct recipient-contract repair

## Authority and compatibility

- Keep `shared_tool_semantics` as `designer/direct_llm/direct`, with no Skill,
  tools or workspace.
- Keep framework ownership of the frozen ordered group, exact validation,
  correction budget, compiled `SharedToolContract`, digest, Work/Artifact,
  downstream Judge and release.
- Keep Luna ownership of the semantic partition choice plus ordering,
  compensation and error-policy text.
- Keep all six source fields and the compiled downstream ABI unchanged, so
  ToolSemantics, ModelingGate, Candidate projection, Package, Registry and
  future Expand parent reads remain compatible.

## Minimal implementation

1. In `agent_world/design.py`, change only the existing SharedTool output-shape
   sentence and the existing `$.atomicity|concurrency|idempotency` partition
   correction condition. State that each dimension must use every exact input
   `tool_indexes` member once, and that the conservative valid form is one
   nested domain containing the complete ordered input group unless evidence
   requires a finer split.
2. Align only the SharedTool source card in `node-contracts.md`.
3. Update focused existing tests to assert the exact visible instruction,
   actionable correction and unchanged compiled partition/digest consumers.

Do not change contracts, fields, compiler acceptance, graph, route, provider,
response mode, retries, call count, Agent code, Candidate, Registry, Observe or
later-child behavior. Do not add a helper/module or normalize an invalid model
partition in framework code.

## Checks and true proof

- Run the focused SharedTool and downstream Design tests, then full pytest,
  Ruff, mypy, compileall, legacy firewall and the production-line ceiling.
- Obtain a fresh independent implementation check.
- Re-run only the immutable-parent diagnostic suffix: real Luna SharedTool,
  then only `tool_semantics[register_member]`, stopping before the second tool.
- Read Observe. Only if the suffix passes may one fresh public Direct E2E run.

Non-claims: deterministic success is not provider success; suffix success is
not complete Design, Candidate, Judge, Registry, Direct E2E, Repair, Expand or
Consumer/SFT/RL.

