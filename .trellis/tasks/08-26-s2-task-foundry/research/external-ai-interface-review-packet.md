# External AI Review Packet — Actual S1 Interfaces and Current S2 Proposal

Status: **review snapshot, not implementation authority**

Snapshot commit: `9f5627ac4e74d4b074604fc7375efe2941c4e522`

Date: 2026-08-28

## 1. Review request

Independently challenge the cross-stage interfaces of a paper-grade Agent
Environment Foundry. Do not assume that a green test, package-shaped archive or
model-authored verifier proves semantic correctness.

Review against these priorities, in order:

1. a downstream Agent must act through real tools against real persistent state;
2. every admitted Task must have a publicly executable constructive solution;
3. task truth and final-answer correctness must come from real execution and
   trusted state, not from candidate self-report;
4. protected truth must not leak to the acting Agent;
5. Graph-based and Programmatic construction must remain cross-environment and
   cannot rely on hard-coded domain fields;
6. deterministic framework work must not be delegated to an LLM;
7. reject redundant nodes, compatibility paths, custom protocols and speculative
   abstractions without a current consumer.

The current S2 PRD/design are candidate proposals. A reviewer may recommend a
major redesign. Findings must distinguish:

- a defect in the implemented S1 handoff;
- a defect or overdesign in the proposed S2 semantics;
- a decision that must remain open for the product owner;
- a later S3/S4 concern that must not leak backward into S1/S2.

## 2. Authority order

```text
PROJECT.md
  > implemented S1 code and exact release evidence
  > accepted live user decisions
  > current S2 PRD/design proposal
  > this review packet's synthesis
```

This packet summarizes source material; it does not supersede it.

## 3. Stable product stages

```text
natural-language Need
  -> S1 Environment Foundry
  -> exact qualified EnvironmentRelease
  -> S2 Task Foundry
  -> sealed release-bound TaskPack
  -> S3 acting-Agent Episode + verified facts + Reward/abstention
  -> S4 SFT/RL
```

Frozen ownership:

- S1 owns environment generation, environment behavior, independent release
  qualification and immutable publication.
- S2 owns Task construction, constructive solvability, task-local truth,
  verifier material and Task admission.
- S3 owns the acting Agent loop, trajectory, final response, verifier execution
  and reward/abstention.
- S4 owns training and cannot redefine Environment or Task truth.
- MCP, HTTP, provider messages and `tool_call_id` are adapters, not environment
  semantics.

## 4. Actual S1 public API — implemented

### 4.1 Generation entry point

```python
generate_environment(
    need_text: str,
    *,
    config: GenerationConfig | None = None,
) -> Released | NotReleased | Unsupported
```

Current public input is only `need_text: str`. Optional user-supplied
sources/files and explicit constraints are described in the S1 PRD input
boundary but do not yet exist in the implemented public signature.

`GenerationConfig` owns run/release stores and Research, Builder,
Qualification and cold-verification configuration. It is infrastructure input,
not part of Environment semantics.

### 4.2 Terminal results

```python
@dataclass(frozen=True)
class Released:
    release: EnvironmentRelease
    run_root: Path
    research_digest: str
    candidate_digest: str
    qualification_evidence_digest: str
    cold_evidence_digest: str
    archive_digest: str
```

```python
@dataclass(frozen=True)
class NotReleased:
    code: str
    message: str
    details: dict[str, Any]

@dataclass(frozen=True)
class Unsupported:
    code: str
    message: str
    details: dict[str, Any]
```

Only `Released` may publish a release identity.

## 5. S1 internal handoffs — implemented, not S2 inputs

```text
NeedRecord
  -> ResearchReady
  -> CandidateBuild
  -> QualificationResult
  -> EnvironmentRelease
```

### 5.1 ResearchReady

```python
ResearchReady(
    brief: DevelopmentBrief,
    review: EvidenceReview,
    builder_projection: BuilderProjection,
    digest: str,
)
```

```python
BuilderProjection(
    frozen_need,
    selected_world,
    requirements,
    initial_world_relations,
    cited_evidence,
)
```

`BuilderProjection` is private S1 input. It is excluded from the published
project and must not become an S2 compatibility contract.

### 5.2 CandidateBuild

```python
CandidateBuild(
    workspace: Path,
    thread_id: str,
    candidate_digest: str,
    final_response: str,
    checks: tuple[CommandResult, ...],
)
```

Candidate source and public project files are later released, but Builder chat,
thread data and its tests are never release authority.

### 5.3 QualificationResult

