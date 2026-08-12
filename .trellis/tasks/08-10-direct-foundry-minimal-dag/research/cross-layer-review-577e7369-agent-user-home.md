# Research: cross-layer review — 577e7369 agent user-home isolation

- Query: Review whether setting `HOME` equal to the existing ephemeral `CODEX_HOME` in the pinned Codex child environment is the smallest coherent repair for ambient `~/.agents/skills` discovery.
- Scope: internal / pinned-SDK adapter and real-preflight evidence
- Date: 2026-08-11

## Decision

**Decision: allow**

- Plan digest: `577e7369b4f118b88e393cef0597412e7c6ca0c3d4e050477d2f396d7f002b43` (independently matched to the complete plan file).
- Plan revision: `agent-preflight-user-home-isolation-plan.md`, first submitted repair-plan revision for `diagnosis-agent-preflight-global-skill-root.md`.
- Revision count: 1 of at most 2 for this Diagnosis Record and plan lineage.
- Scope classification: local adapter-isolation repair. The externally meaningful Agent node contracts, Artifact contracts, and release behavior do not change.
- Trigger: the real Luna singleton-Skill preflight completed, retained its target bundle/digest, closed one session, and cleaned its temporary home, but failed closed because the model also saw 24 `arkcli-*` Skills. A same-pinned-SDK no-model `skills/list` probe attributed every additional Skill to `/home/kelong/.agents/skills` at `user` scope. A probe with only child `HOME` redirected to the existing ephemeral home returned exactly the mounted Skill.
- Affected trust boundary: the framework-owned `CodexAgentBackend` child-process environment and the model-visible Runtime-Skill discovery surface. This is not a graph node, model semantic contract, candidate-process boundary, repair decision, or release decision.

## Product target and plan digest

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

The one-line repair advances only the prerequisite that each tool-enabled runtime Agent begins with its one selected product Runtime Skill and no ambient user Skill root. It is neither a claim that a Researcher/Builder Agent has succeeded nor evidence for Candidate, Integration, Judge, Registry, Expand, Consumer, or Direct E2E completion.

## Findings

### Diagnosis and minimum coherent scope

`CODEX_HOME` already points to a new disposable directory containing exactly `skills/<selected-name>/SKILL.md`. The diagnosis distinguishes the earlier bundled/plugin leak (already repaired by two fixed SDK overrides) from the remaining user root: the pinned runtime derives `~/.agents/skills` from the OS user home independently of `CODEX_HOME`, and its typed `skills/extraRoots/set([])` operation cannot remove that built-in root. The causal experiment changed only the child `HOME` and yielded the expected singleton surface. Therefore:

```text
ambient parent HOME -> pinned Codex SDK child -> ~/.agents/skills user root
                                     ^
                          fixed HOME = ephemeral CODEX_HOME
```

Adding `"HOME": str(codex_home)` to the existing explicit `CodexConfig.env` mapping is the smallest viable repair. It reuses the adapter's existing lifecycle and the already-created directory; it does not introduce a second temporary root, custom SDK lifecycle, Skill filter, denylist, permission/profile abstraction, or a new discovery API call. It is not overdesigned.

The environment change is locally scoped despite serving multiple Agent works: every Agent call reaches the single `_call` launch point, for primary and fallback routes alike. It neither changes any node's model-visible semantic input/output nor alters its selected Skill, workspace, route, Credential handle, prompt, validation, Artifact, retry, or owner. The existing fail-closed before/after physical singleton check remains the enforcement point; changing `HOME` cannot turn an extra Skill into acceptance without that check still passing.

### Impact chain, ownership, and compatibility

```text
ResearchPlan / ResearchSynthesis / BuildPlan / VerifierIntent / CandidateBuild
  -> DesignExecutor or CandidateExecutor
  -> CodexAgentBackend.invoke_json -> _call
  -> CodexConfig.env { CODEX_HOME, HOME, selected credential }
  -> one ephemeral AsyncCodex session / one mounted Runtime Skill
  -> framework validates singleton surface, closes session, removes temporary home

Direct LLM -> DirectChatBackend                                      unchanged
Candidate -> Integration -> Judge -> Package -> Registry -> Observe unchanged
Future Repair / Expand reuse the same Agent adapter boundary             unchanged
Consumer starts from exact released packages, not SDK launch state        unchanged
```

