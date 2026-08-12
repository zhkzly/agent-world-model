# Research: context-feedback-synthesis-independent-audit

- Query: Independent read-only audit of the revised feedback doctrine and debugging guide against the product contract, execution map, and the three task-local deep-research records.
- Scope: internal
- Date: 2026-08-12
- Decision: allow

## Findings

The documents correctly state the requested **logical** Feedback semantics: it
is a framework-authored next `user` wish in the same node conversation, retains
the rejected result only as an untrusted ephemeral `assistant` turn, preserves
the frozen task/contract, and asks for one complete replacement
(`research/prompt-feedback-observe-retry-principles.md:13-21, 76-96`;
`spec/guides/agent-llm-node-debugging.md:12-41`).  They also correctly keep
the framework as the sole validator, retry, routing, budget, Artifact, Judge,
and release owner, as required by the canonical document
(`docs/agent-world-environment-generation.zh.md:241-273, 376-445`).

The Prompt/Skill/tool-observation/Artifact/Observe/OpenViking boundaries are
otherwise sound.  In particular, Direct has no Skill/tools/workspace;
tool-enabled Agents have one mounted Skill; tool results remain loop-local
observations; Artifacts contain validated typed facts; Observe is a safe
read-only projection; and OpenViking is explicitly development memory rather
than a runtime subsystem or Direct prompt input
(`research/prompt-feedback-observe-retry-principles.md:44-64, 172-210`;
`docs/direct-rewrite-execution-map.zh.md:22-24, 53-60, 102-115`).  The four
loops are also correctly separated: tool continuation, node-local correction,
transport replay, and workflow Repair (`research/prompt-feedback-observe-retry-principles.md:125-155`;
`docs/agent-world-environment-generation.zh.md:391-403, 799-853`).

The root/non-JSON conflict is honestly isolated.  The revised doctrine says
the proposed one-turn root-format alternative is inactive and requires a
separate diagnosis/plan/SDK predicate/test/real-node proof
(`research/prompt-feedback-observe-retry-principles.md:156-170`).  That
matches the currently binding rule that generic root errors do not consume a
semantic correction (`docs/agent-world-environment-generation.zh.md:421-426`).

The original block was limited to two documentation ambiguities that could otherwise
change the effective runtime boundary:

1. **Logical roles versus the Direct transport are not explicitly reconciled.**
   The doctrine depicts a `developer` turn and a same-conversation continuation
   (`research/prompt-feedback-observe-retry-principles.md:68-90`), while the
   canonical Direct contract permits only `model + rendered Prompt/input +
   authorized correction feedback`, forbids profile-owned/developer
   instruction and outbound Provider `instructions`, and makes the rendered
   Prompt the complete Direct work instruction
   (`docs/agent-world-environment-generation.zh.md:504-513`;
   `spec/guides/agent-llm-node-debugging.md:53-60`).  The text must say that
   these are logical conversation roles.  For Direct, they must be rendered
   through the permitted Direct input surface; for an Agent, logical continuity
   must not imply undeclared reuse of SDK session, workspace state, or provider
   retention.  Any carried tool result remains typed observation data under its
   normal authorized tool-loop contract, not feedback or control state.

2. **The most relevant external/self-correction counterexample is not named
   where the assistant turn is retained.**  The task-local research deliberately
   recommended omitting raw prior output by default because malformed output,
   prompt-injection-like content, anchoring, duplicate history, and hidden
   continuation can make retention unsafe or unhelpful
   (`research/prompt-feedback-deep-research.md:202-247`;
   `research/context-engineering-deep-research.md:9-22, 148-155`).  The revised
   doctrine cites external-feedback evidence and marks the result untrusted,
   but does not state that the user-defined retained assistant turn is a narrow,
   unproven exception to that default.  Without that statement, an implementer
   can mistake the literature for support for unconditional raw-output
   retention.  This is distinct from the useful finding that externally grounded
   validator feedback is preferable to intrinsic self-correction
   (`research/prompt-feedback-deep-research.md:106-129, 131-173`).

