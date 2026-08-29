# Checkpoint B mutation licences

Each row was executed with `mutation_license.py`; the focused test became RED
under the injected defect and returned GREEN after byte restoration.

| Target | Killed defect |
| --- | --- |
| `builder.py` | canonical reset-schema path changed to an unbound path |
| `verifier_inputs.py` | v2 surface staging replaced by a legacy v1 document |
| `verifier_author.py` | receipt removed from prohibited output tokens |
| `verifier_author.py` | native-tree mutation comparison disabled |
| `verifier_author.py` | frozen report-field comparison disabled |
| `verifier_author.py` | post-test/factory authority-artifact rescan removed |
| `verifier_author.py` | verifier-project tree mutation comparison removed |
| `verifier_author.py` | verifier project file mode removed from identity |
| `semantics_author.py` | semantics project file mode removed from identity |
| `verifier_author.py` | pre-repair current-project digest check disabled |
| `verifier_author.py` | invocation accepted-project digest check disabled |
| `verifier_author.py` | resolved before/after instance alias check disabled |
| verifier contract | initial Task truth changed to capability readiness |
| verifier contract | required report values allowed to be empty |
| TaskSemantics contract | initial Task truth changed to capability readiness |

These fifteen licences cover deterministic enforcement only. The real authoring and
physical matrix are separately recorded in `checkpoint-b-live-evidence.md`.