- Owner: `CodexAgentBackend` remains the sole framework owner of temporary-home materialization, exact child environment, SDK setup, session close, cleanup, and before/after bundle validation.
- Immediate consumers: `DesignExecutor` delegates ResearchPlan and ResearchSynthesis through this backend; `CandidateExecutor` delegates BuildPlan, VerifierIntent, and CandidateBuild through the same backend. They retain their existing Runtime Skill selection and workspace contract.
- Workspace: `CodexConfig.cwd`, `thread_start(... cwd=workspace)`, and `thread.run(... cwd=workspace)` remain unchanged. `HOME` only changes the child user's home-based discovery root; it is not the workspace and does not add filesystem authority.
- SDK lifecycle: the existing `AsyncCodex` creation, one ephemeral thread, constant `Sandbox.full_access`, `finally: await session.close()`, and outer temporary-home cleanup remain unchanged. The chosen `HOME` exists for the full session and is removed only after close.
- Credentials: the selected `route.api_key_env` remains the only credential entry. No credential is copied into the temporary home, Artifact, prompt, package, or log. Redirecting `HOME` deliberately prevents ambient home credential/config discovery; a missing explicitly selected handle continues to fail closed rather than silently falling back to ambient state.
- Candidate/Integration/Judge/Registry: these consume framework-committed Artifacts, not the SDK environment mapping. No candidate Runtime, source closure, verifier, IntegrationReport, JudgeReport, release dossier, package manifest, Registry receipt, or Observe projection changes.
- Repair/Expand/Consumer: current Direct still stops with route-free Findings; no repair authority or budget behavior changes. Future Repair and Expand reuse the same DesignGraph/CandidateGraph Agent adapter and receive the same fixed isolation without a new policy/profile system. Consumer has no SDK-launch consumer and remains package/RPC-bound.

### Files found and code patterns

- `agent_world/invocation.py:165-309` — sole `CodexAgentBackend` adapter; `:218-259` creates the ephemeral Skill home and explicit `CodexConfig.env`; `:289-309` owns session creation, exactly one close, and fixed full-access thread/turn lifecycle.
- `tests/test_agent_route_config.py:190-306` — exact backend spy sets ambient `CODEX_HOME` and captures `CodexConfig.env`, mounted bundle, `cwd`, sandbox, session close, cleanup, and absence of persisted credential/endpoint; this is the correct deterministic regression location for asserting `HOME == CODEX_HOME` and `HOME != ambient home`.
- `tests/test_agent_route_config.py:588-610` — SDK initialization-only test uses an independently constructed config and does not exercise the product adapter child environment; it need not become a second configuration path for this one-line repair.
- `agent_world/foundry.py:30-35` — composition root creates one shared `CodexAgentBackend` for Designer and Builder.
- `agent_world/design.py:175-315` and `agent_world/candidate.py:489-690` — current Agent-work consumers delegate to that shared backend; Direct LLM delegates separately to `DirectChatBackend`.
- `node-contracts.md:171-197` — contract requires one ephemeral home/Skill, explicit credential, no ambient Skill/Hook/MCP inheritance, close/cleanup, and a real singleton preflight.
- `research/diagnosis-agent-preflight-bundled-surfaces.md` and `research/cross-layer-review-6e33d4e8-agent-isolation.md` — predecessor repair evidence: bundled `.system` and plugin startup are separately controlled and must remain fixed.
- `research/diagnosis-agent-preflight-global-skill-root.md` — current Diagnosis Record; its causal probe establishes the built-in user-root attribution and rejects `extraRoots/set`, output filtering, validator weakening, and broader framework changes.

### External references and versions

