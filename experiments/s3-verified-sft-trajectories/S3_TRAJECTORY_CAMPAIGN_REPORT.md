# S3 Verified SFT Trajectory Campaign

## Result and identity

The final campaign consumed the exact S1 campaign
`486dd2349f1eccb2f2ee096447a7c2325e811ecd92b6189722a69ed49a09ad7d`
and the exact 69-member S2 CorpusManifest
`7ce6f07703acf6a60f4c67ff784f18bfac75821f1c47ba979fc7a553288f186e`.
Product source was frozen at
`c38e2a0d685e24a6bae7f515745c840017c9876a`.

Exact output identities:

- campaign: `7884245f6d992fd5673a0c9b6f5e93e183ad6251b9a408c5cf8995b55ec6ced1`;
- Episode batch: `a654e1031f7039e6d9faea58ab592466d9a723d0fb68b60b37f6b7000575e23e`;
- summary: `d87bfe9d51a88b6428fd1d63c951a93de2d5149bce03065b2d0984a5bb0ee153`;
- artifact root:
  `/home/kelong/pycodes/foundry-s3-verified-episodes/7884245f6d992fd5673a0c9b6f5e93e183ad6251b9a408c5cf8995b55ec6ced1`.

## Method

For each TaskPack, Luna executed exactly eight independent logical rollouts on
fresh native instances. The policy received only the frozen public system
prompt, Task instruction, reset observation, ToolSpecs, its own
ToolObservations and the type-only answer schema.

```text
cold Release + cold TaskPack
-> fresh reset
-> real Luna tool-use trajectory
-> close and reopen the same instance without reset
-> protected state readback
-> common Atom/All/If/ForEach Goal evaluator
-> reward 1.0 / 0.0 / null
-> EpisodeRecord/3 + derived TrainingEpisodeView/2
```

S3 did not consume S2 sampling/filter trajectories, compare against a reference
path, generate a Checker, invoke an LLM Judge, or retry until success. Eight
Release workers ran concurrently; turns inside an Episode remained causal and
serial.

## Aggregate results

| Metric | Result |
|---|---:|
| Requested/sealed Episodes | 552 / 552 |
| Verified success | 530 |
| Verified policy failure | 22 |
| Abstain | 0 |
| Pre-Episode blocked | 0 |
| Success rate | 96.0% |
| TaskPack success coverage | 69 / 69 |
| Release success coverage | 20 / 20 |
| Minimum successes for one TaskPack | 5 / 8 |
| Provider turns | 1,769 |
| Real public tool calls | 1,709 |
| Model tokens | 2,918,445 |
| Wall clock | 16 min 10 s |

The 22 failures are retained as valid policy evidence and excluded from the
positive SFT cohort. Reason occurrences were 16 answer mismatches, six Goal
failures, four missing Atom events and two unresolved conditions; one failure
can contain multiple reason codes.

## Trajectory shape and diversity

Verified-success tool-call length was 1–12, with median 2, mean 3.10 and p95 7.
Reconstructed multi-turn SFT rows contained 5–20 messages, median 7.

| Goal shape | Verified success | Verified failure |
|---|---:|---:|
| Atom | 247 | 9 |
| All | 134 | 2 |
| If | 141 | 11 |
| ForEach | 8 | 0 |

Successful Goals contained 284 query, 196 transition and 112 refusal Atom
memberships. The 530 successful rollouts reduce to 132 distinct normalized
`(TaskPack, action+argument sequence, final answer)` routes. Per TaskPack this
ranges from one to eight routes with median one. Therefore 530 is the verified
raw success count, not a claim of 530 semantically distinct SFT examples; S4
must own deduplication and curation.

## Artifact and SFT-view verification

Every one of the 552 EpisodeRecord/TrainingEpisodeView pairs passed strict cold
read. Each pair was copied alone into a fresh temporary root and cold-read
again. IDs and trusted-to-public projection remained stable.

All 530 successes were mechanically reconstructed as:

```text
system
user(instruction + reset observation)
assistant(function call)
tool(real ToolObservation)
...
assistant(final structured answer)
```

Every successful call was schema-validated and dispatched, with a real
observation. Public-view traversal found zero Goal truth, expected answer,
protected before/after state, S2 sampling/reference/filter evidence or
evaluator leakage.

The trusted Episode records total 11,080,248 bytes and the public training views
8,391,149 bytes. Their paired distribution payload is 19,471,397 bytes. The
full campaign root is about 2.08 GB because it intentionally retains isolated
native instances and preparation caches; those are not SFT distribution data.

## Failure-derived correction

An earlier diagnostic campaign completed 552 slots with 520 success, 18 policy
failure and 14 provider abstentions. It exposed that the existing public capture
discarded already-derived provider exception details. The current source now
binds those details into trusted `EpisodeRecord/3`, rejects `/2`, and keeps the
public `TrainingEpisodeView/2` unchanged. The final campaign then completed
with zero abstention or blocked slots. The earlier campaign remains diagnostic
evidence and was not overwritten or relabelled.

## Claim boundary and next consumer

This result establishes real multi-Release Episode collection, complete public
interaction capture, post-reopen deterministic task reward and non-leaking,
tokenizer-neutral SFT-ready views.

S4 still owns:

```text
select reward=1 views
-> quality and action-route deduplication
-> target-specific messages/tools projection
-> exact chat template and tokenizer
-> assistant-only loss mask
-> Parquet and real SFT training
```

No model-improvement or training claim is made by this campaign.
