from __future__ import annotations

import json
import stat
from collections import Counter
from pathlib import Path

import pytest
from pydantic import BaseModel, JsonValue, ValidationError

from agent_world.artifact_store import (
    ArtifactIntegrityError,
    ArtifactStore,
    ArtifactStoreError,
    ArtifactWriter,
    UnsafeArtifactError,
)
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    EvaluatorGoalBinding,
    KeyValue,
    PublicSelfCheckDescriptor,
    ReleaseProfile,
    Rule,
    RuleClause,
    RuleValueRef,
    TaskMaterializerDescriptor,
    TaskRequirement,
    canonical_json_bytes,
    sha256_digest,
)


def _test_writer(store: ArtifactStore) -> ArtifactWriter:
    return store.issue_writer(
        producer="artifact-contract-test",
        allowed_artifact_types=(
            "build.curriculum",
            "build.task_materialization_schema",
            "control.payload",
            "control.subject",
            "environment_design",
            "evidence",
            "source.workspace",
            "source_workspace",
        ),
        allowed_event_types=("unsafe_event",),
    )


def _diamond_artifact_refs(writer: ArtifactWriter) -> tuple[ArtifactRef, ...]:
    leaf = writer.put_json(
        artifact_id="subject:diamond-leaf",
        artifact_type="control.subject",
        value={"node": "leaf"},
    )
    left = writer.put_json(
        artifact_id="subject:diamond-left",
        artifact_type="control.subject",
        value={"node": "left"},
        dependencies=(leaf,),
    )
    right = writer.put_json(
        artifact_id="subject:diamond-right",
        artifact_type="control.subject",
        value={"node": "right"},
        dependencies=(leaf,),
    )
    root = writer.put_json(
        artifact_id="subject:diamond-root",
        artifact_type="control.subject",
        value={"node": "root"},
        dependencies=(left, right),
    )
    return leaf, left, right, root


class _ArtifactNode(BaseModel):
    node: str


def test_contract_json_and_hash_are_canonical_and_models_are_closed() -> None:
    left = {"z": [3, 2, 1], "a": {"later": False, "first": True}}
    right = {"a": {"first": True, "later": False}, "z": [3, 2, 1]}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_digest(canonical_json_bytes(left)) == sha256_digest(canonical_json_bytes(right))

    budget = Budget(agent_turns=2, wall_seconds=30.0)
    assert (
        budget.content_digest()
        == Budget(
            wall_seconds=30.0,
            agent_turns=2,
        ).content_digest()
    )
    with pytest.raises(ValidationError):
        Budget.model_validate({"agent_turns": 2, "unknown_dimension": 1})
    with pytest.raises(ValidationError):
        Budget.model_validate({"agent_turns": "2"})
    with pytest.raises(ValidationError):
        budget.agent_turns = 3  # type: ignore[misc]