- Local product source of truth: `docs/agent-world-environment-generation.zh.md:5.4` requires a private Codex Agent profile with no ambient Skills/Hooks/MCP/credentials and a unique mounted Skill verified by the initial Available-skills surface.
- Derived execution map: `docs/direct-rewrite-execution-map.zh.md` limits the cleanroom adapter to an ephemeral `CODEX_HOME`, one Runtime Skill, fixed full access, and no profile/permission/plugin framework.
- Pinned dependency: `pyproject.toml:7` and `uv.lock:111-121` lock `openai-codex==0.144.4`. The diagnosis's same-pinned-SDK probes are the compatibility evidence; no new SDK version, public configuration claim, or external provider behavior is being assumed.

## Smallest allowed implementation and proof

1. Change only the existing environment literal in `CodexAgentBackend._call` so it contains `CODEX_HOME`, `HOME` with the same path, and the selected optional credential handle.
2. Update only the existing backend-spy assertion to require the exact three-key mapping when a credential is configured, equality of `HOME` and `CODEX_HOME`, and non-equality with the test's ambient home. Preserve the current assertions for `cwd`, provider overrides, sandbox, one mounted bundle, one close, cleanup, and no credential persistence.
3. Run the focused backend route/isolation regression, then the existing full deterministic checks and independent whole-scope check.
4. Only after deterministic success, run one fresh, temporary, nonce-marker real preflight through the actual adapter and pinned SDK. It must prove the returned initial Available-skills list is exactly the selected Skill and returns the marker; it must separately verify unchanged bundle digest, no `.system`, no plugin cache, no ambient user Skills, one close, non-ambient temporary home, and cleanup.
5. Treat any new real preflight failure as a new terminal scene: preserve the safe outcome, read Observe only if a product graph run exists, then diagnose before any further repair. This preflight itself is outside the product graphs, so no Observe scene may be invented.

## Deterministic checks versus true-boundary proof

- Deterministic regression proves the adapter supplies the intended child environment and preserves its fixed SDK invocation/lifecycle contract. It cannot prove the SDK honors the variable at runtime.
- Full deterministic and independent checks guard against an unintended adapter or graph regression; they do not prove a model-facing Skill surface.
- The single real nonce preflight is the smallest true-boundary proof. It proves only the pinned Agent adapter's singleton Runtime-Skill discovery boundary; it does not prove semantic Agent work, CandidateBuild, Integration, Judge, Registry publication, or the end-to-end product.

## Explicit non-claims

- No claim is made for Direct LLM behavior, any semantic Research/Build/Verifier node success, Candidate source correctness, Integration, Judge, Package, Registry, Repair, Expand, Consumer, or Direct E2E.
- The plan must not add `skills/extraRoots/set`, private SDK access, model-output filtering, a Skill denylist, validator weakening, deletion/hiding of the real user Skill directory, a second temporary directory, dynamic SDK discovery, profile/config/permission/capability machinery, hooks/MCP, callbacks, route/retry/sandbox changes, graph changes, or downstream work.
- `HOME = CODEX_HOME` is discovery isolation, not OS sandboxing and not a replacement for the existing explicit workspace, credential, candidate-process, Judge, or package boundaries.

## Next permitted gate

Implementation is permitted only for the exact child-environment entry and its matching backend-spy regression. After implementation, deterministic checks, independent check, and the one real singleton-Skill preflight are required before any broader proof. This allow expires if the plan digest, adapter discovery trust boundary, pinned SDK behavior, or relevant real-preflight evidence changes.

## Caveats / Not Found

- The diagnosis documents one causal same-pinned-SDK probe, not a production semantic Agent run. The required fresh real preflight remains mandatory; static environment assertions alone are insufficient.
- Redirecting `HOME` intentionally prevents unconfigured ambient home discovery. This is compatible with the declared explicit credential handle, but an environment that depends on undisclosed home-based credentials/config must fail closed rather than be silently supported.
- No product graph run, Candidate, package, Registry receipt, or Observe scene exists for this adapter-only preflight; none may be inferred from a passing preflight.
