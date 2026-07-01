# Design: Direct LLM And Deep Research Node Execution

## Summary

The pipeline should stop treating deterministic `request_driven.py` functions as the upstream generation path. Selected non-IMPLEMENT stages should actually invoke LLM/research/tool-discovery execution and return structured artifact fields. Deterministic checks remain, but deterministic semantic generation should be removed from the success path.

## Target Folder Structure

Keep the structure explicit and implementation-focused. Core pipeline code, live execution code, prompts, config, and optional external research projects should not be mixed together.

```text
agent_world/
  config.py                       # parse node execution / LLM / research env config
  strategies.py                   # stage -> executor routing for this pipeline

  executors/
    __init__.py
    base.py                       # NodeExecutionResult and small executor protocol
    structured_agent.py           # S2/S3/S4/S5/S7/S8 advisory JSON artifact generation
    research_agent.py             # S1 SourceEvidenceIndex generation via research workflow

  research/
    __init__.py
    providers.py                  # local, SearXNG-compatible, process search providers
    lightweight.py                # lightweight research agent: query plan -> search -> evidence
    adapters/
      __init__.py
      open_deep_research.py       # optional adapter if external project is cloned
      manusearch.py               # optional adapter if external project is cloned

  prompts/
    knowledge_pack.md             # S2
    environment_spec.md           # S3
    logical_tool_graph.md         # S4
    task_set.md                   # S5
    verifier_plan.md              # S7
    feasibility_review.md         # S8 advisory

  skills/
    research-source-discovery/
      SKILL.md                    # S1 research workflow, provider/tool rules, output contract
    knowledge-extraction/
      SKILL.md                    # S2 extraction rules and source-grounding requirements
    tool-surface-discovery/
      SKILL.md                    # S4 MCP/CLI/API/SDK discovery and graph rules
    task-generation/
      SKILL.md                    # S5 task generation rules
    verifier-planning/
      SKILL.md                    # S7 verifier planning rules and anti-leakage constraints
    feasibility-review/
      SKILL.md                    # S8 advisory review rules

external/
  research/                       # optional local clones, not imported directly by core
    open_deep_research/           # optional git clone / submodule
    ManuSearch/                   # optional git clone / submodule
    searxng/                      # optional local service source/config
```

No `deterministic.py` executor is required for this task because deterministic artifact generation is not a fallback requirement. Small deterministic helpers may remain where they perform validation, normalization, IDs, hashes, or framework decisions.

`external/research/` is optional. The first implementation may use only the lightweight in-repo research agent. If an open-source project is cloned for reference or adapter integration, the adapter under `agent_world/research/adapters/` should be the only code that knows its layout.

Recommended `.gitignore` policy:

```text
external/research/*/
!external/research/README.md
```

If a cloned external project becomes a required dependency later, promote it through an explicit dependency or submodule decision in a separate task.

## Config Ownership

Configuration should be centralized enough to avoid env-var parsing scattered across executors:

```text
agent_world/config.py
  load_node_execution_config(env)
  load_research_config(env)
  load_llm_node_config(env)

agent_world/strategies.py
  executor_for_stage(stage, config)
  stages requiring LLM/research
  skill refs per stage/executor/backend profile
```

`agent_world/agents.py` can continue to own existing `AgentBackendConfig` loading for model/auth/backend. New code should not duplicate secret handling.

## Skill Ownership

Prompts are short, stage-specific request templates. Skills are durable instruction bundles that agents can reuse across invocations. Skills should describe:

- node purpose;
- available tools or providers;
- required output shape;
- source/evidence rules;
- forbidden shortcuts;
- examples of accepted and rejected outputs;
- safety and secret-handling constraints.

Default stage-to-skill mapping:

```text
S1 -> skills/research-source-discovery/SKILL.md
S2 -> skills/knowledge-extraction/SKILL.md
S4 -> skills/tool-surface-discovery/SKILL.md
S5 -> skills/task-generation/SKILL.md
S7 -> skills/verifier-planning/SKILL.md
S8 -> skills/feasibility-review/SKILL.md
```

Skill assignment must be configurable, not hardwired. A strategy should be able to express:

```python
StageExecutionProfile(
    stage="S4",
    executor_id="structured_agent",
    backend_kind="llm",
    skill_refs=[
        "skills/tool-surface-discovery/SKILL.md",
        "skills/knowledge-extraction/SKILL.md",
    ],
)
```

This matters because a generic LLM, a research agent, and a code-oriented agent may need different instruction bundles for the same stage. It also allows an advanced research backend to use a narrower skill set while a lightweight in-repo agent gets more detailed operating instructions.