def test_artifact_store_commits_immutable_revisions_and_dependency_dag(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = _test_writer(store)
    source = writer.put_json(
        artifact_id="evidence:source",
        artifact_type="evidence",
        value={"claim": "observed", "source": "https://example.test/reference"},
    )
    design_v1 = writer.put_json(
        artifact_id="design:inventory",
        artifact_type="environment_design",
        value={"revision": 1, "tools": ["inventory.reserve"]},
        dependencies=(source,),
    )
    same_design = writer.put_json(
        artifact_id="design:inventory",
        artifact_type="environment_design",
        value={"tools": ["inventory.reserve"], "revision": 1},
        dependencies=(source,),
    )
    design_v2 = writer.put_json(
        artifact_id="design:inventory",
        artifact_type="environment_design",
        value={"revision": 2, "tools": ["inventory.reserve", "inventory.release"]},
        dependencies=(source,),
    )

    assert same_design == design_v1
    assert design_v2.revision_id != design_v1.revision_id
    assert store.dependencies(design_v1) == (source,)
    assert set(store.dependents(source)) == {design_v1, design_v2}
    assert store.get_json(design_v1) == {
        "revision": 1,
        "tools": ["inventory.reserve"],
    }
    assert store.get_json(design_v2)["revision"] == 2
    assert set(store.list_revisions("design:inventory")) == {design_v1, design_v2}
    assert [event.event_type for event in store.list_events()].count(
        "artifact_revision_committed"
    ) == 3


def test_list_revisions_builds_one_verified_index_and_tracks_new_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = _test_writer(store)
    first = writer.put_json(
        artifact_id="design:indexed",
        artifact_type="environment_design",
        value={"revision": 1},
    )

    assert store.list_revisions("design:indexed") == (first,)

    def forbidden_rescan():  # type: ignore[no-untyped-def]
        raise AssertionError("an initialized revision index must not rescan the store")

    monkeypatch.setattr(store, "_iter_revisions", forbidden_rescan)
    assert store.list_revisions("design:indexed") == (first,)

    second = writer.put_json(
        artifact_id="design:indexed",
        artifact_type="environment_design",
        value={"revision": 2},
    )
    assert set(store.list_revisions("design:indexed")) == {first, second}
    assert set(store.list_revisions()) == {first, second}


def test_exact_revision_projection_survives_process_reopen_without_history_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    store = ArtifactStore(root)
    writer = _test_writer(store)
    expected = writer.put_json(
        artifact_id="design:persistent-index",
        artifact_type="environment_design",
        value={"revision": 1},
    )
    assert store.list_revisions("design:persistent-index") == (expected,)

    reopened = ArtifactStore(root)

    def forbidden_rescan():  # type: ignore[no-untyped-def]
        raise AssertionError("a synchronized persistent projection must not scan history")

    monkeypatch.setattr(reopened, "_iter_revisions", forbidden_rescan)
    assert reopened.list_revisions("design:persistent-index") == (expected,)
    assert reopened.list_revisions("design:does-not-exist") == ()


def test_run_event_projection_reads_only_selected_signed_event_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    store = ArtifactStore(root)
    writer = _test_writer(store)
    run_ref = writer.put_json(
        artifact_id="run:projection:subject",
        artifact_type="control.subject",
        value={"run": True},
    )
    unrelated_ref = writer.put_json(
        artifact_id="other:projection:subject",
        artifact_type="control.subject",
        value={"run": False},
    )
    selected = writer.record_event(event_type="unsafe_event", subject_ref=run_ref)
    writer.record_event(event_type="unsafe_event", subject_ref=unrelated_ref)
    assert selected in store.list_events_for_run("run:projection")

    reopened = ArtifactStore(root)
    original = reopened._read_event_path
    read_names: list[str] = []

    def counted(path: Path):  # type: ignore[no-untyped-def]
        read_names.append(path.name)
        return original(path)

    monkeypatch.setattr(reopened, "_read_event_path", counted)
    events = reopened.list_events_for_run("run:projection")
    assert selected in events
    assert all(
        any(
            ref.artifact_id.startswith("run:projection")
            for ref in (event.subject_ref, *event.related_refs)
        )
        for event in events
    )
    assert len(read_names) == len(events)


def test_artifact_store_verifies_each_shared_dag_revision_once_per_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    refs = _diamond_artifact_refs(_test_writer(store))
    root = refs[-1]
    revision_read_counts: Counter[str] = Counter()
    original_read_file = store._read_file

    def counting_read_file(path: Path, *, missing_message: str) -> bytes:
        relative = path.relative_to(store.root)
        if relative.parts[:2] == ("revisions", "sha256"):
            revision_read_counts[path.stem] += 1
        return original_read_file(path, missing_message=missing_message)

    monkeypatch.setattr(store, "_read_file", counting_read_file)

    assert store.get_revision(root).ref == root
    assert revision_read_counts == Counter(
        {ref.revision_id.removeprefix("sha256:"): 1 for ref in refs}
    )


def test_artifact_store_reads_many_shared_revisions_with_one_dependency_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = _test_writer(store)
    leaf, left, right, _ = _diamond_artifact_refs(writer)
    revision_read_counts: Counter[str] = Counter()
    original_read_file = store._read_file

    def counting_read_file(path: Path, *, missing_message: str) -> bytes:
        relative = path.relative_to(store.root)
        if relative.parts[:2] == ("revisions", "sha256"):
            revision_read_counts[path.stem] += 1
        return original_read_file(path, missing_message=missing_message)

    monkeypatch.setattr(store, "_read_file", counting_read_file)

    assert writer.get_json_many((left, right), _ArtifactNode) == (
        _ArtifactNode(node="left"),
        _ArtifactNode(node="right"),
    )
    assert revision_read_counts == Counter(
        {
            leaf.revision_id.removeprefix("sha256:"): 1,
            left.revision_id.removeprefix("sha256:"): 1,
            right.revision_id.removeprefix("sha256:"): 1,
        }
    )


def test_artifact_writer_verified_closure_reuses_ancestor_audit_for_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = _test_writer(store)
    leaf = writer.put_json(
        artifact_id="subject:verified-closure-leaf",
        artifact_type="control.subject",
        value={"node": "leaf"},
    )
    revision_read_counts: Counter[str] = Counter()
    original_read_file = store._read_file

    def counting_read_file(path: Path, *, missing_message: str) -> bytes:
        relative = path.relative_to(store.root)
        if relative.parts[:2] == ("revisions", "sha256"):
            revision_read_counts[path.stem] += 1
        return original_read_file(path, missing_message=missing_message)

    monkeypatch.setattr(store, "_read_file", counting_read_file)

    with writer.verified_closure():
        writer.put_json(
            artifact_id="subject:verified-closure-left",
            artifact_type="control.subject",
            value={"node": "left"},
            dependencies=(leaf,),
        )
        writer.put_json(
            artifact_id="subject:verified-closure-right",
            artifact_type="control.subject",
            value={"node": "right"},
            dependencies=(leaf,),
        )

    assert revision_read_counts[leaf.revision_id.removeprefix("sha256:")] == 1


@pytest.mark.parametrize("tamper_target", ["revision", "blob"])
def test_artifact_store_reverifies_shared_dependency_across_public_reads(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    leaf, _, _, root = _diamond_artifact_refs(_test_writer(store))

    assert store.get_revision(root).ref == root

    digest = leaf.revision_id.removeprefix("sha256:")
    if tamper_target == "revision":
        revision_path = store.root / "revisions" / "sha256" / digest[:2] / f"{digest}.json"
        revision_path.chmod(0o600)
        value = json.loads(revision_path.read_text(encoding="utf-8"))
        value["producer_attestation"] = "hmac-sha256:" + "0" * 64
        revision_path.write_text(json.dumps(value), encoding="utf-8")
    else:
        blob_digest = leaf.content_hash.removeprefix("sha256:")
        blob_path = store.root / "blobs" / "sha256" / blob_digest[:2] / blob_digest
        blob_path.chmod(0o600)
        blob_path.write_bytes(b"x" * leaf.size_bytes)

    with pytest.raises(ArtifactIntegrityError):
        store.get_revision(root)


def test_artifact_store_signs_producer_scope_and_seals_issuance(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="framework",
        allowed_artifact_types=("control.subject",),
        allowed_event_types=("control_started",),
    )
    ref = writer.put_json(
        artifact_id="subject:signed",
        artifact_type="control.subject",
        value={"status": "signed"},
    )

    revision = store.get_revision(ref)
    assert revision.producer == "framework"
    assert revision.capability.allowed_artifact_types == ("control.subject",)
    key_path = store.root / ".producer-provenance.key"
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    event = writer.record_event(event_type="control_started", subject_ref=ref)
    assert event.producer == "framework"
    assert store.list_events()[-1] == event

    with pytest.raises(UnsafeArtifactError, match="cannot record event type"):
        writer.record_event(event_type="judge_passed", subject_ref=ref)

    replayed = ArtifactWriter(store, revision.capability, object())
    with pytest.raises(ArtifactStoreError, match="no active writer authorization"):
        replayed.put_json(
            artifact_id="subject:replayed-capability",
            artifact_type="control.subject",
            value={"status": "forged"},
        )

    with pytest.raises(UnsafeArtifactError, match="cannot write artifact type"):
        writer.put_json(
            artifact_id="report:forged",
            artifact_type="judge_report",
            value={"verdict": "pass"},
        )

    store.seal_capability_issuance()
    assert store.capability_issuance_sealed
    with pytest.raises(ArtifactStoreError, match="issuance is sealed"):
        store.issue_writer(
            producer="environment-judge",
            allowed_artifact_types=("judge_report",),
        )


def test_artifact_store_rejects_tampered_signed_revision_producer(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = _test_writer(store)
    ref = writer.put_json(
        artifact_id="subject:tamper",
        artifact_type="control.subject",
        value={"status": "safe"},
    )
    digest = ref.revision_id.removeprefix("sha256:")
    revision_path = store.root / "revisions" / "sha256" / digest[:2] / f"{digest}.json"
    revision_path.chmod(0o600)
    value = json.loads(revision_path.read_text(encoding="utf-8"))
    value["capability"]["producer"] = "environment-judge"
    revision_path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ArtifactIntegrityError, match="capability identity mismatch"):
        store.get_revision(ref)


@pytest.mark.parametrize(
    ("artifact_type", "value"),
    [
        ("runtime_secret", {"safe": True}),
        ("environment_design", {"api_key": "credential-material"}),
        ("environment_design", {"nested": {"raw_prompt": "private turn"}}),
        ("agent_transcript", {"turns": []}),
    ],
)
def test_artifact_store_rejects_sensitive_artifacts(
    tmp_path: Path,
    artifact_type: str,
    value: dict[str, object],
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(UnsafeArtifactError):
        _test_writer(store).put_json(
            artifact_id="unsafe:artifact",
            artifact_type=artifact_type,
            value=value,
        )


def test_artifact_store_detects_blob_tampering(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = _test_writer(store).put_blob(
        artifact_id="runtime:source",
        artifact_type="source_workspace",
        content=b"program bytes\n",
        media_type="application/octet-stream",
    )
    digest = ref.content_hash.removeprefix("sha256:")
    blob_path = store.root / "blobs" / "sha256" / digest[:2] / digest
    blob_path.chmod(0o600)
    blob_path.write_bytes(b"changed bytes\n")

    with pytest.raises(ArtifactIntegrityError):
        store.get_blob(ref)


@pytest.mark.parametrize("method", ["json", "blob", "event"])
def test_artifact_store_rejects_known_secret_canaries(
    tmp_path: Path,
    method: str,
) -> None:
    store = ArtifactStore(
        tmp_path / "artifacts",
        known_secret_canaries=("credential-canary-value",),
    )
    writer = _test_writer(store)
    subject = writer.put_json(
        artifact_id="safe:subject",
        artifact_type="control.subject",
        value={"status": "safe"},
    )

    with pytest.raises(UnsafeArtifactError, match="known secret canary"):
        if method == "json":
            writer.put_json(
                artifact_id="unsafe:json",
                artifact_type="control.payload",
                value={"note": "credential-canary-value"},
            )
        elif method == "blob":
            writer.put_blob(
                artifact_id="unsafe:blob",
                artifact_type="source.workspace",
                content=b"prefix credential-canary-value suffix",
                media_type="application/octet-stream",
            )
        else:
            writer.record_event(
                event_type="unsafe_event",
                subject_ref=subject,
                details=(
                    # KeyValue intentionally permits ordinary metadata values;
                    # the byte-level canary gate is the final write boundary.
                    KeyValue(
                        key="note",
                        value="credential-canary-value",
                    ),
                ),
            )


def test_artifact_store_rejects_credential_shaped_blob(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(UnsafeArtifactError, match="openai-key"):
        _test_writer(store).put_blob(
            artifact_id="unsafe:credential",
            artifact_type="source.workspace",
            content=b"sk-abcdefghijklmnopqrstuvwxyz012345",
            media_type="application/octet-stream",
        )

    with pytest.raises(UnsafeArtifactError, match="credential-assignment"):
        _test_writer(store).put_blob(
            artifact_id="unsafe:assigned-credential",
            artifact_type="source.workspace",
            content=b'api_key = "a8DkP7mZ2qL9sW4vN6xR"',
            media_type="application/octet-stream",
        )


def test_artifact_store_allows_credential_handles_and_documented_placeholders(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = _test_writer(store).put_blob(
        artifact_id="safe:credential-handle",
        artifact_type="source.workspace",
        content=(
            b'api_key = os.environ["OPENAI_API_KEY"]\nexample = "Bearer your_example_token"\n'
        ),
        media_type="text/x-python",
    )

    assert store.get_blob(ref).startswith(b"api_key = os.environ")


def test_task_materializer_and_public_check_contracts_are_fixed_protocols(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = _test_writer(store)
    schema_ref = writer.put_json(
        artifact_id="task:schema",
        artifact_type="build.task_materialization_schema",
        value={"type": "object"},
    )
    curriculum_ref = writer.put_json(
        artifact_id="task:curriculum",
        artifact_type="build.curriculum",
        value={"task_types": ["inventory"]},
    )

    descriptor = TaskMaterializerDescriptor(
        entrypoint="inventory.tasks:materialize",
        entry_path="src/inventory/tasks.py",
        output_schema_ref=schema_ref,
        curriculum_ref=curriculum_ref,
    )
    assert descriptor.protocol == "python-callable-v3"
    assert descriptor.task_schema_version == "task-materialization-v3"
    assert descriptor.instruction_renderer == "objective-public-goal-v1"
    assert descriptor.evaluator_goal_projector == "identity-bindings-v1"
    with pytest.raises(ValidationError):
        TaskMaterializerDescriptor(
            entrypoint="inventory.tasks:build_task",
            entry_path="src/inventory/tasks.py",
            output_schema_ref=schema_ref,
            curriculum_ref=curriculum_ref,
        )

    public_check = PublicSelfCheckDescriptor(
        argv=(".venv/bin/python", "-m", "inventory.public_check"),
        entry_path="src/inventory/public_check.py",
    )
    assert public_check.protocol == "python-module-v2"
    with pytest.raises(ValidationError):
        PublicSelfCheckDescriptor(
            argv=("python3", "-m", "inventory.public_check"),
            entry_path="src/inventory/public_check.py",
        )

    release = ReleaseProfile(profile_id="default")
    assert {
        "static_assurance",
        "supply_chain",
        "task_materialization",
        "task_reachability",
        "public_self_check",
    } <= set(release.required_hard_gates)


def test_rule_clause_rejects_a_tautological_empty_schema() -> None:
    with pytest.raises(ValidationError, match="tautological empty JSON Schema"):
        RuleClause(
            clause_id="clause:empty-schema",
            left=RuleValueRef(
                source="post_state",
                pointer="",
                value_type="object",
            ),
            operator="schema_valid",
            json_schema={},
        )


def test_task_requirement_owns_closed_v3_schemas_and_identity_goal_projection() -> None:
    def goal_rule(rule_id: str, family: str) -> Rule:
        return Rule(
            rule_id=rule_id,
            family=family,  # type: ignore[arg-type]
            description="Counter state must reach the framework-projected target.",
            boolean_operator="all",
            case_sensitivity="positive_only",
            clauses=(
                RuleClause(
                    clause_id=f"clause:{rule_id}",
                    left=RuleValueRef(
                        source="post_state",
                        pointer="/counter/value",
                        value_type="number",
                    ),
                    operator="greater_or_equal",
                    right=RuleValueRef(
                        source="task_goal",
                        pointer="/target",
                        value_type="number",
                    ),
                ),
            ),
        )

    closed_goal: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"target": {"type": "integer"}},
        "required": ["target"],
        "additionalProperties": False,
    }
    requirement = TaskRequirement(
        task_type="increase_counter",
        objective="Increase the counter to the public target.",
        allowed_actor_ids=("user",),
        required_tool_ids=("counter.increment",),
        success_conditions=(goal_rule("rule:success", "task_success"),),
        terminal_conditions=(goal_rule("rule:terminal", "task_terminal"),),
        initial_config_schema={
            "type": "object",
            "properties": {"initial": {"type": "integer"}},
            "required": ["initial"],
            "additionalProperties": False,
        },
        public_goal_schema=closed_goal,
        evaluator_goal_schema=closed_goal,
        evaluator_goal_bindings=(
            EvaluatorGoalBinding(
                binding_id="binding:target",
                public_pointer="/target",
                evaluator_pointer="/target",
            ),
        ),
        difficulty_dimensions=("scale",),
    )
    assert requirement.evaluator_goal_bindings[0].projection == "identity"

    with pytest.raises(ValidationError, match="additionalProperties=false"):
        TaskRequirement.model_validate_json(
            canonical_json_bytes(
                {
                    **requirement.model_dump(mode="json"),
                    "initial_config_schema": {
                        "type": "object",
                        "properties": {"initial": {"type": "integer"}},
                        "required": ["initial"],
                        "additionalProperties": True,
                    },
                }
            )
        )

    with pytest.raises(ValidationError):
        EvaluatorGoalBinding(
            binding_id="binding:computed-target",
            public_pointer="/target",
            evaluator_pointer="/target",
            projection="computed",  # type: ignore[arg-type]
        )
