# S1 EnvironmentRelease/3 — 20-Need Campaign

## Scope and identity

This campaign executed the exact 20-Need `need-suite/1` at
`0b80720439e271fea441585d010b39907e3de2824010f1f29d68c9a90294b294`
against product source `1396cc5ebff71c0e32fa5102f758be07ddf6e33a`.
The retained artifact root is outside the repository at:

```text
/home/kelong/pycodes/foundry-s1-v3-20need-campaign/
  e772f8032cbaf166d0edb4a6f119627cc63c0b25e93ca6fef5b02f2e4b6d4586/
```

This is S1 environment-generation evidence. It does not claim that S2 has
generated or admitted Tasks, that rewards are correct, or that SFT/RL improves
a model.

## Final result

- 20/20 Needs have a current, unique cold EnvironmentRelease/3.
- 204 structured public tools were generated (10.2 per environment).
- Generated actors contain 2,961 nonblank non-comment Python LOC.
- Generated projects contain 63 test functions.
- The 20 deterministic Release ZIPs total 506,217 bytes.
- The campaign retained 42 attempt directories, including infrastructure and
  semantic failures rather than reporting only the final successes.
- End-to-end wall time with bounded concurrency and repair was about 3 h 23 m.

| Metric | Mean | P50 | P95 |
|---|---:|---:|---:|
| End-to-end per final Need | 14.69 min | 13.83 min | 21.19 min |
| Research | 8.97 min | 7.61 min | 16.02 min |
| Codex Builder | 4.62 min | 4.51 min | 6.15 min |
| Environment Conformance | 0.661 s | 0.612 s | 0.740 s |
| Publication | 0.074 s | 0.076 s | 0.083 s |
| Cold preparation | 0.330 s | 0.326 s | 0.357 s |

## Per-environment output

| Need | Domain | Final attempt | Tools | LOC | Tests | ZIP KB | Release ID |
|---|---|---:|---:|---:|---:|---:|---|
| 01 | library circulation | 1 | 7 | 140 | 2 | 23.6 | `7db220339c5a…` |
| 02 | warehouse inventory | 1 | 6 | 160 | 3 | 23.3 | `76add86433df…` |
| 03 | employee expense reimbursement | 2 | 6 | 137 | 4 | 24.6 | `f8fe65105b14…` |
| 04 | IT application access | 1 | 7 | 106 | 3 | 23.5 | `6ef729959d59…` |
| 05 | customer support tickets | 1 | 9 | 151 | 2 | 24.2 | `c57b7928b358…` |
| 06 | outpatient appointment scheduling | 1 | 7 | 180 | 2 | 24.7 | `44480504e134…` |
| 07 | retail returns and refunds | 1 | 11 | 123 | 3 | 24.2 | `2c5344a8d498…` |
| 08 | procurement purchase orders | 3 | 13 | 147 | 2 | 24.8 | `2b4ed3951f4d…` |
| 09 | service incident management | 2 | 13 | 127 | 2 | 23.9 | `d0f675cd77f9…` |
| 10 | software subscriptions | 2 | 18 | 131 | 4 | 24.6 | `c22de18c58c5…` |
| 11 | Git release preparation | 2 | 7 | 136 | 3 | 23.5 | `9ff6e047d020…` |
| 12 | controlled document review | 2 | 7 | 121 | 2 | 24.7 | `cc97315fef4a…` |
| 13 | laboratory samples | 3 | 12 | 146 | 5 | 25.8 | `cbedac5055a1…` |
| 14 | vehicle fleet compliance | 2 | 7 | 136 | 4 | 25.1 | `5b12b9352b5…` |
| 15 | campus equipment loans | 2 | 13 | 176 | 3 | 24.7 | `8f20da1f212b…` |
| 16 | small insurance claims | 3 | 13 | 171 | 3 | 25.7 | `7034ddf14f83…` |
| 17 | restaurant table reservations | 2 | 12 | 160 | 4 | 24.7 | `37a82a48465d…` |
| 18 | shipment customs documents | 3 | 10 | 171 | 4 | 28.4 | `0763b004b915…` |
| 19 | course enrollment and waitlists | 4 | 9 | 129 | 4 | 24.2 | `070105cbad51…` |
| 20 | rental property maintenance | 4 | 17 | 213 | 4 | 26.2 | `cfd830e58003…` |

## Failure and recovery audit

| Failure class | Count | First causal deviation | Resolution |
|---|---:|---|---|
| Provider auth unavailable | 13 attempts | Concurrency 3 exceeded currently available 8317 authentication capacity; immediate retries consumed the Research turn budget | Recovery used concurrency 2, then 1 for unstable retries; campaign default is now 2 and auth-unavailable is terminal for one Research invocation |
| Provider timeout/TLS | 2 attempts | One Evidence Reviewer timed out; one upstream TLS handshake failed repeatedly | Fresh attempts at concurrency 1; every provider turn already has a 180 s timeout and no hidden SDK retry |
| Nullable state schema | 1 candidate | A legitimate `null` value was declared only as `string` | Codex repaired the state schema and added full reset/post-transition schema tests before a new Release identity was issued |
| Reset wall clock | 1 candidate | Reset seeded rows using ambient current time | Codex replaced it with a reset-owned logical clock and proved cross-instance replay |
| Transition wall clock | 5 accepted candidates | Default-reset Conformance did not inspect ambient time used only by later mutations | Post-release audit superseded all five Releases with deterministic-clock actors; an AST preflight now rejects ambient entropy before Builder completion |

The audit also found two generated projects whose tests did not visibly load
`state.json`. Fresh Host-side workflows for support tickets and incident
response executed every relevant mutation through the released proxy; every
post-transition protected snapshot validated and remained stable after reopen.

## Context-engineering changes derived from evidence

1. Framework safely canonicalizes only fixed ABI facts: a missing input-object
   root and an exact ToolObservation wrapper mistakenly placed around the
   success-data schema.
2. Builder preflight now runs the complete task-neutral reset/readback/replay
   Conformance while the Codex thread can still repair factual failures.
3. An AST gate rejects ambient wall clock, random UUID, OS entropy and unseeded
   randomness in generated actor source.
4. The runtime Skill explicitly requires nullable schema coverage, a
   reset-owned logical clock/counter/seed, identical two-instance action replay,
   and complete post-transition `state.json` validation.
5. Framework reports semantic counterexamples to Codex but does not silently
   widen a domain schema from `string` to `string | null`.
6. Future campaign attempts receive independent terminal records, so later
   success cannot erase an earlier failure. This campaign predates that fix;
   its 42 attempt directories are supplemented by the consolidated failure
   audit in this report.

After the campaign, these findings also produced one task-free Host diagnostic
carrier. A fresh Codex library canary authored two scenarios with nine real
steps; Framework executed both in two independent instances and issued cold
Release `f94bd24e18a393838789ff621b485c078c0966f84d24bcbb94623cbf5a8ae41b`.
The scenarios contain no instruction, answer, reward, checker or witness.

## Final audit boundary

All 20 current Release directories cold-verified with unique IDs. A fresh raw
catalog audit found zero tools depending on input-root or output-envelope
normalization, and a source audit found zero current actors using ambient
clock/random/UUID calls. These checks strengthen S1 evidence; S2 must still
independently establish Task solvability, checker/reward correctness and
training utility.