`structured_agent.py` and `research_agent.py` should load configured skill text and include a `skill_refs` list in invocation records. A missing configured skill should fail fast because it means the node is under-specified.

## Execution Configuration

Suggested env/config:

```text
AGENT_WORLD_NODE_EXECUTION=agent
AGENT_WORLD_AGENT_BACKEND=llm
AGENT_WORLD_OPENAI_BASE_URL=<optional OpenAI-compatible base URL>
AGENT_WORLD_OPENAI_API_KEY=<secret, never written>
AGENT_WORLD_OPENAI_MODEL=<model>
AGENT_WORLD_AGENT_NETWORK=1
AGENT_WORLD_AGENT_MAX_TOKENS=4096

AGENT_WORLD_RESEARCH_BACKEND=local|searxng|process
AGENT_WORLD_SEARXNG_URL=<optional>
AGENT_WORLD_RESEARCH_CMD=<optional JSON-producing command>
AGENT_WORLD_RESEARCH_MAX_QUERIES=5
AGENT_WORLD_RESEARCH_MAX_RESULTS=10
```

If required configuration is missing, the corresponding stage should fail or return `needs_human`.

## Stage Behavior

### PLAN / SELECT / S0

These stages may stay simple initially if needed to bootstrap the run, but they should not preserve the old hardcoded artifact chain as the product behavior. If the implementation touches them, prefer structured agent generation for PLAN/S0 and deterministic policy only for SELECT.

### S1 SourceEvidenceIndex

Use `research_agent.py` and `research/lightweight.py`.

Workflow:

```text
DomainPlan + NeedSpec + raw_request + source_paths
  -> query planning
  -> local source scan
  -> external provider search when configured
  -> candidate evidence normalization
  -> LLM evidence selection
  -> SourceEvidenceIndex fields
```

Provider behavior:

- `local`: reads provided source paths and raw request material.
- `searxng`: calls configured SearXNG-compatible endpoint and normalizes results.
- `process`: invokes configured command with JSON input and expects JSON search results.

### S2/S3/S4/S5/S7 Structured Artifact Generation

Use `structured_agent.py`.

Workflow:

```text
upstream artifacts + target artifact field contract + stage prompt
  + stage skill text
  -> AgentBackend.invoke()
  -> parse JSON object
  -> make_artifact() validation in pipeline
```

Stages:

- S2 prompt produces `KnowledgePack` fields.
- S3 prompt produces `EnvironmentSpec` fields.
- S4 prompt produces `LogicalToolGraph` fields and should include tool-surface discovery context.
- S5 prompt produces `TaskSet` fields.
- S7 prompt produces `VerifierPlan` fields.

### S8 FeasibilityReport

Use:

```text
framework deterministic checks
  + LLM feasibility review
  -> framework final FeasibilityReport fields
```

The LLM can identify semantic risks, missing evidence, weak tasks, verifier gaps, and tool-surface problems. The framework decides final status.

## Executor Result Contract

```python
NodeExecutionResult(
    status="pass",
    fields={},
    evidence_refs=[],
    invocation_records=[],
    trace_refs=[],
    failure_class="",
    recovery_suggestion="",
)
```

Pipeline core wraps `fields` with `make_artifact()`, then runs existing validation/gates/review.

## Invocation Recording

For LLM/research stages, write invocation records into `context.agent_invocations` and `ArtifactStore.put_agent_invocations()`.

Records should include:

- stage;
- node purpose;
- backend/provider kind;
- executor/backend profile;
- skill refs;
- input artifact ids;
- output refs;
- evidence refs;
- trace ref;
- status;
- failure class.

Do not write secret values.

## Error Handling

Important failures:

- `missing_llm_configuration`
- `network_permission_denied`
- `invalid_agent_json`
- `invalid_agent_artifact_fields`
- `missing_research_provider`
- `research_provider_failed`
- `research_result_empty`

Do not silently fall back to deterministic generation.

## Tests

Tests must not create accepted semantic artifacts through mock LLM/research success paths. Unit tests may stub transport-level provider responses or force invalid agent output to verify diagnostics, but a passing request-driven pipeline requires a configured non-mock AgentBackend.

## Migration

1. Add executor result contract.
2. Add structured LLM executor.
3. Add lightweight research agent and providers.
4. Wire S1/S2/S3/S4/S5/S7/S8 to these executors.
5. Remove old deterministic generation from non-IMPLEMENT success path.
6. Update/delete tests that require the old hardcoded outputs.
7. Keep checks/gates/runtime verification.

IMPLEMENT can remain in the existing code path unless changing it is required by the new execution model.
