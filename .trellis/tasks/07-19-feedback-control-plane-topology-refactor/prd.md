# Feedback Control Plane and Pipeline Topology Refactor

## Product purpose

The product converts a natural-language environment need into a genuinely executable,
programmatic Agent environment that can be installed, reset, stepped, rolled out,
independently evaluated and published for later rollout/veRL training.  Program code owns
state transition.  LLM text simulation, mocks, fixed replay cases, generated-test-as-oracle
and environment-specific success branches are not valid product paths.

The framework is loop engineering: code owns workflow state, Artifact lineage, validation,
budgets, retry, invalidation and release authority.  Bounded Agents own real research,
semantic proposal, code generation and hard semantic challenge.  Humans intervene only for
permission, unresolved ambiguity, unacceptable risk, credentials or release policy.

Direct Generation is independently useful from one human need.  Discovery may provide
optional evidence.  Evolve searches for additional environment needs or coverage by
sampling parents/operators/selectors, but every selected proposal must enter the same full
research, design, build, assurance and publish path as Direct.

## Problem statement

The current system contains valuable strict contracts, real subprocess verification,
content-addressed Artifacts and observability, but its feedback control plane has accumulated
multiple authorities and asymmetric paths:

- seven real hotel Direct runs did not cross Design;
- a single no-progress semantic repair consumed 50,645 provider tokens;
- generic root diagnostics and generic semantic errors erased actionable conditions;
- old microsharding consumed over 900k accounted tokens without a Design;
- retry limits are independently owned by components, FeedbackContract, RepairLedger,
  Controller loops and job budgets;
- one local failure expands into several overlapping durable control objects;
- FeedbackResult is not consumed to derive readiness or release claims;
- Direct and Evolve have different Design and repair control planes;
- Integration and final Judge repeat deterministic/public work on the same bytes;
- the CLI cannot run a bounded downstream diagnostic without ordinary rework;
- Builder and some tests can remain silent for minutes without a first-progress terminal.

The answer is not to weaken correctness checks.  It is to make every feedback boundary have
decision value, keep leaf diagnostics local and exact, and constrain repair to the smallest
causal Artifact.

## Functional requirements

### FR-1: one shared generation WorkGraph

Generate and Expand MUST instantiate the same typed logical WorkGraph:

`ResearchEvidence -> WorldArchitecture -> WorldBehavior -> WorldRules ->
TaskCurriculum -> ModelingBoundary -> Build || VerifierIntent -> Integration ->
ReleaseAssurance -> Package -> Registry`.

GenerateSeed and ExpansionSeed MAY differ.  ExpansionSeed includes selected parents,
MutationIntent and optional clues, but it MUST produce a full new EnvironmentDesign and real
EnvironmentPackage through the common graph.  No Evolve semantic retry may bypass global
repair authority.

### FR-2: explicit proposal, validation and assurance responsibilities

Each WorkDefinition MUST independently declare:

1. proposal executor and its capability profile;
2. deterministic validation policy;
3. optional real-execution assurance policy;
4. inputs, output coordinate and dependency edges;
5. repair policy and release effect.

An LLM MUST be used only for research planning/synthesis, semantic proposal, code generation
or a hard semantic advisory that deterministic code has explicitly classified as undecidable.
LLM output MUST never directly choose route, retry, invalidation, maturity or release.

### FR-3: two levels of feedback evidence

Leaf checks MAY be numerous but MUST aggregate into one exact ValidationReport for the
current WorkAttempt.  A durable FeedbackEvaluation MUST be emitted only at a boundary where
the result changes readiness, routing, quarantine or release state.

Every boundary definition MUST answer:

- what Claim is checked;
- why it is checked at that time;
- which executor evaluates it;
- its hard cost/deadline class;
- how the causal owner is derived;
- the minimal repair Artifact coordinate;
- permitted attempts;
- maximum automatic backjump;
- exact downstream invalidation rule;
- diagnostic, readiness, release or publication effect.

### FR-4: actionable deterministic diagnostics

Mechanical format, schema, type, reference, protocol, lifecycle, budget and policy failures
MUST produce stable issue code, exact safe path, violated condition, expected/allowed safe
category, validation phase/frontier and retryability.  A generic root diagnostic MUST fail a
diagnostic-quality check and MUST NOT consume an Agent correction.

Rejected values, secrets, private verifier cases and provider transcripts MUST NOT enter
diagnostics or Artifacts.

### FR-5: one repair authority

One RepairPolicy per logical Artifact coordinate and one global BudgetLedger MUST be the only
retry truth.  Component-local `max_reworks` loops MUST NOT independently authorize semantic
work.

- one local correction is allowed by default;
- a second local correction requires code-proven strict progress;
- identical issue/frontier, regression and A-to-B-to-A oscillation stop automatically;
- an automatic one-hop parent repair requires a precise causal Artifact edge;
- distance two or greater requires human authority;
- infrastructure retry is typed separately from semantic repair but charged by the same
  global budget authority.

### FR-6: causal invalidation and sibling retention

Repair ownership MUST be derived from boundary policy plus Artifact/Claim dependency edges;
Agent or validator owner text is only a hint.  A new revision invalidates only descendants of
the repaired coordinate.  Successful independent sibling shards MUST remain committed and
reusable.  Generate, Expand and resume MUST use the same rule.

### FR-7: one maturity and release truth

Readiness and ClaimVector MUST be derived from active, digest-bound terminal
FeedbackEvaluations and WorkCommits.  Controller MUST NOT construct a second unrelated
release projection.  Registry release exists only after exact package bytes are atomically
committed and reread.

