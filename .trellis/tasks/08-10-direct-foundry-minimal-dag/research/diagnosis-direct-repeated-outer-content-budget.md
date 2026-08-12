# Diagnosis — declared two-correction Direct node stops after one format Feedback

- Date: 2026-08-12
- Run: `run_6df6b3046ae64983847f44621ac81a1c`
- Coordinate: `design/tool_semantics[manage_maintenance]`
- Terminal: `direct_response_not_json`, rejected, not published

## Expected behavior

The product target remains a natural-language request compiled into an
executable Candidate, independently judged and published as an immutable
`EnvironmentPackage`. A Direct node that explicitly declares two local
corrections may make at most three proposals. Each correction is a new user
turn over the same frozen task and complete contract; framework validation,
budget admission, Artifact commit and release remain authoritative. There is
no fourth proposal and no raw rejected-output persistence.

This expectation incorporates the user's later clarification that stochastic
LLM/Agent work should receive two or three bounded attempts when actionable
Feedback can help it self-revise. The existing source paragraph that permits
only one format Feedback is therefore stale product guidance, not authority to
silently discard the declared second correction.

## Time-ordered role-play trace

1. The public cleanroom run passed ResearchPlan, ResearchAcquire,
   ResearchSynthesis, WorldArchitecture, SharedToolSemantics and five
   ToolSemantics shards. No forbidden legacy authority participated.
2. Luna proposal 1 for `manage_maintenance` completed with
   `finish_reason=stop`; usage was 6,397 input and 2,366 output tokens. Strict
   parsing classified only the safe root condition `outer_content`.
3. The same Direct conversation received the previous ephemeral assistant
   answer and an actionable user Feedback turn: replace the whole answer with
   one JSON object; delete prose, labels, fences and second values; start/end
   with braces; self-check the complete contract.
4. Luna proposal 2 completed with 7,931 input and 1,467 output tokens but was
   again classified as root `outer_content`. The raw answer was correctly not
   persisted, so its exact private characters remain unknown.
5. `GraphRunner._eligible_local_correction` then rejected another Feedback
   solely because both corrections had code `direct_response_not_json`, even
   though this node declares `local_corrections=2`. It committed a failed
   WorkRecord and blocking Finding; Candidate, Judge and Registry never ran.

The first deviation under the clarified product expectation is step 5: the
control plane discarded an already-declared bounded correction. The first
model format failure is recoverable stochastic output, and the second is the
input to that remaining correction; neither grants release or weakens parsing.

## Five lenses

1. **Project Agent view — supported.** Observe names the failed shard, both
   attempts, operation usage, Finding and non-release.
2. **Effective Prompt/input — supported but intentionally non-minimal.** The
   model saw one tool surface, 106 frozen semantic bindings, one shared
   contract and the citation catalog. The first call used 6.4k input tokens;
   five siblings passed and both failed answers stopped normally, so input
   size is not the evidenced format cause. Projection slimming could alter
   cross-tool rule meaning and is not part of this repair.
3. **Direct no-Skill — supported.** Both operations used Luna through the
   official OpenAI SDK with `skill_digest=null`, no tools or workspace.
4. **Code/execution — weakened.** `response_format=json_object` and strict
   local parsing worked fail-closed, but the graph's format-specific branch
   overrides the node's declared second correction.
5. **Feedback/observability — supported.** The safe condition and concrete
   replacement/deletion action reached proposal 2. The missing event is not a
   better diagnosis string; it is admission of the remaining bounded turn.

## Break-loop classification

- **Category:** B/E — cross-layer retry contract plus a stale implicit
  assumption that repeated format classification can never benefit from one
  more stochastic self-revision.
- **Why the previous repair was insufficient:** it made the first Feedback
  actionable and proved one two-call success, but preserved a source/code rule
  that silently narrows `local_corrections=2` for format failures.
- **Homologous scope:** only Direct nodes already declaring two local
  corrections. Default one-correction nodes and Agent/provider/transport
  retry stay unchanged.
- **Prevention:** tests must equate the declared correction count with admitted
  user Feedback turns and prove the hard no-fourth-call ceiling.

## Alternatives rejected

- Do not relax or scrape the strict JSON parser.
- Do not add generic retries, a scheduler, another node, model fallback or new
  configuration.
- Do not split ToolSemantics or prune its cross-tool binding projection during
  this causal repair; those changes alter semantic consumers and are not
  supported by this terminal.
- Do not add dynamic JSON-schema generation merely to mask one provider/model
  format miss; the existing SDK JSON mode remains in place.

## Smallest next proof

Revise the stale source/design sentence and make the existing
`local_corrections=2` declaration admit a second Feedback after format-first
progress: either another format replacement attempt or a newly parsed,
precisely located semantic repair. This yields at most three total proposals
and never a fourth. A semantic-first proposal that regresses to format error
does not qualify as progress. Prove this bounded state machine
deterministically, then replay only `tool_semantics[manage_maintenance]` with
the exact parents from this run. A pass permits immediate downstream chaining;
a third failure is a new honest terminal, not permission for another retry.

Candidate, Integration, Judge, Registry, Direct E2E, Repair, Expand and
Consumer remain unproven.
