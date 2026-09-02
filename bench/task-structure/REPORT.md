# Task-structure guard benchmark

Date: 2026-09-03

This benchmark replays the first complete 15-candidate Library campaign. The
source run used commit `836e472`, campaign `a8575b70...d1e302`, and the immutable
artifact root:

```text
/home/kelong/pycodes/foundry-s2-qualified-20need-task-campaign/
  a8575b7073531ae9a630e5c3202ac17bfdd10eeb673f53b67f35c0d190d1e302/
  needs/need-01-library-circulation/attempts/attempt-001/sampling
```

## Invariants

1. Entity substitutions, paraphrases, inspection order, and answer-field labels
   do not create a new task structure when the required state effect is the same.
2. A materially different state-transition lifecycle or refusal outcome remains
   distinct.
3. Deduplication runs before checker authoring and fresh witness execution.

## Gold cases

Manual inspection of all 15 public instructions and their real before/after
states found two structures:

- `single-checkout`: attempts 1, 2, 4-7, 9-13, and 15;
- `checkout-then-return`: attempts 3, 8, and 14.

Attempts 1 and 3 are the first representatives. The remaining 13 candidates are
duplicates of an earlier representative. All 13 packages admitted by the old
guard cold-verified under their pinned source; the benchmark does not relabel a
broken package as a duplicate.

## Result

| Guard | Duplicate interceptions | Duplicate recall | Unique false positives |
|---|---:|---:|---:|
| `836e472` public-trace/answer-field identity | 2 / 13 | 15.4% | 0 / 2 |
| `d458fa9` effect-shape identity | 13 / 13 | 100.0% | 0 / 2 |

The two-member unique set is only a false-positive smoke test, not a cross-domain
estimate. The next live campaign must test the guard on additional Releases.

Under replay of the completed report, rejecting the 11 previously admitted
duplicates before checker construction would have avoided 2,829,422 ms of
post-proposal work: 2,520,365 ms of checker construction and 305,560 ms of fresh
solves. The source run itself took 3,863,488 ms, used 521,047 reported model
tokens, and made 292 public tool calls.

## Guard self-check

The repository tests contain distilled versions of the real Library failure:

- same transition with different wording, inspection order, report fields, and
  selected array position must collide;
- checkout and checkout-then-return must differ;
- different refusal codes must differ;
- a repeated accepted objective must be visible to the next proposal turn.

Mutation checks independently removed array-position normalization, bypassed the
effect branch, erased prior-task proposal context, and stopped the sampler from
forwarding that context. Each mutation made the focused tests fail and restoration
made them pass.

## Live post-fix campaign

Commit `662c22f` ran a fresh 15-candidate campaign against independently
regenerated Library Release `6a61f3e0...bc8c0` (campaign
`91ffc873...896273`). It admitted 10 Tasks with 10 distinct structure IDs and
rejected five candidates: four failed their fresh checker and one was a real
duplicate. The admitted set covers successful mutation, multi-step lifecycle,
two different refusal regimes, state-preserving reconciliation queries, a
two-checkout capacity transition, borrower handoff, and a mixed
success/refusal/return trajectory.

Compared with the old campaign's manually corrected 2/15 effective-structure
yield, the live post-fix yield is 10/15: a 5x increase, or +53.3 percentage
points. All 10 TaskPacks were copied to a new filesystem root and cold-verified
with 10 unique package IDs, 10 unique structure IDs, and 20 distinct passing
witnesses.

The live campaign took 6,235,981 ms and reported 949,384 model tokens and 305
public tool calls. Its wall time is not a clean latency comparison with the old
run: it shared the local provider with simultaneous S1 generation, and one
checker turn visibly queued behind that work. The diversity/yield comparison is
the supported result; a throughput claim requires a matched-concurrency run.
