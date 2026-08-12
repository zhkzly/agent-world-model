# Diagnosis — Direct outer-content Feedback describes but does not direct

- Date: 2026-08-12
- Run: `run_804e6cc894674e69b7ea72d0714c8daa`
- Coordinate: `design/tool_semantics[manage_equipment]`
- Terminal: `direct_response_not_json`, rejected, not published

## Expected behavior

A completed Direct answer that is not exactly one JSON object may receive one
next-user format correction. That message must tell the same LLM what concrete
change to make to its previous answer, request one complete replacement and
retain strict whole-object validation. Framework owns the call ceiling and
must stop a second format failure without release.

## Chronology and recipient view

1. The fresh public cleanroom run passed all three Research nodes,
   WorldArchitecture, SharedToolSemantics and the first ToolSemantics shard.
2. Luna call 1 for `manage_equipment` used 5,974 input and 1,343 output tokens.
   It completed, but strict parsing classified its ephemeral content as one
   object with outer content or extra JSON data.
3. Framework sent the same frozen task plus the previous ephemeral assistant
   answer and a user Feedback turn. The safe issue said `path $`, condition
   `response has non-JSON leading or trailing content, or extra JSON data`, and
   expected `object`.
4. The requested action nevertheless remained generic: `Change the response
   at that path so it satisfies the condition and expected category`, followed
   by the general complete-object/self-check sentence.
5. Luna call 2 used 6,117 input and 2,547 output tokens and repeated the same
   safe outer-content condition.
6. GraphRunner correctly stopped after two format calls, committed no
   ToolSemantics, produced one blocking Finding and kept Registry closed.

No raw model content is persisted, so whether the outer characters were prose,
a label, a fence or a second JSON value remains intentionally unknown. The safe
condition is sufficient to request deletion of all such alternatives.

## Five lenses

1. **Project Agent view — supported.** Observe names the shard, two attempts,
   operation usage, failed Work/Finding and non-release.
2. **Effective Prompt/input — supported for delivery.** The original shape and
   correction were sent; both calls finished and were far below any observed
   truncation boundary.
3. **Direct no-Skill — supported.** Both operation records are Direct Luna with
   `skill_digest=null`.
4. **Code/execution — supported.** Official SDK passed
   `response_format=json_object`; the OpenAI-compatible local route returned
   content that strict local parsing rejected. Parser rejection and stop policy
   behaved as designed.
5. **Feedback/observability — weakened.** The subtype is precise, but its action
   is a generic path repair at root rather than an explicit deletion/replacement
   instruction. The recipient can identify the defect but is not directly told
   how to transform the prior answer.

## Break-loop analysis

- **Category:** B/E — cross-layer contract and implicit Provider assumption.
- **Why the prior repair was incomplete:** it made the format subtype safely
  observable but treated subtype text itself as actionable Feedback. The live
  route has now repeated the same pattern on a second ToolSemantics shard.
- **Systematic scope:** every Direct format correction uses one shared renderer;
  one renderer sentence is coherent. No node-specific branch is needed.
- **Prevention:** exact tests must assert a recipient action, not merely an
  error condition; the frozen failing leaf must be run before another E2E.

## Causal hypothesis and alternatives

The first evidenced repairable deviation is the format-specific action text.
The local compatible Provider may also enforce `json_object` imperfectly, but
that does not justify parser extraction or a schema framework. If a precise
deletion instruction still repeats on the frozen leaf, structured-output
capability becomes the next hypothesis; it is not changed pre-emptively.

## Smallest repair and proof

In the existing `direct_response_not_json` branch, replace only the generic
path action with an explicit complete-answer operation: remove all prose,
labels, Markdown fences and second JSON values; make the first non-whitespace
character `{`, the last `}`, and ensure the whole answer parses as one object.
Keep the safe condition, original input, previous ephemeral answer,
complete-replacement/self-check wording, strict parser and two-call format
ceiling.

Prove exact text and secrecy deterministically, then replay only the frozen
`manage_equipment` leaf. No SDK response mode, Prompt shape, model, route,
parser acceptance, node, edge, retry budget or downstream ABI changes.

TaskRequirement, Candidate, Judge, Registry, E2E, Repair, Expand and Consumer
remain unproven.