The documents do not otherwise overdesign the change: they expressly reject a
context manager, feedback service, new node, generic RAG, memory hierarchy, or
unbounded retry controller (`research/prompt-feedback-observe-retry-principles.md:191-210`).

## Minimal Necessary Modifications

1. Add one shared clarification (or identical concise wording in both files):
   “same conversation” means the one logical role sequence
   `initial user -> rejected ephemeral assistant -> Feedback user`; it is not
   authorization for a Direct Provider `instructions`/developer field,
   undeclared hidden server-side continuation, reused Agent workspace state, or
   durable transcript storage.  A stateless route reconstructs only the
   approved logical turns through its existing permitted input surface; any
   carried tool result stays a typed tool observation rather than feedback.
2. Next to the retained-assistant-turn rule, add one explicit caveat: this is a
   deliberate, bounded user requirement that differs from the deep-research
   default of omitting raw prior output.  Retain only the one final rejected
   assistant proposal as untrusted data for that correction, never duplicate it
   in Feedback or durable storage, use exactly one declared continuation method,
   and make no efficacy claim until the later approved boundary proof.  Tool
   observations remain governed by their separate typed loop contract.

## Files Found

- `research/prompt-feedback-observe-retry-principles.md` — revised doctrine under review.
- `spec/guides/agent-llm-node-debugging.md` — revised debugging guidance under review.
- `AGENTS.md` — source-of-truth and authority precedence.
- `docs/agent-world-environment-generation.zh.md` — canonical control, Direct, Repair, and Observe contract.
- `docs/direct-rewrite-execution-map.zh.md` — derived execution-boundary map.
- `research/context-engineering-deep-research.md` — context lifecycle and retention counterevidence.
- `research/prompt-feedback-deep-research.md` — external-feedback/self-correction and turn-matrix evidence.
- `research/skills-tools-memory-deep-research.md` — Skill/tool/memory lifetime boundaries.

## External References

No new external lookup was performed.  The audit relied on the primary and
official references already recorded in the three deep-research files,
including Self-Refine, Reflexion, CRITIC, ReAct, the OpenAI Model Spec/Structured
Outputs guidance, and Anthropic evaluator-optimizer/context guidance.

## Related Specs

- `docs/agent-world-environment-generation.zh.md:241-445, 504-513, 631-642, 799-853, 1040-1067`
- `docs/direct-rewrite-execution-map.zh.md:22-24, 53-60, 102-115`
- `.trellis/spec/guides/agent-llm-node-debugging.md:12-65`

## Caveats / Not Found

- This was a document-only review.  No implementation source, historical JSONL,
  provider, Agent SDK, tool, provider call, or E2E run was read or executed.
- The requested user definition can be adopted as a product contract; this
  review does not claim that retained rejected output improves correction
  quality.  After the two wording fixes, the next permitted gate is a fresh
  read-only review of the revised documents, not implementation or a live run.

## Re-review — 2026-08-12

Decision: allow.

The two original conditions are now complete in both reviewed files.  The
doctrine and guide define the role sequence as logical only; Direct keeps its
existing Prompt/input-only surface, and Agent continuation cannot silently
reuse a workspace/session or provider state
(`research/prompt-feedback-observe-retry-principles.md:68-73`;
`spec/guides/agent-llm-node-debugging.md:30-35`).  Both also identify the
single rejected assistant proposal as a bounded user-required exception to the
safer omission default, prohibit duplication/persistence, require one declared
continuation method, retain tool observations in their separate loop, and make
no efficacy claim before a real-boundary proof
(`research/prompt-feedback-observe-retry-principles.md:101-111`;
`spec/guides/agent-llm-node-debugging.md:23-35`).

This allow is limited to resolving those two documentation conditions.  It does
not activate the root/non-JSON alternative or establish runtime behavior,
provider compatibility, or product completion.