```python
QualificationResult(
    status,
    candidate_digest,
    expected_relations_digest,
    evidence_digest,
    evidence_rows,
    probe_bundle_digest,
    negative_evidence_count,
    workspace_root,
    failure_code,
    details,
)
```

Raw evidence rows, predicate carrier, probe source and native expected values
remain protected S1 audit material. S2 receives only the public qualification
summary in the exact release.

## 6. EnvironmentRelease artifact — implemented

### 6.1 Runtime object

```python
EnvironmentRelease(
    release_id: str,
    root: Path,
    project_root: Path,
    payload_digest: str,
    qualification_digest: str,
    archive: Path | None,
)
```

### 6.2 Archive layout

The outer root member set is closed. The `project/` subtree below is a
representative shape from the two real generated releases; its internal source,
docs and test layout remains candidate-defined.

```text
EnvironmentRelease/
├── release.json
├── payload-manifest.json
├── qualification.json
├── project/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── release.json
│   ├── payload-manifest.json
│   ├── src/generated_environment/
│   ├── docs/schemas/
│   ├── README.md
│   └── tests/
├── dist/
│   ├── generated_environment-*.whl
│   └── generated_environment-*.tar.gz
├── docs/
│   ├── DEVELOPMENT_BRIEF.md
│   └── ENVIRONMENT.md
└── licenses/
    └── NOTICE.txt
```

The wheel alone is not the EnvironmentRelease. The outer archive also binds
public docs, schemas, exact source project and qualification summary.

### 6.3 Outer descriptor

```json
{
  "format": "environment-package/1",
  "canonicalization": "rfc8785",
  "hash": "sha256",
  "payload_manifest": "payload-manifest.json",
  "payload_digest": "...",
  "qualification": "qualification.json",
  "qualification_digest": "...",
  "project_root": "project",
  "candidate_descriptor": "project/release.json",
  "public_brief": "docs/DEVELOPMENT_BRIEF.md",
  "public_environment_docs": "docs/ENVIRONMENT.md"
}
```

```text
EnvironmentReleaseID = SHA256(RFC8785-canonical outer release.json)
```

The ID is not embedded in its own preimage.

### 6.4 Inner project descriptor

```json
{
  "format": "environment-release/1",
  "canonicalization": "rfc8785",
  "hash": "sha256",
  "payload_manifest": "payload-manifest.json",
  "payload_digest": "...",
  "environment_factory": "generated_environment.release:make_environment",
  "start_schema": "release-relative/path.json",
  "reset_observation_schema": "release-relative/path.json"
}
```

### 6.5 Public qualification summary

```text
format
verdict
payload_digest
candidate_digest
expected_relations_digest
probe_bundle_digest
evidence_digest
requirement_ids[]
requirement_evidence[]
positive_evidence_count
negative_evidence_count
```

Each `requirement_evidence` contains:

```text
requirement_id
relation_digest
evidence_digest
```

The summary proves binding and coverage but intentionally does not expose raw
native truth or replayable probe source.

Qualification evidence is not a model verdict. The Qualifier model authors
`public_probe.py`, `negative_setup.py` and `native_probe.py` only after the Host
freezes Brief-derived expected relations. The Host owns IDs, digests, manifests,
controlled Candidate copies, journals, probe execution, coverage aggregation
and the final verdict. Admission requires at least one matching assertion per
positive Requirement to flip under a physical near miss while the original
Candidate bytes remain unchanged. The public summary exposes only the resulting
content digests/counts; raw programs and native expected values stay protected.

## 7. Environment runtime contract — implemented

### 7.1 Load

```python
load_environment(
    release_path: str | Path,
    instance_directory: str | Path,
) -> ValidatedEnvironment
```

Preconditions that currently remain outside this function:

- the generated project and dependencies are prepared;
- `generated_environment` is importable in the selected Python runtime;
- the caller supplies the inner `project/` root;
- the caller owns the instance directory.

Loading attaches to an instance. It does not reset it.

### 7.2 Semantic interface

```python
class Environment(Protocol):
    def reset(self, start: JSONObject | None = None) -> JSONValue: ...
    def tools(self) -> tuple[ToolSpec, ...]: ...
    def invoke(self, tool_name: str, arguments: JSONObject) -> ToolObservation: ...
    def close(self) -> None: ...
```

### 7.3 ToolSpec

```python
class ToolSpec(TypedDict):
    name: str
    description: str
    input_schema: JSONObject
    output_schema: JSONObject
```

Schemas use JSON Schema Draft 2020-12. Input schemas have object roots. Output
schemas may describe any JSON value.

