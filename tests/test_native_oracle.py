from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_env_foundry.native_oracle import NativeOracleFailure, run_native_oracle_atom
from agent_env_foundry.qualification import QualificationConfig
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    BindingCandidate,
    CapabilitySpec,
    RenderingSpec,
    StartCase,
    TraceEvent,
)


def _capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="finish-item",
        requirement_ids=("REQ-1",),
        workflow_ids=("workflow",),
        composition_rules=(),
        actor_role="operator",
        task_kind="state_change",
        intent_label="finish the selected item",
        protected_binding_schema={"type": "object", "additionalProperties": True},
        public_descriptor_schema={"type": "object", "additionalProperties": True},
        facets=(),
        conditions=(),
        answer_fields=(),
        read_scopes=("items",),
        write_scopes=("items",),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("finish", "item", None),
    )


def _binding() -> BindingCandidate:
    return BindingCandidate("alpha", True, (), {"id": "private-alpha"}, {"name": "alpha"}, {})


def _instances(tmp_path: Path) -> tuple[Path, Path]:
    before, after = tmp_path / "source-before", tmp_path / "source-after"
    before.mkdir()
    after.mkdir()
    before.joinpath("state.json").write_text(json.dumps({"done": False}))
    after.joinpath("state.json").write_text(json.dumps({"done": True}))
    return before, after


