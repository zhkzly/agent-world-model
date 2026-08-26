# S1 Environment Foundry

## Goal

Turn a natural-language environment Need into a real, qualified and directly
usable `EnvironmentRelease`. The generated environment is a complete uv-managed
Python project with meaningful initial data, executable tools and real native
state transitions. Another team can load the release, reset an episode, inspect
the available tool schemas, invoke tools repeatedly and close the environment.

S1 is complete only when those semantics work from the released artifact. A
demo, mock, template, hard-coded response map, green unit suite or package-shaped
archive is not an environment release.

## Authority and clean-room boundary

- Product intent comes from `PROJECT.md`, accepted decisions, this task and live
  user decisions.
- Product implementation starts from the current clean-break branch. Old branch
  code, plans, prompts, Skills, tests and fixtures are excluded inputs.
- Mature external libraries may be used through their public APIs.
- Booking and filesystem/Git are contrasting conformance Needs, not production
  templates, domain branches or prompt special cases.

## Stage contract

### S1 input

```text
Need
+ optional user-provided sources/files
+ explicit constraints
+ provider/model/resource configuration
```

### S1 output

```text
EnvironmentRelease
├── exact generated uv project and locked dependencies
├── package-owned meaningful initial data/assets
├── standard environment entry point
├── reset(start?) -> structured initial observation
├── start_schema + reset_observation_schema
├── tools() -> ToolSpec[]
├── invoke(tool_name, arguments) -> uniform ToolObservation
├── close()
├── public environment and tool documentation
├── immutable release identity
└── independently authored qualification result
```

S1 does not output a Task, reference solution, final answer, verifier, reward,
trajectory or training record.

### Downstream ownership

- S2 consumes only the released environment contract above and produces a
  release-bound sealed `TaskPack` containing a Task, start configuration, real
  solvability evidence, task truth and verifier/reward material.
- S3 consumes `EnvironmentRelease + TaskPack`, runs the acting Agent and emits
  a verified Episode and attributable Reward.
- S4 consumes verified Episodes for SFT/RL.

Graph-based and Programmatic Task generation are S2 algorithms. They may use
only the environment, tool schemas, public documentation and real observations
already supplied by S1. They cannot require S1 to add graph, witness, Task,
reward or sampler-specific fields.

## Internal context contracts

| Producer | Allowed input | Required output | Immediate consumer |
| --- | --- | --- | --- |
| Research | original Need, supplied material, real Search/Fetch/Extract | fetched evidence and Development Brief | Builder and independent Qualifier |
| Builder | Need, accepted Brief, evidence index, fixed Environment API, empty workspace | complete executable uv project | runner and Qualifier |
| runner | exact candidate project | factual build/runtime observations | Builder repair or Qualifier |
| Qualifier | Need, Brief, public API/docs, candidate source and native instance state; no Builder chat/tests | independent requirement-linked qualification evidence | release publisher |
| publisher | exact candidate and passing qualification | immutable `EnvironmentRelease` | S2 and third-party users |

No stage receives the private conversation, hidden expected values or downstream
artifacts of another stage unless the table explicitly permits it.

## Terminal outcomes

- `Released`: an immutable `EnvironmentRelease` passed native qualification and
  cold third-party use.
- `Unsupported`: no evidence-grounded, resettable and independently testable
  synthetic environment can represent the Need within declared scope.
- `NotReleased`: this run did not satisfy Research, build, qualification or
  release checks; no release identity is published.

The normal generation path does not pause for user approval. Because an
under-specified Need may admit several coherent worlds, the release must disclose
the selected interpretation, material assumptions, alternatives and exclusions.
Automation proves fidelity to that disclosed interpretation; it cannot prove
unstated stakeholder intent.

## Requirements

### R1. Evidence-grounded Research

- One Research Agent uses real Search, Fetch and Extract to learn the domain's
  actors, entities, normal workflows, public interfaces, invariants, refusal
  behavior, time/concurrency concerns, realistic starting data, failure modes
  and mature implementation libraries.
- Search results and model prior are discovery aids. Accepted claims cite exact
  fetched bytes or user-supplied material with stable source identity.
