# Minimal plan — semantic identity and physical release closure

- Plan lineage: `semantic-identity-release-closure`, revision 2/2
- Trigger: `direct-design-provenance-whole-diff-final-check.md`
- Diagnosis: `diagnosis-semantic-identity-release-closure.md`
- Scope: coordinated existing-node repair across DesignGraph and CandidateGraph

## Product and authority boundary

Preserve the only success path: arbitrary EnvironmentRequest -> Research ->
typed Design -> Candidate -> isolated Integration -> independent Judge ->
Package -> Registry -> safe Observe. GraphRunner owns provenance, Controller
owns Package/release decision, Registry only cold-verifies/publishes, and
models/candidates gain no authority.

## Exact implementation

1. In `agent_world/design.py`, add only the values already disclosed or
   compiled to existing semantic material:
   - ResearchSynthesis: ordered `questions_to_resolve`;
   - ModelingGate: `evidence_ref.digest` and ordered ToolSemantics ref digests.
2. In TaskRequirement's existing per-family loop, bind only the ordered
   `tool_refs[index - 1]` selected by `family.tool_indexes`. Do not change the
   NodeSpec, projection, compiler or downstream ModelingGate closure.
3. In `agent_world/candidate.py`, add only current inputs that affect existing
   behavior:
   - CandidateBuild: the exact canonical Builder `projection` already written
     to `inputs/design.json`;
   - Package: ordered Design and Candidate WorkRecord digests;
   - Registry: Design, Candidate, physical-package and ordered Design/Candidate
     WorkRecord digests, alongside its current fields.
4. Before Registry cold-reads/publishes bytes, compare Package's existing
   `physical_package_ref` with the exact supplied `physical_package`; fail with
   one closed safe code on mismatch. Add no Artifact, edge, second release gate
   or new package field.
5. In `agent_world/graph.py`, remove `local_corrections` from the semantic
   revision declaration. Keep the same NodeSpec limit and attempt records; this
   changes identity only, not correction behavior.
6. Keep existing versioned `prompt_id`, `output_contract` and Runtime Skill
   digest as the explicit Prompt/compiler/Skill identities. Because step 4
   adds one new Registry acceptance predicate, add exactly
   `"registry_acceptance_revision": "physical-package-ref-equality@1"` to
   Registry's existing semantic material and bump that literal only when this
   equality/cold-publish predicate changes. Do not add a NodeSpec field, hash
   source, Prompt bodies, model name, profile values, transport or correction
   packets, or introduce a generic identity abstraction.

## Files and code-size ceiling

- `agent_world/design.py`
- `agent_world/candidate.py`
- `agent_world/graph.py`
- `tests/test_design_semantics.py`
- `tests/test_graph_contracts.py`
- `tests/test_direct_release.py`
- `node-contracts.md` only if a one-sentence identity invariant needs syncing

No new production file, dependency, type, node, graph, config field or
compatibility path. Production Python may increase by at most 18 physical
lines from 10,281; prefer less and delete replaced/redundant material in place.

## Deterministic acceptance

- changing only Research questions changes the real synthesis semantic
  revision;
- changing only ModelingGate Evidence, one ToolSemantics ref, or existing
  SharedToolSemantics ref changes its revision and exact dependency closure;
- a TaskRequirement family excludes unrelated tool refs and retains selected
  refs in declared order;
- changing only CandidateBuild's visible Design projection changes its
  revision;
- changing one ordered WorkRecord input changes Package and Registry revisions;
- Registry rejects a valid but different physical ZIP from the one committed
  by Package and does not publish it; changing the exact physical ref changes
  Registry revision;
- changing only the explicit Registry acceptance revision changes its semantic
  revision without changing graph structure or runtime authority;
- changing only `local_corrections` does not change semantic revision, while
  existing correction-attempt behavior remains green;
- all existing two-graph, owner, Skill, output-contract, package cold-read,
  Observe, legacy-firewall, pytest, Ruff, mypy, compileall and diff checks pass.

## True proof and non-claims

After implementation, obtain one fresh independent whole-diff `allow`; only
then resume the existing ordered proofs: one current Direct node, one actual
singleton-Skill Agent turn, CandidateBuild + offline Integration + Judge, then
fresh natural-language Direct E2E to Registry and terminal Observe. A new real
failure stops at Observe and starts a new diagnosis. This plan does not prove
or implement Repair, Expand, multi-parent evolution, Consumer/SFT/RL or
training.
