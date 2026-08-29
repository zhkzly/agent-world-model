# Checkpoint A Mutation Licences

Date: 2026-08-29

Every row was executed with
`python3 /home/kelong/ai-workbench/tools/mutation_license.py`. The tool observed
GREEN, injected the listed behavior error into the exact target, observed RED,
restored the pre-mutation bytes, and observed GREEN again.

| ID | Target | Behavior mutant | Acceptance command | Result |
| --- | --- | --- | --- | --- |
| S1 | `semantics.py` | reject non-null `task_literal.value` | `.venv/bin/python -m pytest -q tests/test_checkpoint_a_semantics.py` | killed/restored |
| S2 | `semantics.py` | accept missing tool name | same as S1 | killed/restored |
| S3 | `semantics.py` | skip exact public-leaf coverage | same as S1 | killed/restored |
| S4 | `semantics.py` | skip literal value ↔ public leaf equality | same as S1 | killed/restored |
| S5 | `semantics.py` | weaken exact selected siblings to subset | same as S1 | killed/restored |
| S6 | `semantics.py` | ignore current request/binding equality | same as S1 | killed/restored |
| S7 | `semantics.py` | accept publicly indistinguishable semantic keys | same as S1 | killed/restored |
| Q1 | `qualification_contracts.py` | remove verifier digest from Core sensitivity | `.venv/bin/python -m pytest -q tests/test_checkpoint_a_qualification_contracts.py` | killed/restored |
| Q2 | `qualification_contracts.py` | accept a non-passed receipt | same as Q1 | killed/restored |
| Q3 | `qualification_contracts.py` | skip StartCase/schema validation | same as Q1 | killed/restored |
| Q4 | `qualification_contracts.py` | skip receipt/Core equality | same as Q1 | killed/restored |
| Q5 | `qualification_contracts.py` | accept a non-fixed verifier factory | same as Q1 | killed/restored |
| Q6 | `qualification_contracts.py` | accept non-boolean result axes at decoder and dataclass boundaries | same as Q1 | killed/restored |
| Q7 | `qualification_contracts.py` | accept unknown keys in exact decoders | same as Q1 | killed/restored |
| Q8 | `qualification_contracts.py` | ignore sealed ToolSpec catalog digest | same as Q1 | killed/restored |
| M1 | `models.py` | allow duplicate logical semantic keys | `.venv/bin/python -m pytest -q tests/task_foundry/test_checkpoint_a_models.py` | killed/restored |
| M2 | `models.py` | allow a tool-output source without event sequence | same as M1 | killed/restored |
| M3 | `models.py` | bypass AdmissionReport/AdmissionPlan coverage | same as M1 | killed/restored |
| M4 | `models.py` | omit conversation identity from Episode identity | same as M1 | killed/restored |
| M5 | `models.py` | let TaskDefinition and checker bind different logical refs | same as M1 | killed/restored |
| M6 | `models.py` | let TaskDefinition and checker bind different logical selections | same as M1 | killed/restored |
| M7 | `models.py` | omit selector/cardinality from LogicalSelection digest | same as M1 | killed/restored |
| M8 | `models.py` | skip occurrence-to-real-trace validation | same as M1 | killed/restored |
| M9 | `models.py` | allow an applicable checker mutant to be unreachable | same as M1 | killed/restored |
| M10 | `models.py` | skip fresh witness resolution-set equality | same as M1 | killed/restored |
| M11 | `models.py` | skip literal value ↔ frozen instruction equality | same as M1 | killed/restored |
| M12 | `models.py` | let TaskPack omit AdmissionPlan validation | same as M1 | killed/restored |
| M13 | `models.py` | let TaskPack accept wrong ordering artifact digests | same as M1 | killed/restored |
| M14 | `models.py` | conflate each member slot with the shared selector ID | same as M1 | killed/restored |
| M15 | `models.py` | skip exact LogicalSelection member-set validation | same as M1 | killed/restored |
| M16 | `models.py` | skip Blueprint Goal→selector/cardinality validation | same as M1 | killed/restored |
| M17 | `models.py` | allow checker GoalProgram to differ from Blueprint | same as M1 | killed/restored |
| M18 | `models.py` | skip Task Goal→logical slot/capability validation | same as M1 | killed/restored |
| M19 | `models.py` | replace ordered member equality with set equality | same as M1 | killed/restored |
| M20 | `models.py` | compare fresh witness resolutions as a set instead of frozen order | same as M1 | killed/restored |
| M21 | `models.py` | allow Goal to leave a frozen logical binding unused | same as M1 | killed/restored |
| M22 | `models.py` | let AllGoal consume one logical slot more than once | same as M1 | killed/restored |
| M23 | `models.py` | let TaskDefinition/checker answer schemas differ | same as M1 | killed/restored |
| M24 | `models.py` | accept an arbitrary checker task-preimage digest | same as M1 | killed/restored |
| M25 | `models.py` | let both witnesses use a different StartCase than the TaskDefinition | same as M1 | killed/restored |
| M26 | `models.py` | allow `exactly_one`/`any_one` selections to freeze multiple members | same as M1 | killed/restored |

Two narrower mutants initially survived: deleting only the explicit missing-tool
guard and deleting only the dataclass boolean check. In both cases a second
independent validation layer still rejected the same external input, so behavior
did not change. They were replaced by behavior-level S2 and Q6 above; neither
survivor is counted as a licence.

Two attempted mutation shell commands were rejected before changing bytes due
to invalid `sed` range syntax. They are not licences; valid behavior-level M18
and M19 commands were subsequently executed and killed.

One inverse-selector mutant later survived because exact binding membership
already made the selector check behaviorally redundant. The duplicate check was
deleted; the minimal sufficient unused-binding invariant is covered by M21.
