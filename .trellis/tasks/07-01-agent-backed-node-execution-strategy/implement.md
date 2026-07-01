# Implementation Plan

## Scope

Implement direct LLM/research-backed execution for selected non-IMPLEMENT nodes. Remove deterministic semantic artifact generation from the success path. Do not preserve old tests that only validate hardcoded artifact contents.

## Ordered Work

1. Add minimal executor result contract.
   - Create `agent_world/executors/base.py`.
   - Create `agent_world/executors/__init__.py`.
   - Define `NodeExecutionResult`.
   - Keep it small and focused on structured fields, invocation records, trace refs, and failure metadata.

2. Add centralized node execution config.
   - Create `agent_world/config.py`.
   - Parse node execution, research, and LLM-node-specific settings.
   - Reuse existing `AgentBackendConfig` loading for backend/model/auth details.
   - Support configurable `skill_refs` per stage and executor/backend profile.
   - Do not write or echo secret values.

3. Add structured LLM executor.
   - Create `agent_world/executors/structured_agent.py`.
   - Use existing `AgentBackend` and `invoke_agent()`.
   - Build prompts from upstream artifacts and target artifact requirements.
   - Load stage-specific skills and include them in the instruction packet.
   - Parse JSON fields.
   - Return structured failure on invalid JSON.

4. Add prompts and skills.
   - Create prompt files for:
     - `KnowledgePack`
     - `EnvironmentSpec`
     - `LogicalToolGraph`
     - `TaskSet`
     - `VerifierPlan`
     - feasibility review
   - Prompts must request JSON fields only.
   - Create skill files:
     - `agent_world/skills/research-source-discovery/SKILL.md`
     - `agent_world/skills/knowledge-extraction/SKILL.md`
     - `agent_world/skills/tool-surface-discovery/SKILL.md`
     - `agent_world/skills/task-generation/SKILL.md`
     - `agent_world/skills/verifier-planning/SKILL.md`
     - `agent_world/skills/feasibility-review/SKILL.md`
   - Skills should define workflow rules, tool/provider usage, output contracts, source/evidence constraints, and forbidden shortcuts.
   - Do not hardcode a single skill per stage inside executors; load skills from the stage execution profile.

5. Add lightweight research implementation.
   - Create `agent_world/research/__init__.py`.
   - Create `agent_world/research/providers.py`.
   - Implement local source provider.
   - Implement SearXNG-compatible provider using `urllib`.
   - Implement process provider using configured JSON command.
   - Create `agent_world/research/lightweight.py`.
   - It should plan queries, collect results, normalize evidence, and use LLM judgment where configured.

6. Add optional external research adapter placeholders.
   - Create `agent_world/research/adapters/__init__.py`.
   - Add adapter boundary files only if needed by implementation.
   - If external projects are cloned for reference, place them under `external/research/`, not under `agent_world/`.
   - Update `.gitignore` so local clones do not pollute commits unless explicitly promoted.

7. Add S1 research executor.
   - Create `agent_world/executors/research_agent.py`.
   - Load `research-source-discovery` skill.
   - Generate `SourceEvidenceIndex` fields from local sources and configured provider.
   - Record provider/search traces.
   - Fail clearly when research execution cannot proceed.

8. Wire pipeline execution directly.
   - Add stage-to-executor selection in `agent_world/strategies.py` or a compact helper.
   - Include configurable skill refs in each stage execution profile.
   - Route S1 to research executor.
   - Route S2/S3/S4/S5/S7 to structured LLM executor.
   - Route S8 to deterministic framework checks plus LLM feasibility review.
   - Do not fall back to old deterministic artifact generation when LLM/research execution fails.

9. Remove old deterministic generation from the success path.
   - Delete or stop using non-essential `request_driven.py` factory calls for S1/S2/S3/S4/S5/S7.
   - Keep only helpers that are validation/normalization/framework policy, if still needed.
   - Update `PipelineNode` definitions so old factory functions are not the product path.

10. Record invocations.
   - Append LLM/research invocation records to `context.agent_invocations`.
   - Write them through `ArtifactStore.put_agent_invocations()`.
   - Include skill refs, evidence refs, and trace refs.
   - Never write secret values.

11. Update tests.
   - Delete or rewrite tests that assert deterministic generated artifact content.
   - Add failure-path tests for invalid LLM output in S2/S5/S7 without accepting mock semantic artifacts.
   - Add research provider transport/normalization tests without accepting mock SourceEvidenceIndex artifacts.
   - Add skill-loading test proving configured stages include skill refs in invocation records.
   - Add invalid JSON failure test.
   - Add missing configuration test proving there is no silent deterministic fallback.
   - Keep runtime/packaging/candidate checks where still relevant.

12. Documentation.
   - Update docs to explain live node execution.
   - Document env vars.
   - Clarify deterministic validation remains, deterministic generation does not.
   - Clarify verified/repair loop remains a later task.

## Validation

Run the relevant test suite after tests are updated:

```bash
uv run pytest tests/agent_world
```

If old tests are intentionally deleted or rewritten, report that explicitly in the final summary.

## Risky Files

- `agent_world/pipeline.py`
- `agent_world/request_driven.py`
- `agent_world/agents.py`
- `agent_world/artifacts.py`
- `tests/agent_world/test_goal12_request_driven_pipeline.py`
- `tests/agent_world/test_agents.py`

## Rollback Points

- Keep framework checks/gates intact while replacing generation.
- Avoid changing IMPLEMENT unless necessary.
- If SearXNG provider is unreliable, keep process/local provider paths and use provider transport stubs only for low-level tests.
