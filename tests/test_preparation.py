from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import agent_env_foundry.preparation as preparation_module
from agent_env_foundry.preparation import (
    OpenPreparedRelease,
    PreparationExecutionError,
    PreparationSettings,
    ProjectMaterializationInput,
    _ChildTransport,
    materialize_project,
    prepare_release,
)
from agent_env_foundry.project_identity import ProjectIdentityError
from agent_env_foundry.release import verify_release_v2
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    ConditionCheckRequest,
    EvaluationBinding,
    GoalEvaluationContext,
    SemanticsContractError,
    start_case_from_document,
)
from agent_env_foundry.verifier_author import compute_verifier_project_digest
from agent_env_foundry.verifier_inputs import (
    ACTOR_VIEW_MANIFEST_NAME,
    EXPECTED_TASK_SEMANTICS_NAME,
    PUBLIC_SURFACE_NAME,
    QUALIFICATION_VERIFIER_CONTRACT_NAME,
)
from v2_release_factory import build_v2_release, write_v2_zip


def _settings() -> PreparationSettings:
    return PreparationSettings(
        Path(os.environ.get("UV_CACHE_DIR", "/tmp/foundry-s2-runtime-uv-cache")),
        120.0,
    )


def test_one_materializer_installs_actor_semantics_and_verifier_roles(
    tmp_path: Path,
) -> None:
    release_root = build_v2_release(tmp_path / "release")
    release = verify_release_v2(release_root)
    actor_module = release.descriptor.actor_factory.partition(":")[0].partition(".")[0]
    semantics_module = release.descriptor.semantics_factory.partition(":")[0].partition(".")[0]
    actor = materialize_project(
        ProjectMaterializationInput(
            source_root=release_root / release.descriptor.actor_project,
            project_digest=release.descriptor.actor_project_digest,
            own_module=actor_module,
            forbidden_modules=(semantics_module,),
            role="actor",
        ),
        tmp_path / "runtimes/actor",
        settings=_settings(),
    )
    semantics = materialize_project(
        ProjectMaterializationInput(
            source_root=release_root / release.descriptor.semantics_project,
            project_digest=release.descriptor.semantics_project_digest,
            own_module=semantics_module,
            forbidden_modules=(actor_module,),
            role="semantics",
        ),
        tmp_path / "runtimes/semantics",
        settings=_settings(),
    )
    verifier_source = release_root / release.descriptor.semantics_project
    for name in (
        EXPECTED_TASK_SEMANTICS_NAME,
        PUBLIC_SURFACE_NAME,
        QUALIFICATION_VERIFIER_CONTRACT_NAME,
        ACTOR_VIEW_MANIFEST_NAME,
    ):
        (verifier_source / name).write_text("author input\n")
    (verifier_source / "actor-view").mkdir()
    (verifier_source / "actor-view/secret.py").write_text("SECRET = True\n")
    (verifier_source / ".venv").mkdir()
    (verifier_source / ".venv/poison").write_text("unbound\n")
    verifier_digest = compute_verifier_project_digest(verifier_source)
    assert verifier_digest == release.descriptor.semantics_project_digest
    verifier = materialize_project(
        ProjectMaterializationInput(
            source_root=verifier_source,
            project_digest=verifier_digest,
            own_module=semantics_module,
            forbidden_modules=(actor_module, "agent_env_foundry"),
            role="verifier",
        ),
        tmp_path / "runtimes/verifier",
        settings=_settings(),
    )

    assert (actor.role, semantics.role, verifier.role) == (
        "actor",
        "semantics",
        "verifier",
    )
    assert len({actor.project_root, semantics.project_root, verifier.project_root}) == 3
    assert all(lock.python.is_file() for lock in (actor, semantics, verifier))
    assert not (verifier.project_root / EXPECTED_TASK_SEMANTICS_NAME).exists()
    assert not (verifier.project_root / "actor-view").exists()
    assert not (verifier.project_root / ".venv/poison").exists()