- Research selects one coherent synthetic interpretation and records material
  alternatives, assumptions and exclusions.
- The Development Brief maps each atomic Need clause to an observable, falsifiable
  requirement. It states required capabilities, state relations, successful and
  refused behavior, persistence expectations and meaningful initial-world needs.
- The Brief is human-readable. It does not prescribe tool names, JSON schemas,
  database tables, Rule IR, Tasks, verifiers or rewards.
- An independent Brief review checks omitted Need clauses, unsupported claims,
  contradiction handling and unjustified narrowing. It is Research quality
  control, not an oracle for unstated user intent.

### R2. Real Codex-authored project

- The framework creates an otherwise empty `uv init --package` workspace.
- The Python Codex SDK starts a real coding thread with that workspace as `cwd`.
  It receives the Need, accepted Brief, compact evidence index and the small
  Environment API defined by R3.
- Codex owns all domain code, dependencies, tool design, input/output schemas,
  native storage, initial data/assets, documentation and diagnostic tests.
- Framework code provides no domain tool stubs, CRUD implementation, database
  model, canned data or repository candidate template that can become the
  positive path.
- The generated project must lock, install, build and execute through real uv
  commands. Candidate-authored tests help repair the project but never qualify
  their own release.

### R3. Canonical Environment API

Every generated project implements this transport-neutral semantic surface:

```python
class Environment:
    def reset(self, start: JSONObject | None = None) -> JSONValue: ...
    def tools(self) -> tuple[ToolSpec, ...]: ...
    def invoke(self, tool_name: str, arguments: JSONObject) -> ToolObservation: ...
    def close(self) -> None: ...
```

`ToolSpec` contains only:

```text
name
description
input_schema
output_schema
```

Every invocation returns the same outer record:

```text
ToolObservation
├── ok: bool
├── data: JSONValue | null
└── error: null | {code: str, message: str, details?: JSONValue}
```

`output_schema` describes `data` when `ok` is true. The error details remain
tool-specific structured JSON.

All start, input and output schemas use JSON Schema Draft 2020-12. They are
self-contained release members and may use local fragment references only; no
remote `$ref` resolution is permitted. Tool input and non-null start schemas
have object roots. `None` selects the universal package default outside the
start schema. Output schemas may describe any JSON value.

Every release names both `start_schema` and `reset_observation_schema` as
digest-bound public members. The loader validates every non-null start before
reset and every returned initial observation against the latter schema.

Only these observation variants are valid:

```text
ok=true  => data validates against output_schema and error is null
ok=false => data is null and error contains code/message plus optional details
```

Contract rules:

- `reset(None)` constructs a meaningful package-owned starting world and returns
  the initial public observation. Environments may additionally accept a
  package-specific structured `start` object described by a public schema.
- Repeating the same release and start reconstructs the Brief-declared business
  relations and observable behavior. Incidental bytes, timestamps or identifiers
  need not be identical unless explicitly promised.
- `tools()` describes the complete public acting surface.
- `invoke()` validates the tool name and arguments, executes real project code
  and returns a `ToolObservation`. Successful `data` validates against that
  tool's output schema.
- A business refusal is `ok=false` with a stable tool-specific error code and
  structured details. It is a valid actor-visible observation, not a process
  failure, and must not perform prohibited mutation.
- Unknown tools and invalid arguments return `ok=false` with reserved
  `contract.unknown_tool` or `contract.invalid_arguments` codes and do not
  dispatch domain execution. The `contract.*` namespace is framework-owned and
  cannot satisfy a business-refusal, state-transition or Task-truth predicate.
- Invalid non-null reset input raises `EnvironmentContractError` before changing
  state. Crashes, timeouts and corrupt results raise `EnvironmentRuntimeError`;
  neither becomes a fictional ToolObservation.
- A value in a successful observation's `data` remains machine-addressable and
  may be supplied directly to a later tool. The framework never mines
  identifiers from prose or error messages.
- Text, images and files are represented inside the tool's declared structured
  `data`, including public content/artifact references when needed. S1 does not
  impose MCP content blocks.