### 7.4 ToolObservation

```python
class ToolObservation(TypedDict):
    ok: bool
    data: JSONValue | None
    error: ToolError | None
```

Valid variants:

```text
ok=true  -> data is schema-valid; error is null
ok=false -> data is null; error has code/message and optional details
```

Framework-owned invalid action codes:

```text
contract.unknown_tool
contract.invalid_arguments
```

They do not dispatch domain code, mutate state, witness a business refusal or
enter a public value pool.

Invalid reset raises `EnvironmentContractError`. A crash, timeout, corrupt
result or output-schema violation raises `EnvironmentRuntimeError`; it cannot be
converted into a fictional observation.

### 7.5 State ownership

The generation contract requires authoritative episode state to live below the
caller-assigned instance directory unless an explicitly qualified external
dependency exists. This is not mechanically enforced by `load_environment`;
independence and isolation are attested separately for each release by
Qualification's mandatory `instance_isolation` evidence.

```text
reset(start) -> construct native state and return public initial observation
invoke(...)  -> execute real state transition
close()      -> release resources, preserve committed state
reload       -> attach without implicit reset
```

Separate instance directories are independent. Trusted code may inspect native
SQLite/files/Git read-only. The acting Agent may not.

## 8. Exact S1 -> S2 visibility boundary

### 8.1 Public candidate/actor view

```text
exact EnvironmentRelease ID
public Development Brief and environment docs
public assumptions/exclusions/limitations as prose
start_schema and reset_observation_schema
validated reset observation
ToolSpec[]
ToolObservation stream
later S2-authored Task instruction and final-answer contract
```

### 8.2 Trusted S2 view

```text
exact release archive/project bytes
payload and qualification digests
qualification summary
caller-owned instance directory
host-owned public call/observation trace
candidate source for post-freeze decode-only inspection
native state for trusted read-only task-local truth extraction
```

### 8.3 Explicitly absent from the handoff

```text
BuilderProjection
Research source bodies and private dialogue
Builder/Qualifier conversations
S1 probe source and raw expected native values
Task, graph, reference program or final answer
TruthExtractor, OutcomeVerifier or reward
Episode trajectory or training representation
```

## 9. Two physical S1 releases

### 9.1 Ocean-container / SQLite

```text
release_id: 4e2fb8fe7d81093aab5237d9e486b92407695f79b2cf899cc4a1466a86f7e1c1
candidate_digest: 1981593558fd12f30d1c689fef0b77df265806f8929f4e88c2d10a0af0983498
qualification: 20/20 positive, 20/20 physical negative
cold replay: passed
public tools: 7
```

Tool names:

```text
world_snapshot
advance_clock
submit_dispute
begin_review
review_dispute
withdraw_dispute
get_dispute
```

### 9.2 Filesystem / Git

```text
release_id: b953501fc6f3b6fdbf3249ea0b502e2d3dc1693fbf1719c3111365034bace2e9
candidate_digest: b38416c1e9039abbca493a178e10e9fa5231a3a0ef0bbc105546ee6c8ffb2fc1
qualification: 28/28 positive, 28/28 physical negative
cold replay: passed
public tools: 8
```

Host run records attest that the second release used the same frozen framework
and runtime Skills while only the Need changed. The Git evidence file pins the
framework commit and Skill digests; the uploaded ocean evidence predates that
pin, so cross-run equality is host-attested rather than independently derivable
from the two evidence JSON files alone.

## 10. Implemented S1 gaps that affect S2

These are observed current boundaries, not hypothetical enhancements.

### G1. No public prepare/open API

The release contains source, lockfile, wheel and metadata, not a relocatable
`.venv`. Cold qualification privately executes approximately:

```text
extract archive
-> uv sync --frozen --all-groups
-> compose Foundry loader dependencies
-> load environment
-> replay qualification
```

There is no public equivalent such as:

```python
prepared = prepare_release(release_ref, cache_root)
session = prepared.open(instance_directory)
```

Review decision required: this likely belongs to the S1 runtime library because
S2, S3 and third-party consumers all need exactly the same mechanism.

### G2. No release resolver service

The implemented interface accepts a release directory/ZIP path. There is no
`resolve_release(release_id)` service and no mutable `latest/current` alias.

### G3. Same import package name across releases

Generated releases currently use names such as `generated_environment`.
Long-lived same-process loading can collide through Python import caches.
Per-release Python environment/process isolation is therefore likely required.

### G4. Output schemas may be broad

Host inspection of the uncommitted real release ZIPs found tools whose output
schemas can be only:

```json
{"type": "object"}
```

The current Graph proposal expects typed JSON-Pointer provenance. Reviewers
must decide whether S1 must require more discriminating output schemas or S2
must infer runtime shapes solely through real observations and challenged LLM
binding proposals. The implementation contract permits this broad schema, but
the specific released ToolSpecs are host-observed unless the ZIPs are uploaded.

### G5. Public limitations are prose

Assumptions, exclusions and residual limitations are bound public bytes in the
Development Brief, not a dedicated structured JSON object. S2 must not pretend
a machine-readable limitation contract already exists.

### G6. Public Qualification is summary-only

S2 can validate exact binding and verdict but cannot replay S1 Qualification
from `qualification.json` alone. A task-local verifier must derive its own
truth; a reproducible PackageDefect must return separate evidence to S1.

### G7. Wheel alone is not the release

The supported artifact is the outer EnvironmentRelease. Installing only the
candidate wheel omits outer identity, public Brief and qualification summary.

## 11. Current S2 proposal — not implemented

The current PRD/design require both Graph-based and Programmatic candidate
sources at the system/corpus level. Each Task needs one successful constructive
witness, not redundant witnesses from both lanes.

### 11.1 StartRecipe (proposed)

```text
exact release identity
canonical reset(start) input
optional package-defined asset references
ordered public setup calls
```

Open risk: hidden setup calls may change actor-unobserved state. A reviewer
should require all load-bearing setup facts to be in actor-visible context or
publicly rediscoverable.

Packet-proposed amendments, not rules currently present in the uploaded S2
PRD/design: a business refusal during setup should reject the candidate as an
invalid StartRecipe rather than count as successful setup; setup should not
consume task-relevant scarce state unless that starting fact is stated to the
actor or publicly rediscoverable. External reviewers should challenge or refine
these proposed rules before they enter canonical S2 documents.

### 11.2 StartRecord (proposed)

```text
recipe identity
actual reset/setup observation trace digest
protected native baseline evidence digests
reload persistence and fresh-reset semantic replay outcome
ToolSpec surface and runtime identities
```

### 11.3 Graph lane (proposed)

Inputs:

```text
public docs
ToolSpecs
reset observation
real public exploration observations
```

Candidate evidence:

```text
PublicValuePool
action mask
LLM-proposed and execution-witnessed tool bindings
PublicResultRef(step, json_pointer)
freshly replayed public tau* chain
```

Solvability proof is the successful fresh execution of `tau*`, not the graph or
random walk itself. Framework code may not hard-code `room_id`, `issue_id`,
`sku` or another domain field.

### 11.4 Programmatic lane (proposed)

A bounded reference Python program may use only:

```python
tools()
invoke()
local deterministic computation
```

It may branch, loop and aggregate public observations. It may not read native
state, import candidate business code, change initialization controls or embed
protected operands. Solvability proof is fresh successful public execution.

### 11.5 Task truth by Task type (proposed)

| Task type | Primary truth | Final answer |
| --- | --- | --- |
| state-changing | native before/after and collateral relations | optional unless requested |
| read/query | actual result cross-checked against native truth | required |
| process-constrained | minimal trace predicate plus native result | instruction-dependent |
| composite | required conjunction | required for query/report subgoals |

### 11.6 TruthExtractor (proposed)

```python
TruthExtractor(
    baseline_instance,
    terminal_instance,
) -> TaskLocalFacts
```

It is task-local, may inspect native state and must not call candidate business
functions. It is challenged with entity/field/relation near misses. Circularity
is additionally constrained by freezing expected relations before source
access, requiring fresh-materialization fact agreement and rejecting an
instruction that does not match extracted truth.

### 11.7 OutcomeVerifier (proposed)

```python
OutcomeVerifier(
    task_local_facts,
    final_answer,
    minimal_process_trace,
) -> satisfied | failed | abstain
```

It is separate from native-state decoding and cannot override a deterministic
failure with an LLM verdict.

### 11.8 Admission outcomes (proposed)

```text
Admitted(TaskPack)
QuarantinedCandidate
RejectedCandidate
VerifierDefect
PackageDefect
InfrastructureFailure
```

### 11.9 TaskPack projections (proposed)

Public acting projection:

```text
TaskPack ID
EnvironmentRelease ID
natural-language instruction
actor-visible initial context
declared process constraints
final-answer contract
public limitations
```

Protected projection:

```text
StartRecipe and StartRecord
reference witness/program and reference evidence
task-local TruthExtractor and truth
OutcomeVerifier and dependencies
challenge/mutation evidence
pilot evidence and admission policy digest
```