def test_materializer_attributes_verifier_import_leak_to_verifier(
    tmp_path: Path,
) -> None:
    release_root = build_v2_release(
        tmp_path / "release",
        leak_actor_into_semantics=True,
    )
    release = verify_release_v2(release_root)
    actor_module = release.descriptor.actor_factory.partition(":")[0].partition(".")[0]
    semantics_module = release.descriptor.semantics_factory.partition(":")[0].partition(".")[0]

    with pytest.raises(PreparationExecutionError) as caught:
        materialize_project(
            ProjectMaterializationInput(
                source_root=release_root / release.descriptor.semantics_project,
                project_digest=release.descriptor.semantics_project_digest,
                own_module=semantics_module,
                forbidden_modules=(actor_module,),
                role="verifier",
            ),
            tmp_path / "runtime",
            settings=_settings(),
        )

    assert caught.value.kind == "VerifierDefect"
    assert caught.value.code == "runtime_import_leak"


def test_materializer_rejects_changed_source_before_copy_or_sync(tmp_path: Path) -> None:
    release_root = build_v2_release(tmp_path / "release")
    release = verify_release_v2(release_root)
    actor_source = release_root / release.descriptor.actor_project
    actor_module = release.descriptor.actor_factory.partition(":")[0].partition(".")[0]
    semantics_module = release.descriptor.semantics_factory.partition(":")[0].partition(".")[0]
    (actor_source / "src/shared_actor/__init__.py").write_text("TAMPERED = True\n")
    runtime = tmp_path / "runtime"

    with pytest.raises(PreparationExecutionError) as caught:
        materialize_project(
            ProjectMaterializationInput(
                source_root=actor_source,
                project_digest=release.descriptor.actor_project_digest,
                own_module=actor_module,
                forbidden_modules=(semantics_module,),
                role="actor",
            ),
            runtime,
            settings=_settings(),
        )

    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "source_project_digest_mismatch"
    assert not runtime.exists()


def test_materializer_attributes_copy_time_identity_failure_and_cleans_staging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release_root = build_v2_release(tmp_path / "release")
    release = verify_release_v2(release_root)
    source = release_root / release.descriptor.semantics_project
    actor_module = release.descriptor.actor_factory.partition(":")[0].partition(".")[0]
    semantics_module = release.descriptor.semantics_factory.partition(":")[0].partition(".")[0]
    digest = compute_verifier_project_digest(source)

    def changed_during_copy(*_args: object, **_kwargs: object) -> str:
        raise ProjectIdentityError(
            "project_source_changed",
            "source changed during copy",
            path="src/release.py",
        )

    monkeypatch.setattr(preparation_module, "copy_authored_project", changed_during_copy)
    runtime = tmp_path / "runtime"
    with pytest.raises(PreparationExecutionError) as caught:
        materialize_project(
            ProjectMaterializationInput(
                source_root=source,
                project_digest=digest,
                own_module=semantics_module,
                forbidden_modules=(actor_module,),
                role="verifier",
            ),
            runtime,
            settings=_settings(),
        )

    assert caught.value.kind == "VerifierDefect"
    assert caught.value.code == "project_source_changed"
    assert caught.value.details["path"] == "src/release.py"
    assert not runtime.exists()
    assert not tuple(tmp_path.glob(".runtime.*.tmp"))