- `close()` releases resources. The loader/runtime owns instance-directory
  allocation and cleanup; these are not acting-Agent tools. Closing does not
  delete committed state. Loading the same release against an existing instance
  directory reattaches to that state without an implicit reset.

The Environment API contains no OpenAI message roles, `tool_call_id`, MCP,
JSON-RPC, HTTP, batch identifier or training mask. A caller may generate
correlation IDs and expose this API through MCP, HTTP or a model-provider adapter
without changing environment semantics.

### R4. Real initial state and native transitions

- Each release includes meaningful domain-appropriate initial data or assets.
- `reset` constructs actual native state under its assigned instance directory.
  State-affecting time, randomness or exogenous inputs must come from the
  package's structured start/configuration rather than undeclared ambient state.
- Tools use a real backend appropriate to the generated Need, such as SQLite,
  files/Git or another independently readable representation. A decorative
  database beside an in-memory dictionary implementation fails qualification.
- Separate instance directories represent independent episodes. One instance
  must not mutate another.
- Load-bearing state must be independently observable by a trusted Qualifier.
  An opaque representation with no independent reader cannot support a canonical
  S1 release.

### R5. Independent semantic Qualification

- Qualification is independently authored from the Need and Brief. The
  Qualifier does not receive Builder chat, repair history or Builder tests.
- Before reading candidate source, the Qualifier records the Brief-derived
  expected business relation and acceptance predicate for every core
  requirement. It may then read source only to locate/decode native
  representation. The evidence records this ordering and purpose.
- Source blindness is not required: arbitrary native encodings may require
  source inspection. Independence means expected behavior comes from the
  Need/Brief and native facts are checked with an independent reader. Candidate
  business functions are never imported or called as the expected-answer oracle.
- Each core Brief requirement maps to at least one executable public probe and
  corresponding evidence appropriate to the claim.
- Qualification exercises multi-step value chaining, native before/after state,
  business refusal without prohibited mutation, reset reconstruction, instance
  isolation and use from a cold extracted release.
- When a package publishes non-default start fields, Qualification exercises at
  least one valid non-default start and repeats it on a fresh instance.
- SQLite is checked with independent SQLite reads; filesystem/Git with file APIs
  and Git plumbing; other formats require an independent standard reader or an
  independently authored parser.
- Each core semantic probe must reject a reachable wrong or near-miss behavior.
  Prefer physical counterexamples. Source mutation may be used as a testing
  technique where useful, but S1 has no Mutator product role or mandatory
  mutation protocol.
- Any uncovered or non-discriminating core requirement ends `NotReleased`.

### R6. Causal repair

- Build and qualification failures report reproducible facts: candidate
  identity, phase, command or public call, violated Brief requirement, actual
  structured result and independently observed native relation.
- The same Builder thread may repair its project. Every changed byte creates a
  new candidate revision and reruns affected checks.
- Feedback never includes hidden probe source, protected expected values or
  patch instructions derived from a private answer key.
- Research defects return to Research; invalid qualification logic is corrected
  without changing candidate bytes; infrastructure retries keep candidate bytes
  unchanged. Exhaustion ends `NotReleased`, never a fallback implementation or
  weaker contract.

### R7. EnvironmentRelease and cold use

The public release contains only what another team needs to run the environment:

- exact generated uv project, lockfile, source and built distribution;
- package-owned initial data included as generated-project package data and in
  the built distribution;
- standard environment entry point and small loader metadata;
- `start_schema`, `reset_observation_schema`, public environment documentation
  and tool documentation;
- licenses and an immutable payload digest;
- a host-authored qualification summary bound to that digest.

Identity is non-circular. A canonical payload manifest binds every public
runtime member other than the manifest, qualification summary and release
descriptor. The canonical qualification summary binds that payload digest and
content-digested evidence references. The canonical release descriptor binds
the loading metadata plus payload and qualification digests;
`EnvironmentReleaseID` is the SHA-256 of that descriptor and is not embedded in
its own preimage.

Detailed Research sources, hidden probes, raw native expected values, failed
candidates and repair conversations are audit evidence, not runtime payload.
They may be retained separately without becoming a product subsystem.

Cold qualification extracts the exact release into an unrelated directory,
installs from its declared locked dependencies, loads the standard entry point
and performs:

