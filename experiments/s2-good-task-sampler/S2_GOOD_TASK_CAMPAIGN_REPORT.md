# S2 Good-Task Sampler — 20-Release Campaign

## Result and identity

The final run consumed the frozen S1 `EnvironmentRelease/3` campaign
`486dd2349f1eccb2f2ee096447a7c2325e811ecd92b6189722a69ed49a09ad7d`
using product source commit
`14f76fc1b8f685dbbef7d39ef058a89c3350313f`.

Exact retained identities:

- campaign configuration: `4453f83c7126724c6e695dd3ee402c270d30e652dcf8d2a1425a0a94aefb08b8`;
- result summary: `ae8f2b4c2baa21b47755ab3dc42cc6168a73399f66c0ebdca9ceb39803dd1747`;
- corpus manifest: `7ce6f07703acf6a60f4c67ff784f18bfac75821f1c47ba979fc7a553288f186e`;
- external evidence root:
  `/home/kelong/pycodes/foundry-s2-good-task-20release-final-v5/4453f83c7126724c6e695dd3ee402c270d30e652dcf8d2a1425a0a94aefb08b8`.

The configuration ID deliberately excludes runtime worker count. Because
model sampling is stochastic, the summary and corpus-manifest IDs—not the
configuration ID alone—identify this exact result.

## Method

For every released environment, Framework selected under-covered Goal shape,
focus-tool and outcome obligations. A generic Sampling Agent used only public
`reset`, ToolSpecs and `invoke` observations. An off-target execution remained
rejected but could steer the next fresh target; no Tool Graph or random walk
prescribed a tool chain.

An accepted path was:

```text
real public execution
→ grounded TaskDraft and minimal AnswerProjection
→ Host argument provenance and protected state capture
→ fresh reference replay
→ common Atom/All/If/ForEach evaluator
→ five independent public Agent runs
→ at least two passes
→ checker-free canonical TaskPack
```

Every Release completed 15 base attempts. A bounded recovery budget was
available only for a Release with zero TaskPacks, but the final run needed zero
recovery attempts. Release-level concurrency was eight; the five filter runs
inside one Candidate remained serial and independent.

## Aggregate results

| Metric | Result |
|---|---:|
| Release coverage | 20 / 20 |
| Base attempts | 300 |
| Sampled drafts | 125 |
| Fresh-replay Candidates | 89 |
| Admitted unique TaskPacks | 69 |
| End-to-end attempt yield | 23.0% |
| Candidate admission | 77.5% |
| Fresh policy passes | 332 / 440 (75.5%) |
| Framework defects | 0 |
| Infrastructure failures | 0 |
| Recovery attempts | 0 |
| Wall clock | 44 min 8 s |
| Total model tokens | 9,057,557 |
| Total public tool calls | 2,944 |
| Mean tokens per admitted Task | 131,269 |

Terminal attempts were retained rather than overwritten: 200 Draft rejections,
19 policy-filter rejections, 11 explicitly unsupported targets, one duplicate
structure and 69 admissions.

## Diversity

| Dimension | Count |
|---|---:|
| Atom | 32 |
| All | 17 |
| If | 19 |
| ForEach | 1 |
| Query | 28 |
| Transition | 25 |
| Refusal | 16 |

The scheduler attempted 202 of 206 Release-scoped public tool identities;
admitted Tasks used 74 distinct Release-scoped objective-tool identities. All
69 accepted structures were unique under Goal/tool/binding/effect/answer-shape
identity. Per-Release output ranged from one to six TaskPacks.

## Representative retained Tasks

- **Atom / transition — clinic appointments**
  (`0c287d10b87d…`): cancel exact appointment
  `appointment-cancellable-001`, then report the cancelled appointment and
  reopened slot.
- **All / query — product returns** (`1d77819bc895…`): list the delivered order,
  inspect it, and report its order ID, status and line-item IDs. Filter result:
  5/5.
- **If / transition — course enrollment** (`01f49abcf528…`): if Foundations has
  exactly two remaining seats, drop Alice's enrollment. Filter result: 3/5.
- **ForEach / query — property maintenance** (`713f97470143…`): retrieve complete
  public details for every visit in the public visit list. Filter result: 5/5.

## Artifact verification

All 69 TaskPacks were cold-read from the campaign, copied one at a time to a
fresh temporary location and cold-read again. Every TaskPack ID, structure ID
and Release binding remained stable. Rebuilding the CorpusManifest and summary
from retained terminal records produced equal documents. Public views exposed
only task/release identity, instruction and type-only final-answer schema;
searches found zero Goal truth, expected answer, replay, protected state,
sampling evidence or Checker leakage.

The 69 published TaskPacks total 3,716,784 bytes (mean 53,866; median 53,149).
The larger campaign directory also retains isolated environments, caches and
all rejected-attempt evidence and is intentionally not the distribution
payload.

## Failure-derived corrections and concurrency evidence

The final source includes corrections established by earlier retained runs:

- generic `result` answer fields made five correct state transitions fail;
  direct answer fields now name their public source leaf;
- exact-condition tool binding rejected equivalent public routes; alternate
  conditions now require the same field anchored to the same target entity;
- repeated condition queries could create fake If Tasks and are rejected
  before Candidate creation;
- ambiguous free-text arguments require explicit literal spelling while IDs,
  paths, versions and ISO timestamps remain usable;
- missing AnswerProjection pointers now become typed Draft rejections instead
  of raw `KeyError` Framework defects;
- transport `ok` cannot become Task answer truth, and answer projections are
  instructed to remain minimal and observation-grounded.

Concurrency stress is retained separately. Twenty Release workers produced
clustered HTTP 429 responses. A later 12-worker run also entered a rate-limit
cascade. The final eight-worker run completed with zero infrastructure failure.
These results measure the current local provider route, not a universal CPU or
architecture limit.

## Limitations and claim boundary

ForEach remains under-represented: one admission from 73 attempts. The high
Draft rejection count also shows that Sampling-Agent contract adherence is the
main remaining efficiency target. One accepted document-list Task exposed an
S1 ToolSpec with a semantically unnecessary required argument; S2 can verify
public execution and recoverability but does not prove every generated S1 tool
argument is causally necessary.

This campaign establishes S2 Task sampling, public solvability, fresh replay,
common deterministic evaluation, 2-of-5 recoverability and checker-free
TaskPack publication across 20 environments. It does not claim S3
trajectory/reward integration, training-data emission, or downstream SFT/RL
improvement.
