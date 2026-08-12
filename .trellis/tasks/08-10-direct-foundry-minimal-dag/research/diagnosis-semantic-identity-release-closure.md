# Static diagnosis — semantic identity and physical release closure

## Evidence and symptom

The fresh whole-diff check
`direct-design-provenance-whole-diff-final-check.md` blocked live proof after
160 deterministic tests passed. This is a static finding, not a real run
terminal, so no Observe scene exists or is invented. Two bounded read-only
audits then checked every existing DesignGraph and CandidateGraph execution
site:

- `design-semantic-material-completeness-audit.md`
- `candidate-semantic-material-completeness-audit.md`

The product target remains natural-language need -> evidence-grounded
executable environment -> isolated Integration and independent Judge -> exact
immutable Registry EnvironmentPackage -> safe Observe.

## Causal finding

`GraphRunner` correctly records exact ordered input/dependency Artifact refs,
but each node separately supplies the effective semantic material used for its
semantic revision. A few existing handlers disclose or compile immutable
values that their material omits:

1. ResearchSynthesis discloses `questions_to_resolve` to its Agent.
2. ModelingGate compiles EvidenceGraph and all ToolSemantics into Design.
3. CandidateBuild discloses the deterministic Builder projection.
4. Package and Registry compile telemetry from ordered Design/Candidate work
   records.
5. Registry publishes a physical package input without first checking it is
   the exact physical ref committed by Package.

Separately, TaskRequirement currently binds every tool shard although one
family discloses and consumes only its selected tool indexes. Also
`local_corrections` is execution/attempt policy but is currently hashed into
semantic identity.

These facts explain how an actual node input or release object can change
without the intended semantic identity changing, or how an unrelated shard can
invalidate a family. They are framework provenance defects, not Luna/Spark
instruction-following failures and not missing retries.

## Findings deliberately rejected as overreach

- Do not hash API keys, base URLs, timeout, workspace paths, caches, provider
  retries or the resolved model into semantic identity. Model/usage/Skill facts
  remain OperationEvidence; transport does not redefine acceptance.
- Do not hash a local CorrectionPacket into a new semantic revision. It is a
  second physical attempt for the same frozen node inputs and is already
  recorded as attempt evidence.
- Do not add source reflection, a generic semantic-material framework, another
  schema, or automatic handler hashing. Existing versioned `prompt_id`,
  `output_contract` and Runtime Skill digest remain the explicit implementation
  identities; a semantic template/compiler change must bump the existing
  versioned identity.
- Do not change ToolSemantics shared refs: current WorldArchitecture admits
  exactly zero groups for one tool or one group containing all tools, so its
  current selected/all tuple is already identical.
- Do not implement Repair, Expand, Consumer, training or compatibility here.

## Smallest coherent repair boundary

Edit only existing semantic maps, one TaskRequirement ref selection, the
existing GraphRunner declaration, and Registry's existing equality gate. Add
targeted deterministic regressions. No model Prompt, Runtime Skill, public
schema, graph topology, owner, route, retry or package format changes.

This diagnosis proves only a static cause. Direct LLM, Agent SDK, Candidate,
Judge, Registry and E2E remain unproved until a reviewed implementation passes
the ordered real-execution sequence.
