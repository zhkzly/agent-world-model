# Plan — honor the declared second Direct format correction

## Goal

Align the existing two-correction Direct node declaration with the user's
bounded self-revision requirement: at most two actionable Feedback turns and
three total proposals, with strict parsing and no fourth call.

## Minimal implementation

1. In the canonical source paragraph and Direct task feedback section, replace
   the stale one-format-correction exception with the bounded rule above.
   Default nodes still have one correction; only Direct nodes explicitly
   declaring two receive the second Feedback after a format-first path.
2. In `GraphRunner._eligible_local_correction`, preserve every existing
   eligibility condition and semantic strict-progress rule, but allow ordinal
   two when the previous correction was `direct_response_not_json` and the
   current safe rejection is either another `direct_response_not_json` or a
   newly parsed, precisely located semantic issue. Preserve the terminal rule
   when a semantic-first proposal regresses to format. The loop's existing
   bound remains authoritative.
3. Update focused graph/design tests to prove:
   - format -> format and format -> semantic paths receive two next-user
     Feedback turns;
   - semantic -> format remains terminal after two proposals;
   - each turn uses the immediately preceding ephemeral assistant answer and
     the concrete replacement/deletion instruction;
   - a successful third proposal commits normally;
   - a third format failure stops with no fourth invocation;
   - default one-correction nodes, semantic progress rules, raw-output secrecy,
     parser strictness and provider retry behavior are unchanged.
4. Add one concise sentence to the existing debugging guide: an explicitly
   budgeted second format correction is still bounded self-revision, not
   permission for unbounded retry.

## Compatibility chain

- **Producer:** Luna returns ephemeral content; unchanged.
- **Changed handoff:** GraphRunner may authorize one additional user Feedback
  turn only inside the same uncommitted Direct node transaction.
- **Immediate consumer:** the same Direct node receives the same frozen input,
  complete output contract and immediately preceding answer; unchanged schema.
- **Downstream:** compiler, Artifact envelope, WorkRecord, Design consumers,
  CandidateGraph, Judge, Registry and Observe contracts are unchanged because
  only a successfully compiled complete replacement can commit.
- **Owners:** framework still owns admission, count, validation and release;
  the model owns only semantic proposal content.

## Explicit non-scope

- No parser weakening/extraction, Prompt or output-shape redesign.
- No input projection slimming, ToolSemantics split, node/edge addition or ABI
  change.
- No SDK response-mode, model, route, fallback or configuration change.
- No general retry facility, cross-node Repair behavior, Expand or Consumer
  implementation.

## Checks and true-boundary proof

1. Focused GraphRunner and Direct Feedback tests.
2. Full serial pytest, Ruff format/check, mypy, compileall and legacy firewall.
3. Independent whole-scope implementation check.
4. Exact-parent real Luna replay of
   `tool_semantics[manage_maintenance]` from
   `run_6df6b3046ae64983847f44621ac81a1c`; read Observe immediately. It must
   either commit within at most three proposals or fail honestly after exactly
   three. Only a commit permits a fresh public E2E.

## Non-claims

Deterministic green checks prove only retry admission. A passed frozen leaf
does not prove Candidate, Judge, Registry, E2E, Repair, Expand or Consumer.
