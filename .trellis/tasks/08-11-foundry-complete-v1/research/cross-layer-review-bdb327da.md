# Research: cross-layer review bdb327da

- Query: Revision 2 of 2 independent cross-layer review of the complete-v1 development-dispatch amendment, including the exact 16-input plan digest, parent/child worker attribution, unchanged runtime routes, and Direct -> Repair -> Expand -> Consumer compatibility.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest: `bdb327dae0d0d6da59a9bf73224f1503363b4f44991a199c396b564df722ab2b`
- Plan revision: `release-public-handoff` R3, dispatch-amendment revision 2 of 2.
- Scope classification: coordinated development-gate dispatch contract across the parent and four child tasks. This is not a runtime route, Artifact, authority, validation, release, or public API change.
- Trigger: closure of the R1 dispatch-review `block` in `cross-layer-review-b34be669-terra-dispatch.md`; no failed real proof or Observe scene is involved.

## Product Target And Trust Boundary

The target remains an arbitrary natural-language `EnvironmentRequest` becoming an evidence-grounded executable environment, independently verified in an isolated boundary, released as an immutable Registry `EnvironmentPackage`, and exposed only as safe Observe facts. Expand must create diverse packages through the same Design/Build/Judge/Release path using evidence and exact released parents; Consumer may use only exact released packages to produce isolated public episodes without environment, reward, or release authority.

The amended boundary is development-worker selection and attribution only. The written rule now requires every declared parent/child research or critic, implementation, and check spawn to state `--provider codex --model gpt-5.6-terra`; it forbids ambient model inheritance. It does not confer framework authority on the worker or change a product executor.

## Findings

### Digest And Revision Closure

- Independently hashing the exact 16 raw inputs in the recorded order, as newline-terminated `sha256sum` lines followed by SHA-256 of that concatenation, reproduced `bdb327dae0d0d6da59a9bf73224f1503363b4f44991a199c396b564df722ab2b`.
- The predecessor block required the parent matrix and dispatch rule plus Direct, Repair, Expand, and Consumer instructions to name the provider/model explicitly, while keeping runtime routes untouched. R3 makes that exact change and retains the required deterministic checks and proof sequence: `research/cross-layer-review-b34be669-terra-dispatch.md:70`, `:93`, `:125`.

### Parent And Child Dispatch Compatibility

- The parent declares all system research, critic, implementation, and check workers as explicit Codex/Terra and distinguishes those workers from runtime routes: `.trellis/tasks/08-11-foundry-complete-v1/prd.md:199`.
- The parent dispatch rule explicitly covers critic, implementation, check, and further read-only research/diagnosis, requires the current exact-digest allow in each child context, and stops dispatch for an omitted provider/model or a runtime-route change: `.trellis/tasks/08-11-foundry-complete-v1/implement.md:172`.
- Direct makes research/critic, implementation, and check explicit: `.trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md:335`, `.trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md:343`.
- Repair makes its fresh critic, implementation, and check explicit: `.trellis/tasks/08-11-foundry-bounded-repair/implement.md:9`, `:12`, `:24`.
- Expand makes its fresh Campaign/Release critic, implementation, and check explicit: `.trellis/tasks/08-11-foundry-expand-multiparent/implement.md:9`, `:12`, `:30`.
- Consumer makes its fresh Consumer/public-boundary critic, implementation, and check explicit: `.trellis/tasks/08-11-foundry-consumer-sft-rl/implement.md:8`, `:11`, `:29`.
- The three Trellis agent profiles are pinned to `gpt-5.6-terra`, but the plan correctly treats profiles as defense in depth rather than replacing explicit spawn arguments: `.codex/agents/trellis-research.toml:5`, `.codex/agents/trellis-implement.toml:5`, `.codex/agents/trellis-check.toml:5`.

### Runtime And Cross-Layer Compatibility

