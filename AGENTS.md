# AGENTS.md

## Project Intent

This repository should evolve into an Agent-World-like environment generation system.

The user wants a loop-engineering style framework that can take an environment need, capability gap, domain seed, tool ecosystem, PRD, repo, MCP server, CLI, API docs, SDK docs, or other source material, then generate reproducible executable environments with tasks, tools, verifiers, release metadata, and training/evaluation consumer outputs.

AWM is background knowledge and a possible source of examples. It is not the target architecture, not the required data format, and not the system boundary.

The current task source is:

- `docs/agent-world-environment-generation.zh.md`

The current staged Goal documents are:

- `docs/goal-02-hardcoded-full-chain.zh.md`
- `docs/goal-03-online-runtime-grpo.zh.md`
- `docs/goal-04-environment-cli-surface-correction.zh.md`
- `docs/goal-05-open-pipeline-structure.zh.md`
- `docs/goal-06-second-source-family.zh.md`
- `docs/goal-07-generated-environment-bundle.zh.md`
- `docs/goal-08-agent-backed-environment-codegen.zh.md`
- `docs/goal-09-real-code-agent-runner.zh.md`
- `docs/goal-10-packaged-generated-runtime-consumer.zh.md`
- `docs/goal-11-independent-verifier-bounded-repair.zh.md`
- `docs/goal-12-request-driven-generation-pipeline.zh.md`

Keep `docs/loop-engineering.md` and `research/notes/` as background references only.
Use `docs/project-progress-and-corrections.zh.md` as the living progress and drift log; update it when a Goal changes the project's true state or corrects a misunderstanding.

## Current Priority

The first vertical slice is implemented under `agent_world/`.

Maintain and extend that slice without drifting from the task source:

- artifact contracts and validators
- deterministic S0-S11 workflow
- gate and review records
- backend-neutral agent invocation records and backend config
- source discovery and knowledge extraction through explicit agent nodes when needed
- support-desk-lite fixture, Python callable surface, deterministic verifier, replay, and release package
- existing `awm` CLI compatibility

Goal 02 extends only the hardcoded `support-desk-lite` chain from release package into rollout/eval records, deterministic reward records, training export records, and a dataset-only trainer consumer. This is still not generic environment generation.

When explicitly working on Goal 03, extend the same hardcoded `support-desk-lite` chain with an online runtime contract, Python callable runtime, online step/final records, and GRPO/verl adapter metadata. This is still not real trainer integration and still not generic environment generation.

When explicitly working on Goal 04, correct the CLI concept drift. `agent_world.cli_runtime` is a runtime control CLI for health/reset/observe/step/finalize. It is not the user's intended environment CLI surface. Implement environment CLI as a real tool surface: logical tool -> allowlisted argv template -> subprocess.run(shell=False) -> stdout/stderr/exit_code observation -> deterministic verifier reward.

When explicitly working on Goal 05, stop expanding fixture runtime surfaces and open the generation pipeline structure. Keep the working support-desk-lite vertical slice, but start separating pipeline orchestration, node registry, artifact store, source connectors, extraction/synthesis nodes, verifier planning, implementation/code-agent nodes, build/check/replay gates, and release consumers. The goal is to make real source discovery, source-grounded synthesis, and agent-backed implementation possible without turning the core into a prompt script or binding it to one backend.

When explicitly working on Goal 06, prove the Goal 05 pipeline structure is reusable by adding a second local source family, preferably CLI help plus schema/examples. Do not add another support-desk special case. The second family must enter through `LocalSourceConnector` or a small connector extension, produce source-grounded `KnowledgePack`, run through the same `PipelineRunner`/`NodeRegistry`/`ArtifactStore` boundaries, and include negative tests showing missing CLI/schema/rule evidence stops release.

When explicitly working on Goal 07, turn implementation from fixture reuse into generated executable environment bundles. The implementation node must write isolated generated files from source-grounded artifacts: runtime code, seed/state fixture, deterministic verifier, surface descriptor, tests/check script, and build manifest. Verification must import or launch those generated files and run success/failure verifier checks before S10/S11 release planning. Do not count existing fixture runtime imports as code generation.