## 12. Proposed S2 -> S3 interface

S3 acting policy receives only:

```text
public TaskPack projection
ToolSpecs
actor-visible initial context
ToolObservations
final-answer format
```

S3 trusted runtime receives:

```text
exact EnvironmentRelease
protected StartRecipe
TruthExtractor
OutcomeVerifier
protected TaskPack evidence
instance-directory access
```

S3 owns materialization, think/action/observe, public trace, final answer,
terminal native inspection, verifier execution, EpisodeRecord and
Reward/abstention. S2 does not produce training trajectories.

## 13. Proposed S3 -> S4 minimum handoff

This contract is not yet frozen. The minimum current expectation is:

```text
exact EnvironmentRelease ID
exact TaskPack ID
acting model/policy and runner identities
public action/observation trajectory
final answer
verifier result and verified facts
reward or abstention
failure attribution
```

Episode serialization, token masks, scalar reward mapping, SFT filtering, RL
returns/advantages and the veRL adapter remain S3/S4 decisions.

## 14. Explicit non-interfaces

Do not put these in the core S1/S2 semantic contracts:

```text
MCP
HTTP
OpenAI message roles
tool_call_id
JSON-RPC
model-specific function-call envelopes
training masks
veRL batch formats
mutable latest release aliases
universal State JSON
universal verifier DSL
```

## 15. Questions the external reviewers must answer

1. Should public `prepare_release/open` be finalized in S1 before S2 code?
2. Must every prepared release run in an isolated process/venv?
3. Are actual ToolSpec output schemas sufficient for generic Graph binding?
4. Should S1 publish a structured world/limitations summary, or is bound prose
   sufficient?
5. How can StartRecipe setup avoid actor-hidden state and operands?
6. Can Graph binding remain domain-neutral without hard-coded semantic field
   names?
7. Does Programmatic code receive any privilege unavailable to the acting Agent?
8. Is the TruthExtractor/OutcomeVerifier split necessary, or overdesigned?
9. Do S2 pilot policy trials duplicate S3 Episode Runtime?
10. What is the minimum immutable TaskPack that still proves solvability,
    verifier sensitivity and no truth leakage?
11. When is a final answer required, and what exact truth source verifies it?
12. What deterministic/LLM Judge composition is safe?
13. What exact evidence changes `InfrastructureFailure` into `PackageDefect`?
14. Which current S2 fields/nodes have no present consumer and should be deleted?

## 16. Requested reviewer output

Return:

1. `ALLOW`, `MODIFY` or `REJECT` for using the current S2 proposal as the basis
   for implementation planning;
2. findings ordered by severity with exact section references;
3. a complete proposed S1 -> S2 -> S3 interface if the current one is wrong;
4. a deletion list for unnecessary roles/objects/fields;
5. one executable walkthrough for a state-changing Task and one read/query Task;
6. explicit answers to all questions in section 15;
7. remaining product-owner decisions that cannot be resolved from evidence.

Do not write production code. Do not treat the current S2 proposal as authority
merely because it is detailed.

## 17. Files to upload together

Required:

```text
PROJECT.md
.trellis/tasks/08-26-s2-task-foundry/prd.md
.trellis/tasks/08-26-s2-task-foundry/design.md
.trellis/tasks/08-26-s2-task-foundry/research/external-ai-interface-review-packet.md
```

Evidence summaries:

```text
.trellis/tasks/08-26-s1-environment-foundry/research/s1-current-e2e.json
.trellis/tasks/08-26-s1-environment-foundry/research/s1-git-current-e2e.json
```

Snapshot SHA-256:

```text
PROJECT.md
b2e052e88530d15e822a677becf22fbd00379faa40f30127e2c746b2505bca30

S2 prd.md
1d8ab94273d7d6d3950cc0d60bf57d06087972c399a6c6b62d18fc3a52929c7c

S2 design.md
1265bce9631fe791df875aab3dd21117ef15eeaba8c1c3eb4823bf0e973a33b1

S1 ocean/SQLite evidence
d8dee6bd86fd9531aa1bc92c3844cbe7888b2b279d02d38c3be56253d94d5002

S1 filesystem/Git evidence
fd0166f92f622ebb7d5e99f80eee536dda78fa4548f559a706b2f10340ee68de
```

The actual EnvironmentRelease ZIP files are host-local generated artifacts and
are not committed to this branch. Upload them separately only when a reviewer
needs byte-level artifact inspection.