- The baseline and worktree have no diff under `agent_world/`, `tests/`, `config/`, `pyproject.toml`, or `README.md` relative to clean baseline `9562c058b61562c11f76d8127f56b68b0f5be2d9`; `agent_world/config.py` and `agent_world/foundry.py` are also byte-for-byte unchanged. Runtime Direct and Codex Agent adapters remain separately constructed from `FoundrySettings`: `agent_world/foundry.py:142`, `agent_world/config.py:37`.
- The one remaining `gpt-5.3-codex-spark` occurrence in the 16 plans is the unchanged runtime `agent` fallback route, not a development dispatch: `.trellis/tasks/08-11-foundry-complete-v1/design.md:303`. It is explicitly separated from the development-worker matrix at `:310`.
- The canonical source requires Direct as the independent core path, Repair through framework-owned findings, Expand through the same complete trusted path, and Consumer only after Registry release: `docs/agent-world-environment-generation.zh.md:70`, `:98`, `:117`, `:127`. The derived execution map confirms shared DesignGraph/CandidateGraph, outer bounded Expand, and read-only Observe: `docs/direct-rewrite-execution-map.zh.md:30`, `:45`.
- Thus the amendment changes no producer output or consumer input: Direct still supplies the first exact released package; Repair still re-verifies owner evidence and records bounded invalidation before re-entry; Expand still consumes exact released parents and produces a new independently judged/released child; Consumer still admits exact released refs and keeps materialization/reset state private. Framework ownership of routing, invalidation, Judge, ReleaseKernel, Registry, reward, and termination remains unchanged.

## Files Found

- `research/plan-digest-release-public-r3.md` - R3 scope statement, ordered 16-input hashes, and claimed aggregate.
- `research/cross-layer-review-b34be669-terra-dispatch.md` - prior blocking criteria and required amendment closure.
- `prd.md`, `design.md`, and `implement.md` under the complete-v1 parent and four named child tasks - frozen dispatch contracts and producer/consumer sequencing.
- `AGENTS.md` - source-of-truth precedence and critic-gate requirement.
- `docs/agent-world-environment-generation.zh.md` - canonical product, authority, and path contracts.
- `docs/direct-rewrite-execution-map.zh.md` - derived executor/route taxonomy.
- `.codex/agents/trellis-{research,implement,check}.toml` and `.trellis/config.yaml` - development profile defaults and subagent-mode configuration.
- `agent_world/config.py` and `agent_world/foundry.py` - unchanged runtime `direct`/`agent` route construction.

## Smallest Tests And Proof

1. Before every parent or child dispatch, mechanically require each declared development-worker instruction to include the exact Codex provider and Terra model; reject omitted, inherited, or Spark development selection.
2. Before implementation/check, verify the matching exact-digest parent allow and fresh child allow are present in that child's manifests.
3. Keep the runtime route table unchanged; the current R3 review proves only this static planning/configuration boundary.
4. The next real product proofs remain ordered: a fresh Direct release; negative-to-repaired lineage; documentation-grounded single-parent and useful two-parent Expand packages; then unknown-seed Consumer episodes with SFT export and RL reset/step. Read Observe at every real terminal.

## Non-Claims And Next Permitted Gate

This allow does not prove a Direct release, repair, Campaign, multi-parent child, Consumer episode, SFT/RL output, provider capability, or end-to-end product completion. It does not permit changing runtime routes, product code, Artifact schemas, ownership, release policy, or child contracts under the guise of dispatch selection.

Next permitted gate: the coordinator may add this current exact-digest allow to the relevant parent/child implementation and check contexts, then dispatch only the planned child work with explicit `--provider codex --model gpt-5.6-terra`. Any change to the 16-input digest, affected trust boundary, or relevant real scene expires this allow and requires a new review.

## Caveats / Not Found

- No external reference was needed; this decision is based on the canonical project document, derived execution map, frozen plan inputs, profile/configuration files, and baseline comparison.
- No product proof, Observe scene, provider invocation, code edit, manifest edit, or runtime-route edit was performed by this reviewer.
