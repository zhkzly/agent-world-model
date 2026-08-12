# Plan — disclose the expected closed-object fields in Feedback

## Goal

Make one existing compiler rejection actionable to the same Direct LLM without
changing what any node accepts, how many proposals it may make, or what any
downstream consumer receives.

## Minimal implementation

1. In `agent_world/design.py`, change only `_object`'s existing
   `violated_condition` so it includes the sorted, framework-owned `keys`
   supplied by the caller: `object must contain exactly these fields and no
   others: <sorted names>`.
2. Do not include actual proposal keys or values. Do not change `_object`'s
   return type, field-set comparison, error code, path or expected category.
3. In `tests/test_design_semantics.py`, update the two existing exact Feedback
   assertions affected by this wording and add/extend one Curriculum assertion
   for the seven expected family fields.

## Preserved boundaries

- Direct remains official OpenAI SDK JSON mode with no Skill/tool/workspace.
- GraphRunner's correction admission is unchanged: repeated conditions stop,
  strict A-to-B progress alone may reach proposal 3, and no proposal 4 exists.
- Prompt, input projections, output shapes, model/profile/routes, contracts,
  Artifact schemas, graph nodes/edges, Candidate, Judge and Registry are
  unchanged.
- No raw Provider output, actual unknown field name, credential or endpoint is
  persisted in Feedback or Observe.

## Tests and proof

1. Focused: `uv run pytest -q tests/test_design_semantics.py
   tests/test_graph_contracts.py`.
2. Quality: Ruff format/check, mypy, compileall, legacy firewall, then serial
   full pytest.
3. Independent implementation check against this exact plan.
4. One true proof: replay only `design/curriculum_plan` with the exact three
   frozen parent Artifacts from
   `run_fb7f87b4307346b3ae2e6843b27f650a`, using `gpt-5.6-luna`. Read Observe
   immediately. Only a committed Curriculum permits a fresh public E2E.

## Acceptance

- The same malformed object still fails at the same path/code/category.
- Feedback contains the complete sorted expected field list and no actual
  proposal key/value disclosure.
- No correction ceiling, accepted semantic object or downstream ABI changes.
- The live leaf either commits within the existing ceiling or stops honestly
  with no release and no blind retry.