### FR-8: non-duplicative independent assurance

Integration MUST emit evidence bound to candidate source digest, validation-policy digest,
toolchain/validator versions, runtime profile/image commitment and freshness.  Final Release
Assurance MUST consume matching Integration evidence and add reachability, property,
behavior, sealed and fresh-release checks.  It MUST NOT blindly repeat matching static,
public protocol or materializer work, while preserving an independent fresh deployment
boundary.

### FR-9: explicit diagnostic execution lane

The CLI MUST support real, bounded, no-rework diagnosis from a committed Design or Candidate,
including at minimum:

```text
agent-world run diagnose --from DESIGN_REF --until integration --no-rework
agent-world run diagnose --from CANDIDATE_REF --until reset-step --no-rework
agent-world run retry-node REQUEST_ID --artifact REF
```

Diagnostic outputs MUST be marked non-releasable and MUST NOT silently become release
evidence.  A default automatic provisional/partial Builder is out of scope until live data
shows it has positive diagnostic value.

### FR-10: complete observability

Every operation MUST expose scheduled/start/progress/end or terminal-error events with
stable trace/run/work-attempt identities.  Metrics MUST separate controller-accounted,
provider-observed and unknown dimensions and include at least:

- wall time, queue time and critical path per logical and physical work item;
- actual/upper-bound/unknown input, output and total tokens;
- invocation and correction counts;
- real search queries, search/fetch/parser calls, documents and evidence passages;
- subprocess/install/test/reset/step/materialization counts and durations;
- Builder time to first progress and first write;
- cache/checkpoint/evidence reuse and invalidation counts;
- issue-set/frontier transitions, repair outcomes and backjump distances;
- Integration evidence reuse versus repeated work;
- package/publication byte digests and final maturity.

Missing provider metrics MUST remain explicit unknowns.  Secrets, raw credentials and sealed
test contents MUST never be emitted.

### FR-11: bounded dedicated Agents and tool isolation

Retain exactly three semantic roles unless measurements justify another:

- Researcher: search planning and evidence synthesis, with bounded search/fetch/extract
  tools and isolated search configuration;
- Environment Engineer: semantic Design and real Candidate code generation, with the
  environment-codegen skill and workspace-scoped write/process tools;
- Challenger: adversarial intent only, without Candidate write access or sealed expected
  outcomes.

Role skills, hooks, tools, credentials, network domains and writable roots MUST be resolved
by the InvocationBackend profile adapter, not scattered through pipeline code.

### FR-12: clean-break migration

No compatibility path for old `awm`, Runtime ABI v1, replay fixtures, fixed environment IDs
or historical control Artifacts is required.  Existing live stores remain read-only evidence.
Unreachable microsharded Designer paths and duplicate authority models MUST be deleted after
their replacement regressions pass.

## Non-functional requirements

- Python commands and lock/install/test operations use `uv`.
- Production Agent calls use the real InvocationBackend/Codex adapter and the exact explicit
  configured model. Current live acceptance uses gpt-5.3-codex-spark through an API-key profile
  with a credential-free explicitly materialized base URL; its key and URL are injected only from
  approved environment handles. A different model requires an explicit recorded availability
  decision. No scattered SDK calls or ambient provider selection is permitted.
- A failure in telemetry persistence cannot silently publish an unauditable package.
- Recovery after process interruption is idempotent from durable WorkCommit and ledger state.
- No test may claim product E2E success through a fake invocation backend, mock environment,
  fixed hotel implementation or hand-edited Artifact.

## Acceptance criteria

- [ ] All production feedback boundaries have a checked ten-question executable definition.
- [ ] Leaf failures aggregate into ValidationReport; boundary decisions emit exactly one
      active terminal FeedbackEvaluation per subject/policy revision.
- [ ] FeedbackEvaluation and WorkCommit are the actual inputs to readiness and ClaimVector.
- [ ] Direct and Evolve instantiate the same Design WorkGraph and global RepairLedger path.
- [ ] The shared-tool slot reproduction passes through a real distinct shared contract.
- [ ] Root/generic diagnostics cannot spend an LLM repair turn.
- [ ] Progress, no-progress, regression and A-to-B-to-A oscillation regressions pass.
- [ ] A successful sibling Artifact remains valid after an independent sibling repair.
- [ ] Every semantic retry is authorized once and charged once; no component-owned retry
      counter can grant work.
- [ ] Integration evidence is digest-bound and matching checks are not repeated by Judge.
- [ ] Diagnostic no-rework and retry-node commands run real code and produce non-releasable
      Artifacts.
- [ ] Builder first-progress/write deadlines and terminal observability are executable.
- [ ] Lint, type-check and the complete deterministic suite terminate and pass; the Verifier
      straggler hang is isolated and fixed without weakening cancellation assertions.
- [ ] A real staged run exercises Designer, Builder, Integration, Runtime Reset/Step,
      materializer, Release Judge, packaging and Registry separately.
- [ ] A fresh real request `用户预订宾馆` completes Research through Registry using actual
      search, the explicit gpt-5.3-codex-spark API-key profile, real subprocesses, no mocks and
      no manual Artifact edits.
- [ ] A separate real negative run proves actionable feedback and bounded local rework.
- [ ] The final report includes time/token/search/tool/rework/reuse/invalidation distributions
      and explicitly unknown dimensions.

## Evidence references

The preserved cases and proof classifications are maintained in `audit.md`.  No requirement
may be declared complete from a unit test alone when it makes a real execution claim.
