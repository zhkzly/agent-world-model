# Diagnosis — ToolSemantics repeats an undisclosed frozen-boundary failure

## Expected behavior

A fresh Direct run should let each `tool_semantics[tool]` Direct LLM propose the
node's disclosed closed output, let framework compile it against the frozen
tool boundary, and either commit the semantic Artifact or stop with precise
safe evidence. No failed prefix may publish a package.

## Observed chronology

1. Fresh CLI run `run_b644e7e8c9134f099351a80ebd43ded7` started from an
   unfixed bicycle-repair-shop need.
2. Real `research_plan` Agent, Search/Fetch acquisition, `research_synthesis`
   Agent, `world_architecture`, `shared_tool_semantics`, and the
   `create_repair_order` tool shard all committed passed WorkRecords.
3. The first Luna proposal for `tool_semantics[manage_parts]` failed at
   `$.arguments[3]`: the compiler required bounded nonempty text. Framework
   supplied the one allowed exact correction packet.
4. The second Luna proposal failed at the same path and condition. Framework
   committed both attempt records, both operation-usage records, a validation
   failure and a blocking Finding, then terminated `rejected` with
   `release=not_published`.
5. Observe exposes the complete safe chronology and no release. There is no
   transport, credential, research, Agent-Skill, Candidate or Judge failure.

## Attribution

The model-facing shape says only:

```text
{"description":str,"arguments":list[str],"result_fields":list[str],"success_result":object}
```

The compiler additionally requires the ordered `arguments` and
`result_fields` to exactly echo `input.tool`, bounds every item, and requires
`success_result` to have exactly the frozen result-field keys with finite JSON
scalar values. Those conditions are not disclosed in the output contract.
The same validator frontier after correction therefore indicates an
output-contract/framework defect, not a reason to add retries or blame Luna.

## Cross-layer concern

The current implementation compiles this node to an echo-oriented `ToolDraft`
and discards `success_result`. The binding task design instead describes
`tool_semantics` as the per-tool producer of minimal precondition, transition,
postcondition and error semantics. A shape-only repair would make the current
compiler easier to satisfy but might preserve a semantically redundant node
that is too weak for CandidateBuild, Judge and future Expand. This discrepancy
must be decided by the cross-layer critic before implementation; it must not be
silently deferred until a later node fails.

## Rejected actions

- Do not rerun the failed E2E or add a third attempt.
- Do not relax exact boundary validation, normalize malformed model output, or
  switch model/route from this evidence.
- Do not modify downstream nodes, add a generic schema/prompt framework, or
  implement Repair/Expand inside this Direct failure.

## Next gate

Review the exact minimal disclosure plan against the canonical product goal,
the declared node purpose and every downstream consumer. `allow` permits only
that plan. `block` must say whether the minimum coherent repair instead needs a
small semantic ToolSemantics contract change and name its exact affected
consumers and tests.
