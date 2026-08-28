# S2 validation

This document separates checks that are reproducible without model credentials
from live checks that require the operator's actual provider route. Skipping a
live check is never reported as a pass.

## 1. Deterministic repository validation

From the repository root:

```bash
bash scripts/validate_s2_deterministic.sh
```

This runs the exact locked dependency sync, Ruff lint and formatting checks,
strict mypy, and the complete pytest suite. It requires no OpenAI credential and
must pass before diagnosing a model integration problem.

## 2. Provider prerequisites for live runs

The current Foundry routes require an operator-supplied OpenAI-compatible
Responses endpoint and credential:

```bash
export OPENAI_BASE_URL='http://127.0.0.1:8317/v1'   # replace with the real route
export OPENAI_API_KEY='...'
```

The configured model must support the Responses API and structured function
tool calls. Codex code generation additionally requires the Python Codex SDK
runtime and the model/provider mapping used by the repository configuration.
Secrets must not be committed to the repository, test fixtures, TaskPacks, CI
logs, or release artifacts.

## 3. Live-model ownership

Two different model mechanisms are intentional:

- **Python Codex SDK:** writes persistent release-local code in isolated
  workspaces—the actor environment and the protected TaskSemantics project.
- **OpenAI Responses function-tool loop:** acts through the public environment
  surface for constructive witness runs and independent TaskAssessment trials.

Framework Python—not either model—owns schemas, identities, checker compilation,
canonical instruction rendering, public tool dispatch, trace capture, operand
provenance, challenge verdicts, TaskPack sealing, and corpus selection.

## 4. Required live evidence before claiming S2 completion

A real live run must retain exact identities and evidence for:

1. S1 v2 actor and TaskSemantics code generation;
2. independent semantic Qualification with physical near misses;
3. cold release preparation and actor/semantics runtime isolation;
4. checker and final instruction freeze before witness execution;
5. two successful fresh public executions of the exact instruction;
6. no hidden acting operand in either execution;
7. applicable no-op, wrong-target, boundary, partial, collateral, answer and
   process challenges;
8. a valid alternative public path when one is available;
9. independent TaskAssessment policy/model identity and actual cost;
10. SQLite, filesystem/Git, and post-freeze held-out release evidence.

A provider timeout, quota failure, unsupported tool-call format, or missing
credential is `InfrastructureFailure`. It must not be converted into Task
success, high difficulty, a canned trace, or a fake provider result.

## 5. Operator workflow

```bash
git switch s2-task-foundry
git pull --ff-only
bash scripts/validate_s2_deterministic.sh

# Then configure the real provider variables and run the live S1/S2 commands
# documented by the implemented CLI. Preserve the run directory and do not
# edit generated release/Task evidence between retries.
```

The deterministic command is available immediately. Live S1 v2/S2 command
examples become authoritative only when their corresponding implementation
checkpoint exists; documentation must not advertise a placeholder command as a
completed feature.