When explicitly working on Goal 08, replace the remaining deterministic-template implementation path with a verified agent-backed environment code generation path. A code agent may be Codex SDK/CLI, mini-swe-agent, Claude Agent SDK, OpenAI-compatible structured generation, or a custom process adapter, but only through the backend-neutral `AgentBackend` contract. The real codegen backend is `openai_codegen`: it calls an OpenAI-compatible chat-completions endpoint, receives file contents, writes candidate bundle files in an isolated workdir, produces `AgentInvocationRecord`, passes path/redaction/security checks, and only enters release after build/check/replay from those generated files. Do not count deterministic template output or the local process test helper as real code generation.

When explicitly working on Goal 09, implement a real code agent runner. This is different from `openai_codegen`: a runner such as Codex CLI/SDK, mini-swe-agent, Claude Code/Agent SDK, or a custom SWE agent must receive a workspace packet, write files in an isolated workdir, run checks, optionally repair failures, and emit a candidate manifest plus command/trace logs. Do not call local deterministic codegen helpers and call that a runner. The framework must still own the final build/check/replay release gate.

When explicitly working on Goal 10, make verified generated environments callable by downstream steps through a stable package path. Copy accepted `GeneratedEnvironmentBundle` files into `envpkg/runtime/generated/<bundle_id>/`, write `envpkg/release/generated-runtime-index.yaml`, and provide a package-relative consumer check. Do not leave downstream consumers dependent on `/tmp` build workdirs.

When explicitly working on Goal 11, stop trusting generated `check_replay.py` stdout as the release authority. Add a framework-owned independent generated bundle verifier that imports generated runtime/verifier/seed files, verifies every accepted release task with positive and negative records, rejects forged success-only checks, and adds a bounded framework repair loop controlled by `PipelineRunConfig.max_repair_attempts` / `AGENT_WORLD_MAX_REPAIR_ATTEMPTS`. Keep repair attempts under the same `AgentBackend` contract and do not let the agent control pipeline flow.

When explicitly working on Goal 12, implement a request-driven environment generation pipeline, not a third hardcoded domain. A raw request for a booking/ticket reservation service is the first acceptance probe and must produce `booking-service-lite`, not fall back to `project-board-lite`. Add an explicit request/domain planner, strategy selector, source planning/discovery node, source-grounded extraction/synthesis strategy, implementation/code-agent strategy, independent verifier strategy, package release, and bounded repair coverage. Every stage must consume upstream artifact refs and write downstream artifacts with lineage; S3-S11 may not fabricate disconnected domain constants. Once the run starts, the loop must be unattended: no human approval, no mid-run prompt, and no manual registry/source/verifier selection may be required for the success path. Failures must become failure packets that feed bounded repair, an explicit upstream retry edge, or a terminal failed/blocked artifact. Do not implement booking as an isolated script or a manually selected `booking_service_lite_node_registry()` outside the request-driven S0-S11 path, and do not mark the Goal complete if `ReleaseManifest.environment_id` is still `project-board-lite` or if the booking release bypasses the planner/selector/gates.

## Core Principles

