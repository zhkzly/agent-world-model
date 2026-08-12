# Deterministic results — bounded second Direct format Feedback

- Date: 2026-08-12
- Plan digest:
  `85541065b75f17ec5509bb7cc7be2d61173365a7a58c414122f765e3345483a8`
- Status: passed

## Changed behavior

Only the existing ordinal-two `GraphRunner` eligibility changed. A Direct node
already declaring two local corrections now admits the final bounded Feedback
after a format-first path. Format-to-format and format-to-semantic may reach
proposal three; semantic-to-format remains terminal; proposal three never
authorizes proposal four. Default one-correction nodes are unchanged.

The official SDK JSON mode, strict parser, actionable Feedback renderer,
ephemeral previous-answer handling, model/routes, Node declarations, graph and
Artifact/downstream contracts are unchanged.

## Results

- Targeted state-machine and conversation tests: `13 passed`.
- Full Design/Graph focused tests: `115 passed`.
- Full serial test suite: `251 passed`.
- Ruff format check and Ruff check: passed (`22 files already formatted`).
- mypy: passed (`13 source files`).
- compileall: passed.
- legacy firewall: `2 passed`.

Tests cover both `tool_semantics` and `curriculum_plan`, repeated format success
and terminal paths, format-to-semantic progress, semantic-to-format regression,
the hard three-proposal ceiling, immediately preceding ephemeral assistant
answers, actionable Feedback, and rejected-content non-persistence.

## Non-claims

These checks prove only deterministic admission, feedback framing and terminal
behavior. They do not prove Luna will repair the frozen shard or establish
complete Design, Candidate, Integration, Judge, Registry, E2E, bounded Repair,
Expand or Consumer.
