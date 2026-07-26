# Agent/LLM Node Debugging Loop

Use this process for every uncertain outcome from a real Agent/LLM invocation.
It applies to Design, Builder, Judge, Research, and later nodes; it is not a
WorldRules-only rule.

## 1. Read durable, safe evidence before changing anything

- Read the node's safe terminal status, `ValidationReport`, frontier, and
  `observe scene` first.
- Do not infer a cause from a model output snippet, a timeout label, a passing
  unit test, or a repeated sample.
- If the result lacks a stable code, source-facing path, violated condition,
  and expected category, classify **feedback/observability** as defective and
  repair that boundary before another semantic retry.

## 2. Make the four-way ownership decision

Ask these four questions in order. Record the evidence for the selected owner.

| Owner | Evidence | Correct next move |
|---|---|---|
| Prompt | The real node projection omits required frozen context, structural choice, or role instruction. | Fix that node's prompt projection; keep the compiler authoritative. |
| Skill | The contract/prompt are sufficient but the owning role lacks durable, reusable guidance. | Update only that role Skill. |
| Code / contract | A complete valid constructed input violates a framework-owned rule, or code asks the model to provide a mechanical/framework identity. | Refactor the deterministic ownership boundary and add a regression. |
| Feedback / observability | A proposal failure is opaque, unsafe, generic, or cannot tell an Agent what field/category to repair. | Add safe typed diagnostics and scene/frontier projection first. |

Never treat an `error` status alone as retry authority, and never turn a
framework-owned mechanic into an Agent correction merely to obtain another
turn.

## 3. Prove one real node boundary

Construct a complete valid frozen input closure (or adapt a real committed
closure), then execute the actual leaf/compiler/scheduler path for that node.
Change or poison only the suspect condition.

This is stronger than an interface-only unit test because it proves the real
node's input projection, output parsing, compiler, validation, and settlement
boundary. Ordinary pytest tests are still useful as regression guards, but are
not evidence that an Agent/LLM node works with a real provider.

## Test output is also a feedback contract

Every constructed-input or unit-level regression must emit enough safe context
for an Agent to debug it without guessing:

- exact test/node identity and owner boundary;
- the valid fixture/committed-closure provenance and the one poisoned change;
- stable code, source-facing path, violated condition, expected category, and
  expected-versus-actual terminal state;
- elapsed time plus the last completed phase/checkpoint.

A timeout or stall must additionally identify its timeout boundary and last
safe heartbeat/operation. A bare assertion, an opaque exception string, or a
test name that stops producing output is insufficient feedback: treat the
test/harness observability boundary as a code defect before using that result
to guide a semantic prompt, Skill, or contract repair.

If one local result establishes a defect pattern, inventory every
same-owner/same-boundary occurrence before returning to a live run. Do not fix
one prompt branch, discover the next identical omission, and loop.

## 4. Make one causal change, then verify in layers

1. Add a constructed input regression that fails for the original cause and
   passes after the repair.
2. Run focused deterministic tests, lint, and type checks as a supplement.
3. Run exactly one isolated real `test-node` for the same frozen coordinate.
4. Read its safe terminal scene before deciding the next action.

The next real invocation is allowed only when the change is causally different
(for example a corrected prompt/Skill, a new deterministic compiler boundary,
or repaired feedback). Never rerun an unchanged coordinate hoping for a better
sample.

## 5. Interpret the live result without overclaiming

- **Committed/passed:** this one node is proven; it does not prove downstream
  Build/Judge/Registry or release.
- **Typed semantic failure:** return to the four-way decision using its exact
  diagnostic, then isolate that exact issue.
- **Generic feedback:** repair feedback before retrying.
- **Transport/interruption/infrastructure error:** use the recovery/transport
  lane; do not mutate semantic prompts or WorldSpec without evidence.
- **No progress or oscillation:** stop and record the causal blocker rather
  than expanding retries.
