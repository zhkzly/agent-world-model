# Minimal repair plan — select Luna after Spark contract rejection

## Goal

Exercise the unchanged Direct contract with the user-authorized localhost model
selected for the observed Spark non-convergence.

## Exact implementation

1. In `config/agent-world.example.toml`, swap only the existing Direct route
   models: `gpt-5.6-luna` primary and `gpt-5.3-codex-spark` fallback. Keep the
   same localhost chat-completions URL and `OPENAI_API_KEY`.
2. Synchronize only the existing Direct route table/text in
   `docs/direct-rewrite-execution-map.zh.md` and the complete-v1 parent design.
   Agent routes remain unchanged.
3. Update the existing checked-in-example regression to assert the exact new
   order.
4. Run the deterministic quality gate, then one fresh exact
   `world_architecture` proof and read Observe. A further semantic rejection is
   a new failure, not permission to tune Prompt or increase retries.

## Explicit non-goals

No adapter, fallback-policy, correction-budget, Prompt, compiler, schema,
identifier/tool normalization, graph, Skill, stale-run, Candidate, Repair,
Expand or Consumer change.

## Acceptance

- Checked-in config and both route descriptions select Luna then Spark.
- Existing tests and provenance checks remain green.
- A fresh exact node run either commits one passing WorkRecord with Luna
  operation evidence or stops honestly with a newly observed failure.
