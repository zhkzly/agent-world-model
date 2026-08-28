# CP1 YES/NO Checklist

- [x] Does every new object have one named producer and consumer?
- [x] Are release, actor runtime, semantics runtime and materialization identities non-circular and content-bound?
- [x] Does the current v1 release fail the v2 admission contract?
- [x] Can the public projection deserialize no trusted field?
- [x] Can trusted calls be represented without implying state mutation or actor import access?
- [x] Are all non-success outcomes typed instead of collapsed into booleans/strings?
- [x] Are Graph/Programmatic, compatibility, domain templates and CP5–CP7 paths still absent?
- [x] Does each acceptance test fail before implementation and kill its corresponding mutant?
- [x] Do locked sync, Ruff, format, Mypy and full Pytest pass after implementation?

## CP2 Physical Runtime Checklist

- [x] Do directory and ZIP inputs admit only exact v2 bytes?
- [x] Are actor and semantics installed and executed by different locked venv interpreters?
- [x] Can same-named packages from two releases remain live without aliasing?
- [x] Does open/reopen preserve state without implicit reset?
- [x] Are project bytes, editable origins and both import directions checked at every open?
- [x] Does every trusted call produce before/after manifests and reject mutation-on-error?
- [x] Are stdout noise, seq mismatch, timeout and startup failure fail-closed and correctly owned?
- [x] Do focused physical tests, mutation licenses and the full repository gate pass?

## CP3A Expected TaskSemantics Freeze Checklist

- [x] Does the fresh typed turn see accepted Need/Requirement relations but no Candidate,
  native state, source revisions, Task, trace, answer or verdict?
- [x] Must every projected Requirement, including initial-world relations, receive exactly one
  Taskable/NotTaskable/Unsupported disposition?
- [x] Can capabilities reference only Taskable Requirements and their licensed workflows?
- [x] Are composition and public condition records non-empty in the acceptance fixture and
  anchored to known capabilities, Requirements and workflows?
- [x] Does one rejection report every currently observable semantic finding and require a full
  replacement document?
- [x] Is the RFC 8785 payload digest stable under semantically irrelevant record ordering?
- [x] Do focused tests kill coverage, completeness, reference, ordering, leakage, feedback and
  provider-schema mutants?
- [x] Did a real Luna strict-JSON turn accept the schema and produce a Host-frozen result from
  accepted S1 relations?