def _probe(
    path: Path,
    *,
    corrupt_digest: bool = False,
    mutate_request: bool = False,
    mutate_request_mode: bool = False,
    mutate_instance: bool = False,
) -> str:
    source = """from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

mode, request_path, result_path = sys.argv[1:4]
assert mode == "semantic-check"
request_bytes = Path(request_path).read_bytes()
request = json.loads(request_bytes)
root = Path(request_path).parent
before = json.loads((root / request["before_path"] / "state.json").read_text())
after = json.loads((root / request["after_path"] / "state.json").read_text())
satisfied = before["done"] is False and after["done"] is True
result = {
    "format": "native-semantic-result/1",
    "request_digest": %s,
    "materialization_id": request["materialization_id"],
    "capability_id": request["capability"]["capability_id"],
    "public_binding": request["public_binding"],
    "atom_result": {
        "initially_satisfied": False,
        "satisfied": satisfied,
        "required_effects_ok": satisfied,
        "collateral_ok": True,
        "answer_ok": None,
        "process_ok": None,
        "report_values": {},
        "failure_codes": [] if satisfied else ["native-not-finished"],
    },
    "native_observations": [{"before": before, "after": after}],
    "source_use": {"reader": "json", "purpose": "test native state"},
}
Path(result_path).write_text(json.dumps(result, sort_keys=True))
""" % ('"0" * 64' if corrupt_digest else "hashlib.sha256(request_bytes).hexdigest()")
    if mutate_request:
        source += (
            "Path(request_path).chmod(0o644)\n"
            'Path(request_path).write_bytes(request_bytes + b" ")\n'
            "Path(request_path).chmod(0o444)\n"
        )
    if mutate_request_mode:
        source += "Path(request_path).chmod(0o644)\n"
    if mutate_instance:
        source += '(root / request["after_path"] / "state.json").write_text("{}")\n'
    path.write_text(source)
    manifest = {
        "format": "qualification-probes/2",
        "files": [
            {
                "path": "native_probe.py",
                "digest": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        ],
    }
    payload = canonical_bytes(manifest)
    path.with_name("probe_manifest.json").write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_native_oracle_binds_one_real_materialization_and_typed_result(tmp_path: Path) -> None:
    before, after = _instances(tmp_path)
    probe = tmp_path / "native_probe.py"
    bundle_digest = _probe(probe)
    binding = _binding()
    evidence = run_native_oracle_atom(
        probe_path=probe,
        runtime_root=tmp_path / "oracle-runtime",
        materialization_id="primary-001",
        role="primary",
        candidate_digest="a" * 64,
        expected_task_semantics_digest="b" * 64,
        semantics_digest="c" * 64,
        oracle_bundle_digest=bundle_digest,
        capability=_capability(),
        start_case=StartCase("base", None, ("base",)),
        before_instance=before,
        after_instance=after,
        public_binding=binding.public_document(),
        trace=(
            TraceEvent(
                1,
                "finish",
                {"name": "alpha"},
                {"ok": True, "data": {"name": "alpha", "done": True}, "error": None},
            ),
        ),
        final_answer=None,
        config=QualificationConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert evidence.materialization_id == "primary-001"
    assert evidence.atom_result.satisfied
    assert evidence.public_binding == binding.public_document()
    assert evidence.request_digest and evidence.result_digest
    assert json.loads((tmp_path / "source-before/state.json").read_text()) == {"done": False}
    assert json.loads((tmp_path / "source-after/state.json").read_text()) == {"done": True}

    with pytest.raises(NativeOracleFailure) as repeated:
        run_native_oracle_atom(
            probe_path=probe,
            runtime_root=tmp_path / "oracle-runtime",
            materialization_id="primary-001",
            role="primary",
            candidate_digest="a" * 64,
            expected_task_semantics_digest="b" * 64,
            semantics_digest="c" * 64,
            oracle_bundle_digest=bundle_digest,
            capability=_capability(),
            start_case=StartCase("base", None, ("base",)),
            before_instance=before,
            after_instance=after,
            public_binding=binding.public_document(),
            trace=(),
            final_answer=None,
            config=QualificationConfig(uv_cache_dir=tmp_path / "uv-cache"),
        )
    assert repeated.value.code == "native_oracle_materialization_not_fresh"


def test_native_oracle_rejects_result_not_bound_to_exact_request(tmp_path: Path) -> None:
    before, after = _instances(tmp_path)
    probe = tmp_path / "native_probe.py"
    bundle_digest = _probe(probe, corrupt_digest=True)

    with pytest.raises(NativeOracleFailure, match="request digest"):
        run_native_oracle_atom(
            probe_path=probe,
            runtime_root=tmp_path / "oracle-runtime",
            materialization_id="primary-001",
            role="primary",
            candidate_digest="a" * 64,
            expected_task_semantics_digest="b" * 64,
            semantics_digest="c" * 64,
            oracle_bundle_digest=bundle_digest,
            capability=_capability(),
            start_case=StartCase("base", None, ("base",)),
            before_instance=before,
            after_instance=after,
            public_binding=_binding().public_document(),
            trace=(),
            final_answer=None,
            config=QualificationConfig(uv_cache_dir=tmp_path / "uv-cache"),
        )


def test_native_oracle_rejects_probe_bytes_changed_after_bundle_admission(tmp_path: Path) -> None:
    before, after = _instances(tmp_path)
    probe = tmp_path / "native_probe.py"
    bundle_digest = _probe(probe)
    probe.write_text(probe.read_text() + "\n# tampered\n")

    with pytest.raises(NativeOracleFailure, match="bundle"):
        run_native_oracle_atom(
            probe_path=probe,
            runtime_root=tmp_path / "oracle-runtime",
            materialization_id="primary-001",
            role="primary",
            candidate_digest="a" * 64,
            expected_task_semantics_digest="b" * 64,
            semantics_digest="c" * 64,
            oracle_bundle_digest=bundle_digest,
            capability=_capability(),
            start_case=StartCase("base", None, ("base",)),
            before_instance=before,
            after_instance=after,
            public_binding=_binding().public_document(),
            trace=(),
            final_answer=None,
            config=QualificationConfig(uv_cache_dir=tmp_path / "uv-cache"),
        )


@pytest.mark.parametrize(
    ("probe_options", "message"),
    [
        ({"mutate_request": True}, "changed its Host request"),
        ({"mutate_request_mode": True}, "changed its Host request"),
        ({"mutate_instance": True}, "changed a controlled actor instance"),
    ],
)
def test_native_oracle_rejects_request_or_instance_mutation(
    tmp_path: Path,
    probe_options: dict[str, bool],
    message: str,
) -> None:
    before, after = _instances(tmp_path)
    probe = tmp_path / "native_probe.py"
    bundle_digest = _probe(probe, **probe_options)

    with pytest.raises(NativeOracleFailure, match=message):
        run_native_oracle_atom(
            probe_path=probe,
            runtime_root=tmp_path / "oracle-runtime",
            materialization_id="primary-001",
            role="primary",
            candidate_digest="a" * 64,
            expected_task_semantics_digest="b" * 64,
            semantics_digest="c" * 64,
            oracle_bundle_digest=bundle_digest,
            capability=_capability(),
            start_case=StartCase("base", None, ("base",)),
            before_instance=before,
            after_instance=after,
            public_binding=_binding().public_document(),
            trace=(),
            final_answer=None,
            config=QualificationConfig(uv_cache_dir=tmp_path / "uv-cache"),
        )
