# Live proof — SharedTool to first ToolSemantics

- Date: 2026-08-12
- Result: **allow one fresh public Direct E2E**
- Diagnostic run: `run_d1fcdd4d28264a1c965f318211a34582`
- Exact immutable parents from `run_1bec958e41ae4207beb4a7b40149f9c0`:
  - Evidence `sha256:8cea941a9168ce533952de99f7c0b566f6ed33ebc5b9f08149415ec03ad0b757`
  - Architecture `sha256:8b0f1bcda8f37a24aeb2c11ffebdb4beb3a3baffda2c1b4dd3a65cfca497db60`

## Safe result

- Real Luna SharedTool used one bounded correction at `$.error_policy` with
  `value must use at most 280 code points`, then committed
  `design.shared_tool_semantics:665863793a9f5801`.
- Real Luna `tool_semantics[register_member]` passed on its first call and
  committed `design.tool_semantics:edcc50cb6b7be4a8`.
- Observe reports exactly two passed Direct-LLM Works, no Findings and
  `release=not_published`.
- The harness stopped before the second tool. No Agent, Skill, workspace,
  candidate process, Judge, Registry or release path ran.

Framework retained frozen coordinates, exact compiler, correction bound,
Work/Artifact and release authority. This diagnostic is non-resumable,
non-adoptable and non-publishable. It proves only the repaired SharedTool and
immediate first-tool consumer boundary; it does not prove remaining Design,
Candidate, Judge, Registry, public Direct E2E, Repair, Expand or Consumer/SFT/RL.