def test_prepare_open_runs_real_actor_and_all_trusted_methods(tmp_path: Path) -> None:
    release = build_v2_release(tmp_path / "release", behavior="alpha")
    prepared = prepare_release(release, tmp_path / "cache", settings=_settings())
    assert isinstance(prepared, OpenPreparedRelease)
    assert prepared.identity.actor_digest

    instance = tmp_path / "instances/one"
    assert not (instance / "state.json").exists()
    with prepared.open(instance) as session:
        assert session.actor.tools()[0]["name"] == "increment"
        assert not (instance / "state.json").exists(), "open/tools must not reset"
        reset = session.actor.reset({"seed": 2})
        assert reset == {"behavior": "alpha", "count": 2, "resets": 1}
        observation = session.actor.invoke("increment", {"amount": 3})
        assert observation == {
            "ok": True,
            "data": {"behavior": "alpha", "count": 5},
            "error": None,
        }

        starts = session.trusted.start_cases(7, 1)
        facts = session.trusted.inspect(instance)
        capabilities = session.trusted.capabilities()
        bindings = session.trusted.enumerate_bindings("increment", facts)
        atom = session.trusted.evaluate_atom(
            AtomCheckRequest(
                "increment",
                {"count": 2},
                facts,
                bindings[0].protected_binding,
                (),
                {"count": 5},
                GoalEvaluationContext(
                    "target",
                    (
                        EvaluationBinding(
                            "target",
                            "increment",
                            bindings[0].semantic_key,
                            bindings[0].protected_binding,
                        ),
                    ),
                    None,
                    None,
                    (),
                ),
            )
        )
        condition = session.trusted.evaluate_condition(
            ConditionCheckRequest("available", facts, None, ())
        )
        assert starts[0].reset_input == {"seed": 7}
        assert facts["count"] == 5
        assert capabilities[0].capability_id == "increment"
        assert bindings[0].semantic_key == "counter"
        assert atom.satisfied and atom.report_values == {"count": 5}
        assert condition.status == "true"
        assert len(session.trusted_events) == 6
        assert all(event.unchanged for event in session.trusted_events)


def test_trusted_mutation_is_recorded_and_rejected(tmp_path: Path) -> None:
    release = build_v2_release(tmp_path / "release", mutate_semantics=True)
    prepared = prepare_release(release, tmp_path / "cache", settings=_settings())
    with prepared.open(tmp_path / "instance") as session:
        with pytest.raises(PreparationExecutionError) as caught:
            session.trusted.inspect(tmp_path / "instance")
        assert caught.value.kind == "SemanticsDefect"
        assert caught.value.code == "trusted_state_mutation"
        assert len(session.trusted_events) == 1
        assert not session.trusted_events[0].unchanged

    failing_release = build_v2_release(
        tmp_path / "failing-release",
        mutate_semantics=True,
        raise_after_mutation=True,
    )
    failing = prepare_release(failing_release, tmp_path / "failing-cache", settings=_settings())
    with failing.open(tmp_path / "failing-instance") as session:
        with pytest.raises(PreparationExecutionError) as caught:
            session.trusted.inspect(tmp_path / "failing-instance")
        assert caught.value.code == "trusted_state_mutation"
        assert len(session.trusted_events) == 1
        assert not session.trusted_events[0].unchanged


