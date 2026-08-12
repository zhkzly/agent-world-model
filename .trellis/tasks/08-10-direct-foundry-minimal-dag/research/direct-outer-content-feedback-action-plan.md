# Plan — make Direct format Feedback an executable deletion instruction

## Goal

Turn the already-safe Direct format condition into a concrete next-user action
without changing parser acceptance, Provider mode, retry count or any compiled
Artifact.

## Minimal implementation

1. In `agent_world/design.py`, change only the
   `direct_response_not_json` repair sentence in `_direct_feedback` to require
   replacing the whole previous answer with one parseable JSON object, removing
   all prose, labels, Markdown fences and second JSON values, with `{` and `}`
   as the first/last non-whitespace characters.
2. Retain the original frozen user task, previous ephemeral assistant answer,
   safe path/condition/category, complete-replacement instruction and whole
   self-check. Persist no rejected content.
3. In `tests/test_design_semantics.py`, update the existing exact conversation
   assertion and add/retain proof that the raw answer is absent from Feedback
   and durable files. Keep the two-format-call terminal test unchanged.
4. Add one concise sentence to
   `.trellis/spec/guides/agent-llm-node-debugging.md`: a safe parser subtype is
   not actionable by itself; Feedback must translate it into the concrete
   replacement/deletion operation available to its recipient.

## Explicit non-scope

- No SDK/`response_format` change, JSON-schema generation or capability layer.
- No parser extraction, fence stripping, prose scraping or validator weakening.
- No third format call, model fallback, node split, new helper/service, Prompt
  rewrite, input projection, route/model/config, graph edge or downstream ABI.
- No raw model content, Provider body, credential or endpoint persistence.

## Checks and real proof

1. Focused Direct/Feedback and GraphRunner tests.
2. Ruff format/check, mypy, compileall, legacy firewall and serial full pytest.
3. Independent implementation review.
4. Replay only `tool_semantics[manage_equipment]` with exact frozen
   WorldArchitecture `design.world_architecture:043ca6b897fa942b`,
   SharedToolSemantics `design.shared_tool_semantics:18bb5ca5153f4cf5`, and
   EvidenceGraph `design.evidence_graph:93350b0a55675b06` from the failed run.
   Read Observe immediately. Only a committed leaf permits a new public E2E.

## Acceptance and non-claims

The format Feedback must specify the concrete deletion/replacement operation,
while strict parsing, secrecy and the two-call ceiling remain unchanged. A
passed leaf proves only this correction boundary; it does not prove downstream
Design, Candidate, Judge, Registry, E2E, Repair, Expand or Consumer.
