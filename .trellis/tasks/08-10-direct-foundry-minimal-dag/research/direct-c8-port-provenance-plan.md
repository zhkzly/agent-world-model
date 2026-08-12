# Direct R9-C8 — exact port and causal-input closure

## Why this revision exists

The independent C7 whole-diff check passed all deterministic gates and found
one remaining static Direct contract defect: the runner validates a producer
node but not its declared output port, and five executor boundaries consume
Artifact values not present in their graph bindings. No provider, candidate or
E2E terminal failed. This is the second and final bounded plan revision after
the C6 check lineage; it changes provenance only.

The product target remains an arbitrary natural-language need becoming an
evidence-grounded executable environment, independently verified in an
isolated boundary, published as an immutable Registry EnvironmentPackage and
exposed through safe Observe. Port closure is necessary evidence for that
chain, but passing it alone is not product completion.

## 1. Commit the existing logical output ports

- Add exactly one field to the existing `ArtifactEnvelope`:
  `output_ports: tuple[str, ...]`. `GraphRunner` writes the producing
  `NodeSpec.output_ports`; `ArtifactStore` cold-reads a closed, nonempty,
  unique port list.
- For every edge-bound input, `_resolve_inputs` must match the exact
  `(producer node, EdgeSpec.source_port)` and reject an envelope whose committed
  output-port declaration differs from the fixed producer `NodeSpec`.
- Preserve the C6 decision that one immutable envelope may back two logical
  ports. The caller's named target binding and the fixed Edge specify which
  source port is selected; the envelope proves that the producer committed
  that port. Dependency storage remains one deterministic duplicate-free ref.
- Add no `PortRef`, output-envelope fan-out, graph DSL, scheduler, generic
  binding hierarchy or compatibility reader.

## 2. Bind every currently consumed Direct Artifact

Update only the fixed node declarations, edges and executor calls required by
the C7 finding:

- `research_synthesis` binds the `research_acquire.sources` port as well as its
  citation port. Source text remains ephemeral; the committed acquisition
  envelope binds its content digests.
- `task_requirement` binds architecture and all tool-semantics refs in addition
  to curriculum/rules.
- `modeling_gate` binds evidence and all tool-semantics refs in addition to its
  existing compiled design refs.
- `package` binds VerifierBundle, semantic lineage, implementation lineage and
  the exact Design/Candidate WorkRecords from which telemetry is compiled.
- `registry` binds Design, Candidate, VerifierBundle, the physical package,
  actual dossier, actual telemetry, both lineage refs and the same exact
  WorkRecords, in addition to Package/Integration/Judge. Remove the false edge
  binding that supplied the Package envelope as the dossier value. The bound
  Package envelope and existing cold-read checks still verify that all leaf
  refs belong to that exact package closure.
- A declared input without an incoming graph edge remains an already committed
  framework or other-graph Artifact. The resolver cold-reads the two existing
  media types only: JSON through `read_json`, package bytes through
  `read_bytes`. No media/plugin registry is added.

All values used only through a bound envelope remain transitive and are not
duplicated as inputs. Model projections, prompts, Skills, owner authority,
Judge verdicts, package bytes, Registry publication semantics and public
Observe schemas do not change.

## 3. Small regressions and proof gate

Add focused tests that prove:

1. a right producer with a wrong/missing committed source port is rejected;
2. one valid multi-output envelope can still satisfy its two exact declared
   ports without duplicate dependency refs;
3. each corrected executor WorkRecord contains every actual direct Artifact
   input, including package/registry leaf refs and telemetry WorkRecords;
4. the false Package-envelope-as-dossier binding no longer exists; and
5. JSON and the existing physical package media type are cold-read, while an
   unsupported or malformed binding fails closed.

Run the full deterministic gate and one fresh independent Terra whole-diff
check. Real Direct/Agent/Candidate/E2E proofs remain forbidden until that check
returns `allow`. This revision adds no Repair, Expand, Consumer, retry,
permission, profile, callback, compatibility or legacy behavior.
