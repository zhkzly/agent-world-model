# Diagnosis — closed-object field-set Feedback is not actionable enough

- Date: 2026-08-12
- Run: `run_16b5772c5d2c45d787ec3057b4b3a96c`
- Terminal: `curriculum_plan_invalid`
- Boundary: Direct `gpt-5.6-luna` -> `_object` compiler -> next-user Feedback

## Expected behavior

For a parsed object with the wrong closed field set, the framework rejects the
proposal and gives the same Direct node enough safe, deterministic information
to produce a complete replacement. The model keeps its original frozen input,
complete output shape and immediately preceding complete proposal. The
framework—not the model—owns validation, correction admission and commit.

## Chronology and recipient view

1. The diagnostic harness cold-read the exact WorldArchitecture, WorldRules
   and EvidenceGraph parents from the prior public run. No legacy authority was
   loaded.
2. Luna saw the Curriculum input, the complete output shape and no Skill,
   tools, workspace or release instructions. Proposal 1 was valid JSON.
3. `_object` observed that `$.families[0]` did not have exactly the seven
   framework-declared fields. It knew the expected field names but collapsed
   that knowledge to `object must use exactly the declared fields`.
4. Luna then saw its complete previous proposal and a user Feedback turn with
   the exact path, the generic condition and a request for a complete
   replacement. The Feedback did not repeat the expected field names.
5. Proposal 2 was valid JSON but failed the identical path and condition. The
   actual missing/extra keys are intentionally unavailable because raw model
   output is ephemeral and not persisted.
6. GraphRunner correctly detected an identical correction tuple, stopped after
   proposal 2 and committed no Curriculum or release.

The first supported causal deviation is step 3: the deterministic validator
discarded safe contract information needed by the correction recipient. The
runner's no-progress stop is expected behavior, not the cause.

## Five lenses

1. **Project Agent view — supported.** Observe identifies the failed node,
   WorkRecord, two attempt refs, operation refs, Finding and no release.
2. **Effective Prompt/input — supported.** The output shape already lists the
   family fields; both calls completed with 10,945 and 13,867 total tokens, so
   no truncation or capacity fact is observed.
3. **Direct no-Skill invariant — supported.** Both operation records are
   `direct_llm`, model `gpt-5.6-luna`, `skill_digest=null`.
4. **Code/execution boundary — supported.** Official SDK JSON mode returned two
   parsed objects; strict compiler and no-progress admission behaved as coded.
5. **Feedback/observability — weakened.** The recipient gets an exact path but
   not the safe expected field set that `_object` already owns. The actual
   proposal field difference remains unknown and need not be persisted.

## Homologous-surface audit

All closed-object validation in the Direct design compiler uses the same
`_object(value, keys, code, path)` helper. Every call therefore loses the same
safe expected-key information. One helper-level wording change is smaller and
more consistent than Curriculum-only branches; validation acceptance and every
compiled Artifact remain unchanged.

## Smallest coherent repair

Render the sorted framework-owned expected field names in `_object`'s existing
condition, for example: `object must contain exactly these fields and no
others: actor_index, ...`. Do not persist or echo actual unknown keys or
values. Do not change Prompt shape, input projection, parser, schema, model,
route, correction budgets, graph edges, node split or downstream ABI.

Update only exact Feedback assertions and add a Curriculum regression proving
the condition contains the complete expected family field set. Then replay the
same frozen-parent Curriculum leaf once. A new terminal starts a new diagnosis;
there is no blind rerun.

## Rejected strategies and unknowns

- No extra retry: proposal 3 must remain gated by strict progress.
- No node split or output reduction: neither call showed truncation or
  Provider failure.
- No raw-output persistence: actual extra/missing keys remain intentionally
  unknown.
- No model switch: Luna followed the transport/JSON contract; the recipient
  instruction is the evidenced weak surface.

TaskRequirement, ModelingGate, Candidate, Integration, Judge, Registry, E2E,
Repair, Expand/multi-parent and Consumer/SFT/RL remain unproven.
