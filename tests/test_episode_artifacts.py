from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast

import pytest

import agent_env_foundry.episode_runtime as runtime
import test_episode_runtime as fixtures
from agent_env_foundry.episodes import TrainingEpisodeView
from agent_env_foundry.public_agent import DriverDecision
from agent_env_foundry.release import canonical_bytes


def _record(
    tmp_path: Path,
    disposition: Literal["success", "failure", "abstain"],
):
    pack, pack_id, _task = fixtures._write_pack(tmp_path, "atom")
    decisions = {
        "success": fixtures._completed(1, "{}"),
        "failure": [
            DriverDecision(calls=(("call-1", "set_value", '{"value":1}'),)),
            DriverDecision(),
        ],
        "abstain": fixtures._completed(1, "{}"),
    }[disposition]
    return runtime.run_task_episode(
        fixtures.Prepared(mode="environment" if disposition == "abstain" else "healthy"),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=fixtures.Driver(decisions),
        rollout_index=1,
        instance_root=tmp_path / f"instance-{disposition}",
    )


@pytest.mark.parametrize(
    ("disposition", "expected_disposition", "expected_reward", "completion_kind"),
    (
        ("success", "verified_success", 1.0, "completed"),
        ("failure", "verified_failure", 0.0, "policy_failure"),
        ("abstain", "abstain", None, None),
    ),
)
def test_training_view_is_the_exact_public_reward_projection(
    tmp_path: Path,
    disposition: Literal["success", "failure", "abstain"],
    expected_disposition: str,
    expected_reward: float | None,
    completion_kind: str | None,
) -> None:
    record = _record(tmp_path, disposition)
    view = runtime._training_view(record)
    document = view.to_document()

    assert set(document) == {
        "format",
        "episode_id",
        "request_id",
        "request",
        "public_input",
        "turns",
        "completion",
        "disposition",
        "reward",
    }
    assert document["format"] == "training-episode-view/1"
    assert document["episode_id"] == record.episode_id
    assert document["request_id"] == record.request.request_id
    assert document["request"] == record.request.to_document()
    assert set(document["public_input"]) == {
        "system_prompt",
        "instruction",
        "reset_observation",
        "tool_specs",
        "answer_schema",
    }
    assert all(
        set(turn) == {"turn_index", "calls", "raw_public_terminal"} for turn in document["turns"]
    )
    assert all(
        set(call)
        == {
            "raw_call_id",
            "raw_tool_name",
            "call_id",
            "tool_name",
            "raw_arguments",
            "parsed_arguments",
            "parse_status",
            "schema_status",
            "dispatch_status",
            "observation",
        }
        for turn in document["turns"]
        for call in turn["calls"]
    )
    if completion_kind is None:
        assert document["completion"] is None
    else:
        assert set(document["completion"]) == {
            "terminal_kind",
            "final_answer",
            "terminal_code",
        }
        assert document["completion"]["terminal_kind"] == completion_kind
    assert document["disposition"] == expected_disposition
    assert document["reward"] == expected_reward

    assert "policy_spec" not in document
    assert "defect" not in document
    assert "abstain_owner" not in document
    assert "lifecycle_events" not in document
    assert "checker_documents" not in document
    assert "reload_evidence" not in document
    assert all("usage" not in turn for turn in document["turns"])


def test_training_view_allows_business_usage_and_checker_keys_and_snapshots_aliases(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, "success")
    business = {"usage": {"checker": ["ordinary", "business", "data"]}}
    changed_input = replace(record.capture.public_input, reset_observation=business)
    changed = replace(
        record,
        capture=replace(record.capture, public_input=changed_input),
        episode_id="",
    )
    projected = runtime._training_view(changed)
    turn_alias = projected.to_document()["turns"][0]
    view = TrainingEpisodeView(
        projected.episode_id,
        projected.request_id,
        projected.request,
        projected.public_input,
        (turn_alias,),
        projected.completion,
        projected.disposition,
        projected.reward,
    )
    expected = view.to_document()

    business["usage"]["checker"].append("caller mutation")
    turn_alias["calls"][0]["raw_arguments"] = "caller mutation"
    assert view.to_document() == expected
    assert expected["public_input"]["reset_observation"] == {
        "usage": {"checker": ["ordinary", "business", "data"]}
    }

    emitted = view.to_document()
    emitted["public_input"]["reset_observation"]["usage"]["checker"].append("emitted mutation")
    emitted["turns"][0]["calls"][0]["raw_arguments"] = "emitted mutation"
    assert view.to_document() == expected


