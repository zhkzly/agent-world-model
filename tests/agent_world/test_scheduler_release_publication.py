"""Real Registry publication through the new Scheduler release leaf."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from v3_fixture import build_release_graph, builder_writer, framework_writer

from agent_world.artifact_store import ArtifactStore
from agent_world.builder import EnvironmentBuilder
from agent_world.contracts import Budget, EnvironmentPackageManifest
from agent_world.control import (
    LeaseBudgetLedger,
    ObservabilityLeaf,
    PackageLeaf,
    RegistryPublicationLeaf,
    ReleaseDossierCompiler,
    SchedulerLeafExecutor,
    WorkCommit,
    WorkControlRuntime,
    WorkControlStore,
    WorkGraphManifest,
    WorkScheduler,
)
from agent_world.registry import EnvironmentRegistry, ReleaseRecord


def test_registry_publication_leaf_stages_and_publishes_exact_envpkg(tmp_path: Path) -> None:
    """The release leaf performs the real Registry filesystem transaction.

    The Candidate is a prebuilt fixture to isolate Package/Registry control
    behavior.  There is no fabricated Registry result: this test restores the
    immutable candidate tar, rebuilds framework payload bytes, reserves a real
    coordinate, stages it, validates it and atomically publishes it.
    """

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_release_graph(tmp_path, store)
    artifacts = framework_writer(store)
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=WorkControlStore(tmp_path / "work-control"),
        budget=LeaseBudgetLedger(Budget(wall_seconds=600, process_calls=32)),
    )
    builder = EnvironmentBuilder(
        artifact_store=builder_writer(store),
        invocation_backend=cast("object", object()),  # unused by snapshot recovery
        profile_provider=cast("object", object()),  # unused by snapshot recovery
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    leaf = RegistryPublicationLeaf(
        builder=builder,
        registry=registry,
        workspace_root=tmp_path / "registry-workspaces",
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )
    manifest = store.get_json(graph.manifest_ref, EnvironmentPackageManifest)

    record = leaf._publish_exact(
        graph.manifest_ref,
        manifest,
        "attempt:real-registry-publication",
    )

    assert record.status == "released"
    assert record.manifest_ref == graph.manifest_ref
    assert record.candidate_ref == graph.candidate_ref
    package_root = registry.root / record.package_relpath
    assert (package_root / "manifest.json").is_file()
    assert (package_root / "release-dossier.json").is_file()
    assert registry.require_released_manifest(graph.manifest_ref) == record

    # A controller crash after the atomic Registry commit must converge to the
    # same durable release rather than attempt a second publish.
    assert (
        leaf._publish_exact(
            graph.manifest_ref,
            manifest,
            "attempt:real-registry-publication-recovery",
        )
        == record
    )


@pytest.mark.asyncio
async def test_scheduler_package_then_registry_runs_the_real_downstream_closure(
    tmp_path: Path,
) -> None:
    """Package and Registry are two durable Scheduler commits, not Controller calls."""

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_release_graph(tmp_path, store, commit_package=False)
    closure = graph.package_closure
    artifacts = framework_writer(store)
    builder = EnvironmentBuilder(
        artifact_store=builder_writer(store),
        invocation_backend=cast("object", object()),  # snapshot recovery only
        profile_provider=cast("object", object()),  # snapshot recovery only
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    kernel = SchedulerLeafExecutor(runtime=closure.runtime)
    package_leaf = PackageLeaf(
        builder=builder,
        graph=closure.graph,
        final_epoch_ref=closure.final_epoch_ref,
        final_manifest_ref=closure.final_manifest_ref,
        release_profile=graph.release_profile,
        workspace_root=tmp_path / "package-workspaces",
        dossier_compiler=ReleaseDossierCompiler(
            artifacts=artifacts,
            heads=closure.runtime.heads,
        ),
        kernel=kernel,
    )
    publication_leaf = RegistryPublicationLeaf(
        builder=builder,
        registry=registry,
        workspace_root=tmp_path / "registry-workspaces",
        kernel=kernel,
    )
    manifest = store.get_json(closure.final_manifest_ref, WorkGraphManifest)
    scheduler = WorkScheduler(
        graph=closure.graph,
        manifest=manifest,
        manifest_ref=closure.final_manifest_ref,
        heads=closure.runtime.heads,
        artifacts=artifacts,
        runtime=closure.runtime,
    )

    async def package(context) -> None:
        await package_leaf.execute(context, definition=closure.package_definition)

    publication_definition = next(
        item
        for item in closure.graph.definitions
        if item.coordinate.component == "registry" and item.coordinate.stage == "publication"
    )

    async def publication(context) -> None:
        await publication_leaf.execute(context, definition=publication_definition)

    results = await scheduler.run_until_stalled(
        executors={
            closure.package_definition.work_id: package,
            publication_definition.work_id: publication,
        }
    )

    assert [item.coordinate for item in results] == [
        closure.package_definition.coordinate,
        publication_definition.coordinate,
    ]
    assert all(item.after_state == "committed" for item in results)
    release_head = closure.runtime.heads.read_head(publication_definition.coordinate)
    assert release_head is not None and release_head.commit_ref is not None
    release_commit = store.get_json(release_head.commit_ref, WorkCommit)
    release_ref = next(
        item for item in release_commit.consumer_refs if item.artifact_type == "release.record"
    )
    released = store.get_json(release_ref, ReleaseRecord)
    registered = registry.require_released_manifest(released.manifest_ref)
    assert registered.release_id == released.release_id


def test_observability_closure_covers_every_prepackage_final_graph_attempt(tmp_path: Path) -> None:
    """Telemetry cannot omit intermediate Design work from a release claim."""

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_release_graph(tmp_path, store, commit_package=False)
    closure = graph.package_closure
    from agent_world.control.telemetry import TelemetryStore

    telemetry = TelemetryStore(tmp_path / "telemetry.sqlite3")
    try:
        leaf = ObservabilityLeaf(
            heads=closure.runtime.heads,
            graph=closure.graph,
            telemetry=telemetry,
            trace_id="trace:fixture",
            kernel=SchedulerLeafExecutor(runtime=closure.runtime),
        )
        attempts = leaf._prepackage_attempts()
    finally:
        telemetry.close()

    expected = tuple(
        definition
        for definition in closure.graph.topological_definitions()
        if definition.coordinate.component not in {"release", "registry"}
    )
    assert len(attempts) == len(expected)
    assert {
        (attempt.coordinate.component, attempt.coordinate.stage)
        for attempt in attempts
    } == {
        (definition.coordinate.component, definition.coordinate.stage)
        for definition in expected
    }
