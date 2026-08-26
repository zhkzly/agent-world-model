"""Release loading: factory import, instance directory, digest verification.

All release directories come from tests/release_factory.py and are mechanical
contract fixtures, never qualified EnvironmentRelease artifacts (PRD F8).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import rfc8785

from agent_env_foundry.environment import load_environment
from agent_env_foundry.errors import EnvironmentContractError
from release_factory import (
    MANIFEST_PATH,
    RESET_OBSERVATION_SCHEMA_PATH,
    START_SCHEMA_PATH,
    build_release,
    record_for,
)


def load_ok(tmp_path: Path, **kwargs: Any) -> Any:
    root = build_release(tmp_path / "release", **kwargs)
    return load_environment(root, tmp_path / "episodes" / "e1")


def rewrite_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, indent=2))


def reseal_manifest(root: Path, records: list[dict[str, Any]]) -> None:
    """Rewrite the manifest with the given records and reseal the descriptor."""
    manifest = {"files": records}
    rewrite_json(root / MANIFEST_PATH, manifest)
    descriptor = json.loads((root / "release.json").read_text())
    descriptor["payload_digest"] = hashlib.sha256(rfc8785.dumps(manifest)).hexdigest()
    rewrite_json(root / "release.json", descriptor)


def stub_record(rel: str, digest: str) -> dict[str, Any]:
    return {"path": rel, "type": "file", "mode": 0o644, "digest": digest}


def test_load_returns_validated_environment_without_implicit_reset(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    instance = tmp_path / "episodes" / "e1"
    env = load_environment(root, instance)
    assert instance.is_dir()
    # Eager catalog validation is declarative; reset is never implied by load.
    assert [call[0] for call in env._environment.calls] == ["tools"]
    observation = env.reset()
    assert observation["kind"] == "mechanical"
    assert env._environment.instance_directory == instance


def test_reload_reattaches_to_existing_instance_without_reset(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    instance = tmp_path / "episodes" / "e1"
    first = load_environment(root, instance)
    first.reset()
    first.close()
    second = load_environment(root, instance)
    assert [call[0] for call in second._environment.calls] == ["tools"]
    assert second._environment.instance_directory == instance


def test_loader_does_not_assign_a_qualified_release_identity(tmp_path: Path) -> None:
    env = load_ok(tmp_path)
    assert not hasattr(env, "release_id")


@pytest.mark.parametrize(
    "extra_field",
    [
        "task",
        "reward",
        "verifier",
        "trajectory",
        "transport",
        "mcp",
        "lifecycle",
        "tool_call_id",
        "current",
        "release_id",
    ],
)
def test_descriptor_fields_outside_the_contract_are_rejected(
    tmp_path: Path, extra_field: str
) -> None:
    with pytest.raises(EnvironmentContractError, match="release.json|release contract"):
        load_ok(tmp_path, descriptor_patch={extra_field: {"anything": 1}})


def test_missing_descriptor_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(EnvironmentContractError, match="environment_factory"):
        load_ok(tmp_path, descriptor_drop={"environment_factory"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format", "environment-release/2"),
        ("canonicalization", "plain-json"),
        ("hash", "md5"),
        ("payload_digest", "0" * 64),
        ("environment_factory", "no_colon_here"),
        ("environment_factory", "a:b:c"),
        ("environment_factory", ":missing_module"),
        ("environment_factory", "missing_attr_after_colon:"),
        ("environment_factory", ""),
    ],
)
def test_invalid_descriptor_values_are_rejected(tmp_path: Path, field: str, value: str) -> None:
    with pytest.raises(EnvironmentContractError):
        load_ok(tmp_path, descriptor_patch={field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_schema", "../outside.json"),
        ("start_schema", "/etc/passwd"),
        ("reset_observation_schema", "docs/../../escape.json"),
        ("payload_manifest", "../other-manifest.json"),
    ],
)
def test_descriptor_paths_cannot_escape_the_release(tmp_path: Path, field: str, value: str) -> None:
    with pytest.raises(EnvironmentContractError):
        load_ok(tmp_path, descriptor_patch={field: value})


def test_payload_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    descriptor = json.loads((root / "release.json").read_text())
    descriptor["payload_digest"] = "f" * 64
    rewrite_json(root / "release.json", descriptor)
    with pytest.raises(EnvironmentContractError, match="payload digest"):
        load_environment(root, tmp_path / "e1")


def test_tampered_bound_schema_file_is_rejected(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    (root / START_SCHEMA_PATH).write_text(
        json.dumps({"type": "object", "properties": {"seed": {"type": "integer"}}})
    )
    with pytest.raises(EnvironmentContractError, match="digest"):
        load_environment(root, tmp_path / "e1")


def test_tampered_non_schema_payload_member_is_rejected(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    member = root / "project/runtime.py"
    member.parent.mkdir(parents=True)
    member.write_text("ORIGINAL = True\n")
    member.chmod(0o644)
    records = sorted(
        [
            record_for(root, START_SCHEMA_PATH),
            record_for(root, RESET_OBSERVATION_SCHEMA_PATH),
            record_for(root, "project/runtime.py"),
        ],
        key=lambda record: record["path"],
    )
    reseal_manifest(root, records)
    load_environment(root, tmp_path / "before-tamper")

    member.write_text("ORIGINAL = False\n")
    with pytest.raises(EnvironmentContractError, match="payload member.*digest mismatch"):
        load_environment(root, tmp_path / "after-tamper")


def test_non_schema_payload_member_mode_is_verified(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    member = root / "project/runtime.py"
    member.parent.mkdir(parents=True)
    member.write_text("VALUE = 1\n")
    member.chmod(0o644)
    records = sorted(
        [
            record_for(root, START_SCHEMA_PATH),
            record_for(root, RESET_OBSERVATION_SCHEMA_PATH),
            record_for(root, "project/runtime.py"),
        ],
        key=lambda record: record["path"],
    )
    reseal_manifest(root, records)

    member.chmod(0o600)
    with pytest.raises(EnvironmentContractError, match="payload member.*mode mismatch"):
        load_environment(root, tmp_path / "mode-tamper")


def test_unlisted_bound_schema_file_is_rejected(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    records = [record_for(root, RESET_OBSERVATION_SCHEMA_PATH)]
    reseal_manifest(root, records)
    with pytest.raises(EnvironmentContractError, match="not listed|unlisted"):
        load_environment(root, tmp_path / "e1")


def test_symlinked_bound_schema_file_is_rejected(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    target = root / START_SCHEMA_PATH
    content = target.read_bytes()
    target.unlink()
    outside = tmp_path / "outside-start.json"
    outside.write_bytes(content)
    target.symlink_to(outside)
    with pytest.raises(EnvironmentContractError, match="symlink|escape"):
        load_environment(root, tmp_path / "e1")


def test_symlinked_directory_cannot_relay_outside_the_release(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    outside = tmp_path / "outside-schemas"
    outside.mkdir()
    (outside / "start.json").write_text((root / START_SCHEMA_PATH).read_text())
    (outside / "reset-observation.json").write_text(
        (root / RESET_OBSERVATION_SCHEMA_PATH).read_text()
    )
    schemas_dir = root / "docs" / "schemas"
    shutil.rmtree(schemas_dir)
    schemas_dir.symlink_to(outside)
    with pytest.raises(EnvironmentContractError, match="symlink|escape"):
        load_environment(root, tmp_path / "e1")


def test_manifest_listing_itself_or_the_descriptor_is_rejected(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    records = sorted(
        [
            record_for(root, START_SCHEMA_PATH),
            record_for(root, RESET_OBSERVATION_SCHEMA_PATH),
            stub_record("release.json", "0" * 64),
        ],
        key=lambda record: record["path"],
    )
    reseal_manifest(root, records)
    with pytest.raises(EnvironmentContractError, match="must not list|circular"):
        load_environment(root, tmp_path / "e1")


@pytest.mark.parametrize(
    "records",
    [
        # Unsorted by path.
        [
            stub_record(RESET_OBSERVATION_SCHEMA_PATH, "0" * 64),
            stub_record(START_SCHEMA_PATH, "1" * 64),
        ],
        # Duplicate paths.
        [
            stub_record(START_SCHEMA_PATH, "0" * 64),
            stub_record(START_SCHEMA_PATH, "1" * 64),
        ],
    ],
)
def test_manifest_order_and_uniqueness_are_enforced(
    tmp_path: Path, records: list[dict[str, Any]]
) -> None:
    with pytest.raises(EnvironmentContractError):
        load_ok(tmp_path, manifest_records=records)


@pytest.mark.parametrize(
    "record",
    [
        {"path": START_SCHEMA_PATH, "type": "directory", "mode": 0o644, "digest": "0" * 64},
        {"path": START_SCHEMA_PATH, "mode": 0o644, "digest": "0" * 64},
        {
            "path": START_SCHEMA_PATH,
            "type": "file",
            "mode": 0o644,
            "digest": "0" * 64,
            "extra": 1,
        },
        {"path": START_SCHEMA_PATH, "type": "file", "mode": "0644", "digest": "0" * 64},
        {"path": START_SCHEMA_PATH, "type": "file", "mode": 0o644, "digest": "not-hex"},
    ],
)
def test_manifest_record_faults_are_rejected(tmp_path: Path, record: dict[str, Any]) -> None:
    with pytest.raises(EnvironmentContractError):
        load_ok(tmp_path, manifest_records=[record])


def test_missing_release_root_or_descriptor_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(EnvironmentContractError):
        load_environment(tmp_path / "nope", tmp_path / "e1")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(EnvironmentContractError, match="release.json"):
        load_environment(empty, tmp_path / "e1")


def test_corrupt_release_or_manifest_json_is_rejected(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    (root / "release.json").write_text("{not json")
    with pytest.raises(EnvironmentContractError, match="JSON"):
        load_environment(root, tmp_path / "e1")
    root2 = build_release(tmp_path / "release2")
    (root2 / MANIFEST_PATH).write_text("[not an object]")
    with pytest.raises(EnvironmentContractError):
        load_environment(root2, tmp_path / "e1")


def test_start_schema_with_non_object_root_is_rejected_at_load(tmp_path: Path) -> None:
    with pytest.raises(EnvironmentContractError):
        load_ok(tmp_path, start_schema={"type": "string"})


def test_reset_observation_schema_may_describe_any_json_value(tmp_path: Path) -> None:
    # Any-root reset observation schemas are legal; the loader must accept one
    # even though this mechanical fixture's reset result would not match it.
    env = load_ok(tmp_path, reset_observation_schema={"type": "array"})
    assert {spec["name"] for spec in env.tools()} == {"next_value", "echo", "refuse"}


def test_start_schema_with_remote_ref_is_rejected_at_load(tmp_path: Path) -> None:
    bad = {"type": "object", "properties": {"a": {"$ref": "http://example.com/x.json"}}}
    with pytest.raises(EnvironmentContractError):
        load_ok(tmp_path, start_schema=bad)


def test_factory_module_must_be_importable(tmp_path: Path) -> None:
    with pytest.raises(EnvironmentContractError, match="fx_does_not_exist"):
        load_ok(tmp_path, factory="fx_does_not_exist:make_environment")


def test_factory_attribute_must_be_callable(tmp_path: Path) -> None:
    with pytest.raises(EnvironmentContractError, match="callable"):
        load_ok(tmp_path, factory="fx_bad_factories:NOT_CALLABLE")


def test_factory_must_return_the_canonical_surface(tmp_path: Path) -> None:
    with pytest.raises(EnvironmentContractError, match="close|invoke|tools|reset"):
        load_ok(tmp_path, factory="fx_bad_factories:make_incomplete")
    with pytest.raises(EnvironmentContractError, match="close|invoke|tools|reset"):
        load_ok(tmp_path, factory="fx_bad_factories:make_non_environment")


def test_cold_shaped_use_reset_tools_invoke_invoke_close(tmp_path: Path) -> None:
    root = build_release(tmp_path / "release")
    env = load_environment(root, tmp_path / "episodes" / "e1")
    initial = env.reset()
    specs = env.tools()
    by_name = {spec["name"]: spec for spec in specs}
    first = env.invoke("next_value", {})
    second = env.invoke("echo", {"value": first["data"]["value"]})
    assert initial["kind"] == "mechanical"
    assert set(by_name) == {"next_value", "echo", "refuse"}
    assert second["data"]["value"] == first["data"]["value"]
    env.close()