@pytest.mark.parametrize("disposition", ("success", "failure", "abstain"))
def test_paired_bundle_cold_reads_after_relocation(
    tmp_path: Path,
    disposition: Literal["success", "failure", "abstain"],
) -> None:
    record = _record(tmp_path, disposition)
    output = tmp_path / "bundle"
    view = runtime.write_episode_bundle(output, record)
    directory = output / "episodes" / record.episode_id

    assert {item.name for item in directory.iterdir()} == {
        "EpisodeRecord.json",
        "TrainingEpisodeView.json",
    }
    for path in directory.iterdir():
        assert path.read_bytes() == canonical_bytes(json.loads(path.read_bytes()))
    assert runtime.read_episode_bundle(output, record.episode_id) == view

    relocated = tmp_path / "relocated"
    shutil.copytree(output, relocated)
    assert runtime.read_episode_bundle(relocated, record.episode_id) == view


@pytest.mark.parametrize(
    "mutation",
    (
        "public_call",
        "public_terminal",
        "view_reward",
        "trusted_checker",
        "excluded_usage",
        "lifecycle",
        "view_checker_field",
    ),
)
def test_paired_reader_rejects_record_or_view_tampering(
    tmp_path: Path,
    mutation: str,
) -> None:
    record = _record(tmp_path, "success")
    output = tmp_path / "bundle"
    expected_view = runtime.write_episode_bundle(output, record).to_document()
    directory = output / "episodes" / record.episode_id
    record_path = directory / "EpisodeRecord.json"
    view_path = directory / "TrainingEpisodeView.json"
    record_document = cast(dict[str, Any], json.loads(record_path.read_bytes()))
    view_document = cast(dict[str, Any], json.loads(view_path.read_bytes()))

    if mutation == "public_call":
        record_document["capture"]["turns"][0]["calls"][0]["observation"] = {
            "ok": True,
            "data": {"value": 99},
            "error": None,
        }
        record_path.write_bytes(canonical_bytes(record_document))
    elif mutation == "public_terminal":
        record_document["capture"]["turns"][1]["raw_public_terminal"] = '{"changed":true}'
        record_path.write_bytes(canonical_bytes(record_document))
    elif mutation == "view_reward":
        view_document["reward"] = 0
        view_path.write_bytes(canonical_bytes(view_document))
    elif mutation == "trusted_checker":
        record_document["checker_documents"]["atom"]["result"]["report_values"] = {"changed": True}
        record_path.write_bytes(canonical_bytes(record_document))
    elif mutation == "excluded_usage":
        record_document["capture"]["turns"][0]["usage"] = {"input_tokens": 999}
        record_path.write_bytes(canonical_bytes(record_document))
        assert json.loads(view_path.read_bytes()) == expected_view
    elif mutation == "lifecycle":
        record_document["lifecycle_events"][0]["seq"] = 2
        record_path.write_bytes(canonical_bytes(record_document))
    else:
        view_document["checker"] = {"leak": True}
        view_path.write_bytes(canonical_bytes(view_document))

    with pytest.raises(ValueError):
        runtime.read_episode_bundle(output, record.episode_id)


@pytest.mark.parametrize(
    ("kind", "mutation"),
    (
        ("atom", "evaluation_context"),
        ("atom", "protected_binding"),
        ("if", "condition_binding"),
        ("if", "condition_id"),
    ),
)
def test_paired_reader_rejects_malformed_checker_request_under_fresh_identity(
    tmp_path: Path,
    kind: Literal["atom", "if"],
    mutation: str,
) -> None:
    pack, pack_id, _task = fixtures._write_pack(tmp_path, kind)
    record = runtime.run_task_episode(
        fixtures.Prepared(),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=fixtures.Driver(fixtures._completed(1, "{}")),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )
    output = tmp_path / "bundle"
    view = runtime.write_episode_bundle(output, record).to_document()
    document = record.to_document()

    checker = cast(dict[str, Any], document["checker_documents"])
    if mutation == "evaluation_context":
        checker["atom"]["request"]["evaluation_context"] = {"garbage": True}
    elif mutation == "protected_binding":
        checker["atom"]["request"]["protected_binding"] = []
    elif mutation == "condition_binding":
        checker["if"]["condition"]["request"]["protected_binding"] = []
    else:
        checker["if"]["condition"]["request"]["condition_id"] = ""

    changed_id = fixtures._sha(
        {key: value for key, value in document.items() if key != "episode_id"}
    )
    document["episode_id"] = changed_id
    view["episode_id"] = changed_id
    directory = output / "episodes" / record.episode_id
    changed_directory = output / "episodes" / changed_id
    directory.rename(changed_directory)
    (changed_directory / "EpisodeRecord.json").write_bytes(canonical_bytes(document))
    (changed_directory / "TrainingEpisodeView.json").write_bytes(canonical_bytes(view))

    with pytest.raises(ValueError):
        runtime.read_episode_bundle(output, changed_id)