def test_same_package_names_do_not_alias_and_open_never_resets(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    alpha = prepare_release(
        build_v2_release(tmp_path / "alpha", behavior="alpha"), cache, settings=_settings()
    )
    beta = prepare_release(
        build_v2_release(tmp_path / "beta", behavior="beta"), cache, settings=_settings()
    )
    alpha_instance = tmp_path / "alpha-instance"
    with alpha.open(alpha_instance) as left, beta.open(tmp_path / "beta-instance") as right:
        assert left.actor.reset({"seed": 1})["behavior"] == "alpha"
        assert right.actor.reset({"seed": 1})["behavior"] == "beta"
        left.actor.invoke("increment", {"amount": 4})

    with alpha.open(alpha_instance) as reopened:
        facts = reopened.trusted.inspect(alpha_instance)
        assert facts["count"] == 5
        assert facts["resets"] == 1


def test_semantics_runtime_cannot_import_actor_package(tmp_path: Path) -> None:
    release = build_v2_release(tmp_path / "release", leak_actor_into_semantics=True)
    with pytest.raises(PreparationExecutionError) as caught:
        prepare_release(release, tmp_path / "cache", settings=_settings())
    assert caught.value.kind == "SemanticsDefect"
    assert caught.value.code == "runtime_import_leak"

    actor_leak = build_v2_release(tmp_path / "actor-leak", leak_semantics_into_actor=True)
    with pytest.raises(PreparationExecutionError) as caught:
        prepare_release(actor_leak, tmp_path / "actor-cache", settings=_settings())
    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "runtime_import_leak"


def test_semantics_startup_failure_is_attributed_to_semantics(tmp_path: Path) -> None:
    release = build_v2_release(tmp_path / "release", broken_semantics_startup=True)
    prepared = prepare_release(release, tmp_path / "cache", settings=_settings())
    with prepared.open(tmp_path / "instance") as session:
        with pytest.raises(PreparationExecutionError) as caught:
            session.trusted.start_cases(1, 1)
        assert caught.value.kind == "SemanticsDefect"
        assert caught.value.code == "child_startup_failed"


def test_directory_zip_identity_and_prepared_tamper_fail_closed(tmp_path: Path) -> None:
    release = build_v2_release(tmp_path / "release")
    archive = write_v2_zip(release, tmp_path / "release.zip")
    directory = prepare_release(release, tmp_path / "directory-cache", settings=_settings())
    zipped = prepare_release(archive, tmp_path / "zip-cache", settings=_settings())
    assert directory.identity == zipped.identity

    prepared_project = (
        tmp_path
        / "directory-cache/runtimes"
        / directory.identity.release_id
        / "actor/project/src/shared_actor/__init__.py"
    )
    prepared_project.write_text("TAMPERED = True\n", encoding="utf-8")
    with pytest.raises(PreparationExecutionError, match="digest"):
        directory.open(tmp_path / "instance")

    clean = prepare_release(
        build_v2_release(tmp_path / "pth-release"),
        tmp_path / "pth-cache",
        settings=_settings(),
    )
    actor_runtime = tmp_path / "pth-cache/runtimes" / clean.identity.release_id / "actor/project"
    pth_files = tuple((actor_runtime / ".venv/lib").glob("python*/site-packages/*.pth"))
    assert pth_files, "editable installation must have a bound .pth"
    pth_files[0].write_text(str(tmp_path / "unbound-source"), encoding="utf-8")
    with pytest.raises(PreparationExecutionError, match="prepared source"):
        clean.open(tmp_path / "pth-instance")


def test_semantics_wire_decoder_rejects_unknown_fields() -> None:
    with pytest.raises(SemanticsContractError, match="exactly"):
        start_case_from_document(
            {"case_id": "case", "reset_input": None, "regime_tags": [], "extra": True}
        )


def test_private_transport_rejects_sequence_mismatch_and_timeout(tmp_path: Path) -> None:
    mismatch = tmp_path / "mismatch.py"
    mismatch.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " request=json.loads(line)\n"
        " response={'seq': request['seq']+1, 'ok': True, 'value': None}\n"
        " print(json.dumps(response), flush=True)\n",
        encoding="utf-8",
    )
    transport = _ChildTransport(
        Path(sys.executable), mismatch, (), cwd=tmp_path, timeout=1.0, role="actor"
    )
    with pytest.raises(PreparationExecutionError) as caught:
        transport.call("tools", {})
    assert caught.value.code == "child_sequence_mismatch"
    transport.close()

    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text(
        "import sys,time\nfor line in sys.stdin: time.sleep(10)\n",
        encoding="utf-8",
    )
    transport = _ChildTransport(
        Path(sys.executable), sleeper, (), cwd=tmp_path, timeout=0.05, role="actor"
    )
    with pytest.raises(PreparationExecutionError) as caught:
        transport.call("tools", {})
    assert caught.value.code == "child_timeout"
    transport.close()


def test_private_transport_close_ignores_a_dead_child_pipe() -> None:
    class DeadInput:
        def close(self) -> None:
            raise BrokenPipeError("child already exited")

    class FinishedProcess:
        waited = False

        def poll(self) -> int:
            return 1

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.waited = True
            return 1

    process = FinishedProcess()
    transport = object.__new__(_ChildTransport)
    transport._closed = False
    transport._process = process
    transport._stdin = DeadInput()
    transport._timeout = 1.0

    transport.close()

    assert transport._closed is True
    assert process.waited is True
