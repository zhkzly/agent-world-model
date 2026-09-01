# Current S1/S2 evidence baseline

## Retained product evidence

The current baseline contains three real `environment-release/2` products:

| Environment | Release ID | Public tools | Qualified capabilities | Qualification cases |
| --- | --- | ---: | ---: | ---: |
| Git repository maintenance | `14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80` | 6 | 6 | 12 |
| Ocean demurrage dispute (SQLite) | `64fa07e1a144536df2ae3ff9b0cf30175e8b0f913f1e34d8731b8377a80ebb87` | 5 | 4 | 8 |
| Held-out equipment maintenance (SQLite) | `7e2c0718a7de84b07261b729cbe12da86e313c75e4aa107d60ede4c2c34e407a` | 5 | 7 | 14 |

All three strict Qualification receipts have `verdict=passed`.

Their retained S2 product reports contain:

- 42 enumerated candidates;
- 32 per-release unique semantic structures;
- 9 admitted TaskPacks: 4 Atom, 4 ForEach and 1 If;
- two fresh public-only admission witnesses per TaskPack;
- 27 independent `gpt-5.6-luna` assessment trials;
- 26/27 satisfied assessment trials (96.3% model-relative reliability);
- 66 provider turns, 90,188 tokens and 254,403 ms aggregate assessment latency.

Do not report 9/42 as a yield: target-stopping selection did not execute every
enumerated candidate. The existing batch reports retain four actually rejected
attempts with typed causes.

## Current reproducibility gap

`run_task_foundry_product(...)` is the S2 production entry point. S1 exposes
the individual Research, actor Builder, Expected Semantics, TaskSemantics
Author, Verifier Author, Qualification, publication, zip and cold preparation
operations. `.trellis/spec/backend/s1-coordinator.md` explicitly says the
single `generate_environment_v2(...)` API is not yet implemented.

The three baseline releases therefore prove the physical stages and
cross-domain transfer, but not repeatable one-call environment generation. The
campaign must close this specific orchestration gap before collecting scale
claims.

Remote verification on 2026-09-01 found the same completed Direct sampler in
`origin/main@6246740` and `origin/s4-verified-agent-learning@c25dbb3`. The S4
branch adds downstream learning code but does not replace S2 sampling. The
campaign therefore has no license to recreate or redesign Task sampling.

## Repository evidence hygiene

- `README.md` still says S2 is not implemented and must be corrected.
- 367 tests collect at the campaign branch baseline. Two authority tests fail
  only because they still read the archived S2 task from its former active
  path; this stale reference must be corrected before campaign freeze.
- Debug and intermediate `.artifacts` directories are not official campaign
  results. Only reports bound by the frozen campaign manifest may enter new
  statistics.
