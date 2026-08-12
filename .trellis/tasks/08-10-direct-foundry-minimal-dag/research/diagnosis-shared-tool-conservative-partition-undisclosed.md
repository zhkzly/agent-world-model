# Diagnosis — SharedTool conservative partition is not disclosed

- Date: 2026-08-12
- Real run: `run_13b48bda4cde4498a95c0a7e0d402f6a`
- Boundary: `design/shared_tool_semantics[1-2-3-4-5-6-7]`
- Owner/kind: `designer` / `direct_llm`
- Model: `gpt-5.6-luna`; two completed calls, no fallback

## Expected product behavior

The natural-language request must advance through an evidence-grounded Design
to executable Candidate, isolated Judge and immutable Registry package. At this
boundary Luna proposes only compact shared business semantics. Framework owns
the frozen ordered tool group, exact partition validation, correction bound,
compiled contract/digest, Work/Artifact facts and every release decision.
There is no Runtime Skill, tool or workspace because this is a Direct LLM node,
not an Agent node.

The source of truth requires the Prompt to disclose that each shared dimension
partitions the exact ordered group and that, absent evidence for a finer split,
one domain containing the whole ordered group is a conservative valid result.

## Observed chronology

1. The diagnostic used the exact immutable Evidence and WorldArchitecture
   bytes from failed public run `run_1bec958e41ae4207beb4a7b40149f9c0`.
2. The first Luna operation completed, then framework rejected
   `$.atomicity`: `domains must partition the derived group`.
3. The second Luna operation received that bounded correction and completed,
   but failed the same path and condition.
4. Observe reports one failed Direct Work, one blocking Finding, no SharedTool
   or ToolSemantics output, and `release=not_published`.

Safe evidence is under
`config/.agent-world-runs/runs/run_13b48bda4cde4498a95c0a7e0d402f6a/`.
Provider text was neither persisted nor used as release evidence.

## Layer attribution

- **Role:** correct. This remains a bounded Direct semantic draft; converting
  it to Agent would add irrelevant Skill/tool/workspace authority.
- **Input:** correct and immutable. The exact group `[1..7]`, tool surfaces and
  citation catalog were visible.
- **Recipient contract/feedback:** causal defect. The current output shape says
  only “arrays ... partitioning every member exactly once”; it omits the
  source-of-truth conservative whole-group construction. The correction repeats
  the abstract invariant but gives no executable safe construction.
- **Compiler:** correct. It rejects non-integer, duplicate, missing, overlapping
  or unknown members and does not silently repair semantic output.
- **Transport/model:** healthy. Both Luna calls returned parseable JSON within
  the normal token/time bounds. No evidence points to endpoint compatibility.
- **Observe:** sufficient. It exposes model, attempts, exact safe path/category,
  immutable dependencies, failed Work/Finding and non-publication.

## Causal hypothesis and smallest repair

The Direct recipient contract under-discloses a canonical valid partition, so
the model must infer a mechanically fragile nested permutation. Add the missing
source-of-truth instruction to the existing SharedTool output shape and its
existing local correction condition: use the exact input `tool_indexes`, each
exactly once, and use one domain containing the complete ordered group unless
evidence requires a finer partition. Keep the output fields, compiler,
`SharedToolContract`, graph, call count and one-correction/two-call bound
unchanged.

This does **not** hardcode business semantics: Luna may still choose a finer
semantic partition and still owns ordering, compensation and policy text.
Framework continues to hardcode only coordinates, admissibility and the safe
conservative construction. No Agent, Skill, retry increase, schema engine or
downstream compatibility path is needed.

## Falsifiable proof

With the same immutable parents and Luna route, SharedTool must commit within
the existing two-call bound, then the harness may invoke only
`tool_semantics[register_member]` and stop before the second tool. This proves
only the repaired suffix. It does not prove complete Design, Candidate, Judge,
Registry, Direct E2E, Repair, Expand or Consumer/SFT/RL.