@pytest.mark.parametrize("present", ("record", "view"))
def test_paired_reader_rejects_partial_bundle(tmp_path: Path, present: str) -> None:
    record = _record(tmp_path, "success")
    output = tmp_path / "partial"
    directory = output / "episodes" / record.episode_id
    directory.mkdir(parents=True)
    if present == "record":
        (directory / "EpisodeRecord.json").write_bytes(canonical_bytes(record.to_document()))
    else:
        (directory / "TrainingEpisodeView.json").write_bytes(
            canonical_bytes(runtime._training_view(record).to_document())
        )

    with pytest.raises(ValueError, match="exactly two"):
        runtime.read_episode_bundle(output, record.episode_id)


def test_paired_reader_rejects_extra_file_symlink_and_noncanonical_bytes(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, "success")

    extra_output = tmp_path / "extra"
    runtime.write_episode_bundle(extra_output, record)
    extra_directory = extra_output / "episodes" / record.episode_id
    (extra_directory / "extra.json").write_text("{}")
    with pytest.raises(ValueError, match="exactly two"):
        runtime.read_episode_bundle(extra_output, record.episode_id)

    symlink_output = tmp_path / "symlink"
    runtime.write_episode_bundle(symlink_output, record)
    symlink_record = symlink_output / "episodes" / record.episode_id / "EpisodeRecord.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(canonical_bytes(record.to_document()))
    symlink_record.unlink()
    symlink_record.symlink_to(outside)
    with pytest.raises(ValueError, match="ordinary files"):
        runtime.read_episode_bundle(symlink_output, record.episode_id)

    noncanonical_output = tmp_path / "noncanonical"
    runtime.write_episode_bundle(noncanonical_output, record)
    noncanonical_record = (
        noncanonical_output / "episodes" / record.episode_id / "EpisodeRecord.json"
    )
    raw = json.loads(noncanonical_record.read_bytes())
    noncanonical_record.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="canonical"):
        runtime.read_episode_bundle(noncanonical_output, record.episode_id)


def test_bundle_collision_and_directory_identity_fail_without_overwrite(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, "success")
    output = tmp_path / "bundle"
    runtime.write_episode_bundle(output, record)
    directory = output / "episodes" / record.episode_id
    before = {item.name: item.read_bytes() for item in directory.iterdir()}

    with pytest.raises(ValueError, match="absent"):
        runtime.write_episode_bundle(output, record)
    assert {item.name: item.read_bytes() for item in directory.iterdir()} == before

    copied_id = "f" * 64
    shutil.copytree(directory, output / "episodes" / copied_id)
    with pytest.raises(ValueError, match="identity"):
        runtime.read_episode_bundle(output, copied_id)


def test_business_named_keys_survive_the_paired_reader_without_structural_leakage(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, "success")
    changed_input = replace(
        record.capture.public_input,
        reset_observation={"usage": {"checker": {"lifecycle": "business"}}},
    )
    changed = replace(
        record,
        capture=replace(record.capture, public_input=changed_input),
        episode_id="",
    )
    output = tmp_path / "bundle"
    view = runtime.write_episode_bundle(output, changed)

    assert view.to_document()["public_input"]["reset_observation"] == {
        "usage": {"checker": {"lifecycle": "business"}}
    }
    assert all("usage" not in turn for turn in view.to_document()["turns"])

    emitted = runtime.read_episode_bundle(output, changed.episode_id).to_document()
    emitted["public_input"]["reset_observation"]["usage"]["checker"] = "mutated"
    assert (
        runtime.read_episode_bundle(output, changed.episode_id).to_document() == view.to_document()
    )


def test_distinct_episode_bundles_share_one_new_batch_root(tmp_path: Path) -> None:
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = _record(first_root, "success")
    second = _record(second_root, "failure")
    assert first.episode_id != second.episode_id
    output = tmp_path / "batch-output"

    runtime.write_episode_bundle(output, first)
    runtime.write_episode_bundle(output, second)

    assert runtime.read_episode_bundle(output, first.episode_id).episode_id == first.episode_id
    assert runtime.read_episode_bundle(output, second.episode_id).episode_id == second.episode_id