```text
reset -> tools -> invoke -> invoke -> close
```

It also verifies native state, reset and instance isolation. Publication stores
the exact immutable artifact by identity. S1 does not require a custom Registry
service, mutable `current/latest`, proprietary transport or offline-wheel claim.

### R8. Complete S2 seam

S2 receives exactly:

```text
EnvironmentRelease identity and runtime project
+ reset/start schema and initial public observation
+ ToolSpec[]
+ invoke semantics and uniform ToolObservations
+ public environment documentation
+ trusted access to an episode's instance directory for task-specific truth checks
+ S1 qualification summary and declared limitations
```

That is the complete S1-to-S2 contract. S2 may explore the environment and use
public observations to build Graph-based or Programmatic candidates. It may
author task-specific truth extraction, verifiers and reward material, but it
does not modify native state except through `reset` and public tools.

If a proposed Task needs information unavailable from its Task/start context or
public tool observations, that Task is invalid or requires another public tool;
it is not a reason to add protected S2 fields to S1.

### R9. Minimal framework surface

- Implement one direct imperative coordinator. Do not add a graph runtime,
  workflow engine, custom sandbox, custom RPC protocol, universal state model,
  domain DSL, compatibility reader or old/new feature flag.
- Product runtime Skills begin with one Research method Skill and one environment
  code-generation Skill. Additional Skills require observed repeated need.
- Any helper, artifact field or stage must name its present producer and
  consumer. Fields without a current consumer are removed.
- Partial implementation slices are checkpoints, never `Released` products.

## Acceptance criteria

- [ ] AC1: A real unfamiliar Need completes evidence-backed Research and an
  independently checked Development Brief without prescribing implementation
  schemas or Tasks.
- [ ] AC2: The real Python Codex SDK creates the complete candidate project in
  an initially domain-empty uv workspace.
- [ ] AC3: A third-party-shaped client can load the release and execute
  `reset -> tools -> invoke -> invoke -> close`; `reset` returns a structured
  initial observation and the second invocation consumes a value from the first.
- [ ] AC4: Every invocation returns the uniform `ok/data/error` record;
  successful data validates against tool-specific output schemas, business
  refusals are valid observations without prohibited mutation, and invalid calls
  do not execute domain code.
- [ ] AC5: Booking-like qualification observes real SQLite relations for search,
  reservation, refusal, reset and isolation, with no framework booking branch.
- [ ] AC6: Filesystem/Git qualification observes real bytes, modes and Git
  objects through the same Environment API, with no framework Git branch.
- [ ] AC7: Every core Brief requirement has an independent, discriminating probe
  and native evidence. Candidate tests alone cannot authorize release.
- [ ] AC8: Exact released bytes pass cold extraction and direct use without a
  development checkout, generator conversation or MCP-specific client.
- [ ] AC9: An S2-shaped consumer uses only the contract in R8. No S1 artifact
  contains Graph, Programmatic, Task, verifier, reward or trajectory fields.
- [ ] AC10: After generic framework/prompts/Skills freeze, independently selected
  held-out Needs traverse the same path without adding domain branches. The
  experiment reports its actual scope rather than claiming universal coverage
  from one example.

## Out of scope

- Graph-based or Programmatic Task generation and Task admission.
- Task truth extraction, verifier implementation, reward and final-answer policy.
- Agent episode execution, trajectory serialization and SFT/RL.
- Universal native-state schema, snapshot API or verifier DSL.
- Mandatory MCP/HTTP transport or model-provider message format.
- Compatibility with any prior environment release, ABI, Task or reader.

## Evidence basis

- Official Codex SDK: <https://learn.chatgpt.com/docs/codex-sdk>
- Official Python SDK API: <https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md>
- uv project locking/syncing: <https://docs.astral.sh/uv/concepts/projects/sync/>
- uv builds: <https://docs.astral.sh/uv/concepts/projects/build/>
- Agent World Model: <https://arxiv.org/html/2602.10090>
- Agent-World: <https://arxiv.org/html/2604.18292>
- PROVE: <https://arxiv.org/html/2606.03892>
