# EnvironmentRelease/3 Conformance and Publication

## Scope

This is the only path from one frozen actor project to an S2-consumable
EnvironmentRelease/3. It qualifies environment mechanics and persistent world
behavior, not Tasks or rewards.

## Actor roles

The one frozen actor project owns:

```text
public make_environment(instance_directory)
protected read_state(instance_directory)
start/reset/state schemas
environment-specific tests and locked dependencies
```

Generated code never writes the Host conformance receipt, manifest, digest or
publication verdict.

## Conformance receipt

The Host receipt binds at least:

```text
actor project digest
public actor factory
protected state reader factory
start/reset/state schema digests
ToolSpec catalog digest
project test/build evidence digest
reset/replay/persistence/isolation evidence digest
protected-read no-mutation evidence digest
payload evidence digest
```

Every bound evidence item is a Host observation over exact bytes. A reviewer's
prose may reject a candidate but cannot satisfy or rewrite the receipt.

## Publication

The canonical payload contains only:

```text
actor/
conformance/receipt.json
conformance/evidence/
docs/schemas/{start,reset,state}.json
payload-manifest.json
release.json
dist/
licenses/
```

Descriptor and payload path/key sets are exact. TaskSemantics, CapabilitySpecs,
conditions, task goals, StartCases as a Task distribution, checker, verifier,
witness, reward and corpus files are rejected as prohibited members.

Publication verifies all digests, copies exact bytes once, writes canonical
documents and derives the Release ID. No provisional or unqualified release
exists.

## Tests required

- exact v3 descriptor and payload keys;
- actor/state/schema/receipt identity mutations;
- prohibited old semantic/verifier fields and roots;
- symlink/path/mode/extra-member rejection;
- directory and ZIP identity equality;
- cold relocation and same-name release isolation;
- public policy projection cannot discover protected state;
- real filesystem/Git and SQLite conformance;
- mutation licences for every receipt-to-payload binding edge.

## Forbidden

- v1/v2 migration or alternate readers;
- `allow_unqualified` or a format feature flag;
- task-case positive/noop evidence in S1;
- domain-specific Framework checks;
- generated code authorizing its own receipt.