- Build an Agent-World-style environment generator, not an AWM reproduction.
- Do not assume there are exactly two loops. Prefer a deterministic staged workflow with explicit feedback edges where useful.
- Treat MCP, CLI, Python callable, HTTP, local services, databases, repos, PRDs, docs, and AWM samples as possible sources or surfaces.
- Keep logical tools separate from concrete surfaces.
- Distinguish environment CLI surface from runtime control CLI and agent backend CLI. Environment CLI means tools like `lark doc create`, `gh issue create`, `kubectl apply`; runtime control CLI means harness commands like health/reset/step/finalize; agent backend CLI means process adapters such as Codex CLI.
- Prefer deterministic verifiers: state checks, file checks, database checks, commands, tests, and API checks.
- LLM/agent nodes may search, extract, synthesize, draft, judge, or implement, but only as explicit workflow nodes with inputs, outputs, budgets, logs, gates, and backend-neutral invocation records.
- Agent backend config belongs to the new framework contract. Prefer `AGENT_WORLD_AGENT_BACKEND=openai_codegen` for OpenAI-compatible file-content codegen smoke, or `AGENT_WORLD_AGENT_BACKEND=code_agent_runner` / `codex_cli_runner` for real code-agent runner smoke. Use `AGENT_WORLD_CODE_AGENT_CMD`, `AGENT_WORLD_OPENAI_BASE_URL`, `AGENT_WORLD_OPENAI_API_KEY`, `AGENT_WORLD_OPENAI_MODEL`, `AGENT_WORLD_SMOKE_OPENAI_MODEL`, `AGENT_WORLD_OPENAI_API_VERSION`, and `AGENT_WORLD_CODEX_CMD`; treat old AWM LLM variables only as legacy fallbacks.
- If Goal mode, CI, or local smoke tests need a real model, prefer cheap configured models such as `gpt-5.4-mini` or `gpt-3-codex-spark`. Do not hardcode these names in core code; read them from config/env and skip live smoke tests when credentials, network, base URL, or model access are unavailable.
- Stable state belongs in artifacts, manifests, typed config, databases, or trace records, not prompt-only memory.
- Training frameworks such as verl, LLaMA-Factory, OpenRLHF, and TRL are consumers, not core dependencies.

## What Not To Do Now

- Do not create or continue an `awmx` demo.
- Do not implement real trainer loops, GPU training, Ray/vLLM/SGLang workers, or framework-specific training dependencies in core.
- Do not bind the design to AWM JSONL or AWM MCP.
- Do not make every environment MCP-only.
- Do not treat a generic CLI command executor as the environment CLI surface.
- Do not count `agent_world.cli_runtime` health/reset/observe/step/finalize as a completed environment CLI surface. It is runtime control unless a separate environment_cli descriptor and real tool command templates exist.
- Do not bind Codex SDK, mini-swe-agent, deep-search, or any single agent runner directly into the core. If a workflow node needs one of them, use a pluggable agent backend adapter with explicit invocation records.
- Do not download the full AWM 1K dataset into the repository.
- Do not introduce unrelated runtime code outside the explicitly requested Goal scope. Goal 03 may add online runtime contracts and a Python runtime for `support-desk-lite`, but not real MCP/CLI/HTTP implementations unless separately requested.
- Do not continue adding runtime/training features while Goal 06 is validating pipeline reuse; keep runtime/training as downstream regressions unless explicitly requested.
- Do not implement Goal 06 by cloning the support-desk workflow with renamed constants; the point is to validate reusable source family and node boundaries.
- Do not mark a Goal 07 generated environment release as verified unless build/check/replay loaded or launched the generated files themselves.
- Do not mark Goal 08 as complete unless a code-agent backend path generated the environment bundle in an isolated workdir and that generated bundle passed build/check/replay. A mock/process agent can prove wiring in deterministic tests, but deterministic template output alone is not enough. For real codegen, use `openai_codegen` or another backend that obtains file contents from an external model/agent, not the local template helper.
- Do not mark Goal 09 as complete unless a code agent runner wrote files in an isolated workspace and ran at least one check command with command logs. A file-content LLM backend, process helper, or deterministic template is not enough for Goal 09.
- Do not mark Goal 11 as complete unless forged generated check success is rejected, every released `project-board-lite` task has independent verifier records, and bounded repair records both success-after-repair and exhausted-failure cases without entering S10/S11 on failure.
- Do not mark Goal 12 as complete unless the request-driven planner/selector path is implemented and `raw_request` for a booking service releases `booking-service-lite`, includes package-level generated runtime files, verifies at least three booking tasks with independent positive/negative records, rejects forged generated checks, preserves existing `support-desk-lite`, `project-board-lite`, and `awm` CLI regressions, proves S0-S11 artifact lineage from raw request to release, and proves the result did not come from a manually selected third fixture registry.

## Work Rules

When changing this repo:

1. Read `docs/agent-world-environment-generation.zh.md` first.
2. Use AWM material only as background or source evidence.
3. Remove or rewrite documents that conflict with the current task source.
4. Keep new implementation scoped to the frozen first-slice contracts unless the user explicitly asks to expand the scope.
5. Use `uv` for Python commands.
6. Preserve existing `awm` CLI behavior unless explicitly asked otherwise.
<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
