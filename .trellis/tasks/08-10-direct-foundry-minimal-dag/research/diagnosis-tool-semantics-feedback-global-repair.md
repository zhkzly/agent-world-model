# Diagnosis — ToolSemantics Feedback repairs one path, not the whole condition

- Date: 2026-08-12
- Real run: `run_9916d45626bf4ab3b11535c96fe50aa1`
- Coordinate: `design/tool_semantics[reserve_tool]`
- Terminal: `tool_semantics_invalid`, rejected, not published

## Expected behavior

Feedback is the next useful user instruction to the same model. An exact path
identifies one observed violation, but the complete replacement must satisfy
the same condition everywhere. The model should repair all relevant
occurrences and self-check the whole object within the existing three-proposal
ToolSemantics ceiling. The product target remains natural-language need ->
executable environment -> independent Judge -> Registry package.

## Observed chronology

1. The exact frozen parents and Luna Direct route produced a parsed JSON object.
2. Attempt one failed at `$.preconditions[2].when` because the array violated
   its declared cardinality. The next user Feedback carried this safe issue.
3. Attempt two no longer had that issue. It failed at
   `$.transitions[3].effects[2].value` because an effect value was neither
   finite JSON nor a frozen binding reference. The next user Feedback carried
   this different safe issue.
4. Attempt three no longer failed at that path, but stopped on the same
   condition at `$.transitions[4].effects[2].value`.
5. Framework correctly stopped after three proposals, persisted only safe
   packet/operation facts, and published nothing.

The rejected proposals are intentionally unavailable. Therefore it is unknown
whether the third issue already existed in attempt two or was introduced by
the complete regeneration. This diagnosis does not claim fail-fast validation
hid a known second issue.

## Five-lens attribution

1. **Project Agent view — supported.** Observe names exact attempts, paths,
   conditions, model usage, Work and non-release.
2. **Effective Prompt/input — weakened at Feedback wording.** The original
   RuleDraft shape already applies to every effect and asks for whole-object
   self-check, but `_direct_feedback` explicitly says “Change the response at
   that path,” which makes a point edit a reasonable interpretation.
3. **Direct no-Skill — supported.** All three operations are Direct Luna with
   no Skill/tool/workspace.
4. **Code/execution — supported for safety, weakened for diagnostic precision.**
   The compiler gives an exact path but describes the effect-value alternatives
   compactly; it does not explicitly tell the recipient that literal values are
   written directly while only semantic references use an object wrapper.
5. **Feedback/observability — supported for strict progress, insufficient for
   whole-condition repair.** A disappeared, then B disappeared, but the same B
   condition recurred at C before the hard ceiling.

## Causal hypothesis and alternatives

- Primary: the recipient followed the instruction literally and repaired only
  the named occurrence. The same-condition recurrence is consistent with the
  current path-local sentence.
- Secondary: the compact effect-value alternatives remain easy to confuse with
  PredicateDraft's `{kind:"literal",value:...}` form; the generic condition may
  not tell Luna how to construct every valid effect value.
- Not established: provider capacity. All three calls completed and none was a
  format/truncation terminal. ToolSemantics already uses one tool per shard.

Do not add a fourth call, split per field, weaken the compiler, accept wrapped
values, add a generic diagnostic framework, or change model/route. The smallest
repair is recipient-facing: make the named path explicitly one observed
occurrence, require fixing every occurrence governed by the same condition in
the complete previous proposal, and phrase the existing effect-value condition
as direct literal/list versus exact semantic-reference object. Then rerun only
the exact frozen leaf.
