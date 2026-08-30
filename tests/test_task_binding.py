from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_task_specification import _capability, _obligations, _proposal

from agent_env_foundry.semantics import (
    BindingCandidate,
    ConditionCheckResult,
    ConditionSpec,
    PublicFieldSource,
    PublicValueSource,
    StartCase,
)
from agent_env_foundry.task_binding import (
    TaskBindingError,
    materialize_task_specification,
)
from agent_env_foundry.task_specification import (
    compile_task_semantic_section,
    compile_verifier_bundle,
)


def _binding() -> BindingCandidate:
    return BindingCandidate(
        semantic_key="file:README.md",
        eligible=True,
        reason_codes=(),
        protected_binding={"native_path": "private/README.md", "row_id": 17},
        public_descriptor={"path": "README.md"},
        facets={},
        public_sources=(
            PublicFieldSource(
                "/public_descriptor/path",
                PublicValueSource("task_literal", None, None, "README.md"),
            ),
        ),
    )


def _prepared(capability, obligations, *, condition_status: str | None = None):
    class Actor:
        def reset(self, _start):
            return {"branch": "main", "clean": condition_status != "false"}

    class Trusted:
        def inspect(self, _root: Path):
            return {"branch": "main", "clean": condition_status != "false"}

        def capabilities(self):
            return (capability,)

        def enumerate_bindings(self, _capability_id, _facts):
            return (_binding(),)

        def evaluate_condition(self, _request):
            return ConditionCheckResult(condition_status or "abstain", {}, ())

    class Session:
        actor = Actor()
        trusted = Trusted()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    return SimpleNamespace(
        identity=SimpleNamespace(release_id="a" * 64),
        start_cases=(StartCase("clean-start", None, ("clean",)),),
        requirement_obligations=obligations,
        open=lambda _root: Session(),
    )


def test_public_binding_closes_constraints_operands_and_answer_without_semantic_drift(
    tmp_path: Path,
) -> None:
    obligations = _obligations()
    capability = _capability()
    semantic = compile_task_semantic_section(
        _proposal(obligations),
        capabilities=(capability,),
        obligations=obligations,
    )
    verifier = compile_verifier_bundle(
        semantic,
        capabilities=(capability,),
        obligations=obligations,
    )
    original_digest = semantic.semantic_digest

    specification = materialize_task_specification(
        _prepared(capability, obligations),
        semantic,
        verifier,
        tmp_path / "instance",
        start_case_id="clean-start",
    )

    assert specification.semantic.semantic_digest == original_digest
    assert specification.binding.semantic_digest == original_digest
    assert "README.md" in specification.instruction
    assert "private/README.md" not in specification.instruction
    assert "row_id" not in specification.instruction
    for obligation in obligations:
        assert specification.instruction.count(obligation.canonical_text) == 1
    assert {
        item["obligation_id"] for item in specification.public_closure.constraint_disclosures
    } == {item.obligation_id for item in obligations}
    assert {item["source_key"] for item in specification.public_closure.operand_sources} == {
        "slot:target:/public_descriptor/path",
        "answer:CAP-GIT-UPDATE-COMMIT-PERSIST:created_commit_id",
    }
    assert specification.specification_id

    with pytest.raises(TaskBindingError, match="constraint disclosures"):
        replace(
            specification,
            public_closure=replace(
                specification.public_closure,
                constraint_disclosures=specification.public_closure.constraint_disclosures[:-1],
            ),
        )


def test_false_condition_handle_is_recorded_irrelevant_not_self_waived(
    tmp_path: Path,
) -> None:
    obligations = _obligations()
    conditional = replace(
        obligations[2],
        applicability=replace(
            obligations[2].applicability,
            kind="condition_branch",
            capability_id=None,
            condition_id="COND-CAN-COMMIT",
            branch="true",
        ),
    )
    selected = (*obligations[:2], conditional)
    capability = replace(
        _capability(),
        conditions=(
            ConditionSpec(
                "COND-CAN-COMMIT",
                "repository permits a commit",
                "world",
                ("CAP-GIT-UPDATE-COMMIT-PERSIST",),
                (),
                None,
                PublicValueSource("reset", None, "/clean", None),
            ),
        ),
    )
    semantic = compile_task_semantic_section(
        replace(_proposal(selected), condition_id="COND-CAN-COMMIT"),
        capabilities=(capability,),
        obligations=selected,
    )
    verifier = compile_verifier_bundle(
        semantic,
        capabilities=(capability,),
        obligations=selected,
    )

    with pytest.raises(TaskBindingError) as unresolved:
        materialize_task_specification(
            _prepared(capability, selected),
            semantic,
            verifier,
            tmp_path / "unresolved",
            start_case_id="clean-start",
        )
    assert unresolved.value.code == "task_condition_unresolved"

    specification = materialize_task_specification(
        _prepared(capability, selected, condition_status="false"),
        semantic,
        verifier,
        tmp_path / "instance",
        start_case_id="clean-start",
    )
    dispositions = {
        item["obligation_id"]: item for item in specification.binding.obligation_dispositions
    }
    assert dispositions[conditional.obligation_id]["applicable"] is False
    assert conditional.canonical_text not in specification.instruction
