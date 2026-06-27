from __future__ import annotations

import json
from typing import Any

from agent_world.artifacts import make_artifact


def independent_review(
    *,
    stage: str,
    artifact: dict[str, Any],
    need_spec: dict[str, Any] | None = None,
    upstream_artifacts: list[dict[str, Any]] | None = None,
    gate_checklist: list[str] | None = None,
    source_of_truth_refs: list[str],
    reviewer_ref: str,
    invocation_ref: str | None = None,
    reviewer_output: str | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    upstream_artifacts = upstream_artifacts or []
    gate_checklist = gate_checklist or []
    status = "pass"
    if reviewer_ref == artifact.get("producer"):
        status = "fail"
        findings.append(
            {
                "requirement_ref": "docs/agent-world-environment-generation.zh.md#9.1",
                "finding": "reviewer cannot be the same producer as the reviewed artifact",
                "severity": "high",
                "evidence": artifact["id"],
            }
        )
    if not source_of_truth_refs:
        status = "fail"
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "review lacks source-of-truth refs", artifact["id"]))
    if not gate_checklist:
        status = "fail"
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "review lacks gate checklist", artifact["id"]))
    if stage != "S0" and not upstream_artifacts:
        status = "fail"
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "review lacks upstream accepted artifacts", artifact["id"]))
    if need_spec:
        _check_no_scope_drift(stage, artifact, need_spec, upstream_artifacts, findings)
    parsed_output = _parse_reviewer_output(reviewer_output, artifact["id"], findings) if invocation_ref else {}
    if findings:
        status = "fail"
    elif parsed_output:
        status = parsed_output["alignment_status"]
        if status == "pass" and (parsed_output.get("drift_findings") or parsed_output.get("required_fixes")):
            findings.append(
                _finding(
                    "docs/agent-world-environment-generation.zh.md#9.1",
                    "reviewer output cannot pass with drift findings or required fixes",
                    artifact["id"],
                )
            )
            status = "fail"
        for risk in parsed_output.get("waived_risks", []):
            if not isinstance(risk, dict) or not all(key in risk for key in ["risk", "reason", "approver"]):
                findings.append(
                    _finding(
                        "docs/agent-world-environment-generation.zh.md#10.14",
                        "waived risk lacks risk/reason/approver",
                        artifact["id"],
                    )
                )
                status = "fail"
    fields = {
        "review_id": f"review-{stage.lower()}-{artifact['id']}",
        "reviewed_artifact_ids": parsed_output.get("reviewed_artifact_ids", [artifact["id"]]),
        "source_of_truth_refs": source_of_truth_refs,
        "reviewer_ref": invocation_ref or reviewer_ref,
        "review_type": "llm_agent" if invocation_ref else "static_check",
        "alignment_status": status,
        "drift_findings": findings + parsed_output.get("drift_findings", []),
        "required_fixes": [finding["finding"] for finding in findings] + [str(item) for item in parsed_output.get("required_fixes", [])],
        "waived_risks": parsed_output.get("waived_risks", []),
        "upstream_artifact_ids": [item["id"] for item in upstream_artifacts],
        "gate_checklist": gate_checklist,
        "reviewer_output_ref": invocation_ref or "",
        "reviewer_note": parsed_output.get("reviewer_note", ""),
    }
    return make_artifact(
        "ReviewRecord",
        source_stage=stage,
        producer=reviewer_ref,
        fields=fields,
        artifact_id=fields["review_id"],
        inputs=[artifact["id"]],
        status="accepted" if status == "pass" else status,
    )


def _finding(requirement_ref: str, finding: str, evidence: str, severity: str = "high") -> dict[str, Any]:
    return {"requirement_ref": requirement_ref, "finding": finding, "severity": severity, "evidence": evidence}


def _parse_reviewer_output(output: str | None, expected_artifact_id: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    if not output:
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "review invocation produced no structured output", expected_artifact_id))
        return {}
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "review invocation output is not JSON", expected_artifact_id))
        return {}
    if not isinstance(parsed, dict):
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "review invocation output is not a JSON object", expected_artifact_id))
        return {}
    required = {"alignment_status", "reviewed_artifact_ids", "drift_findings", "required_fixes", "waived_risks"}
    missing = sorted(required - set(parsed))
    if missing:
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", f"review invocation output missing {missing}", expected_artifact_id))
        return {}
    if parsed["alignment_status"] not in {"pass", "fail", "needs_human"}:
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "review invocation output has invalid alignment_status", expected_artifact_id))
    parsed["reviewed_artifact_ids"] = _string_list(parsed.get("reviewed_artifact_ids"))
    if expected_artifact_id not in parsed["reviewed_artifact_ids"]:
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "review invocation did not review current artifact", expected_artifact_id))
    parsed["drift_findings"] = _normalize_drift_findings(parsed.get("drift_findings"), expected_artifact_id, findings)
    parsed["required_fixes"] = _string_list(parsed.get("required_fixes"))
    parsed["waived_risks"] = _normalize_waived_risks(parsed.get("waived_risks"), expected_artifact_id, findings)
    parsed["reviewer_note"] = str(parsed.get("reviewer_note", ""))
    return parsed


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _normalize_drift_findings(value: Any, expected_artifact_id: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        findings.append(
            _finding(
                "docs/agent-world-environment-generation.zh.md#9.1",
                "review invocation drift_findings is not a list",
                expected_artifact_id,
            )
        )
        value = [value]
    normalized = []
    for item in value:
        if isinstance(item, dict) and all(key in item for key in ["requirement_ref", "finding", "severity", "evidence"]):
            normalized.append(
                {
                    "requirement_ref": str(item["requirement_ref"]),
                    "finding": str(item["finding"]),
                    "severity": str(item["severity"]),
                    "evidence": str(item["evidence"]),
                }
            )
            continue
        findings.append(
            _finding(
                "docs/agent-world-environment-generation.zh.md#9.1",
                "review invocation drift finding was not in contract shape",
                expected_artifact_id,
            )
        )
        normalized.append(
            _finding(
                "docs/agent-world-environment-generation.zh.md#9.1",
                str(item),
                expected_artifact_id,
                "medium",
            )
        )
    return normalized


def _normalize_waived_risks(value: Any, expected_artifact_id: str, findings: list[dict[str, Any]]) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        findings.append(
            _finding(
                "docs/agent-world-environment-generation.zh.md#10.14",
                "review invocation waived_risks is not a list",
                expected_artifact_id,
            )
        )
        value = [value]
    normalized = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(
                {
                    "risk": str(item.get("risk", "")),
                    "reason": str(item.get("reason", "")),
                    "approver": str(item.get("approver", "")),
                }
            )
        else:
            findings.append(
                _finding(
                    "docs/agent-world-environment-generation.zh.md#10.14",
                    "review invocation waived risk was not in contract shape",
                    expected_artifact_id,
                )
            )
            normalized.append({"risk": str(item), "reason": "reviewer_output_unstructured", "approver": ""})
    return normalized


def _check_no_scope_drift(
    stage: str,
    artifact: dict[str, Any],
    need_spec: dict[str, Any],
    upstream_artifacts: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    encoded = str(artifact).lower()
    forbidden = {
        "training integration": "training",
        "reward export": "reward",
        "awm reproduction": "awm reproduction",
        "mcp-only": "mcp-only",
        "cli-only": "cli-only",
    }
    for label, needle in forbidden.items():
        if needle in encoded and stage not in {"S0", "S9", "S10", "S11"}:
            findings.append(_finding("docs/agent-world-environment-generation.zh.md#8", f"artifact may drift toward {label}", artifact["id"], "medium"))
    domain_seed = str(need_spec.get("domain_seed", "")).lower()
    upstream_encoded = " ".join(str(item).lower() for item in upstream_artifacts)
    if stage in {"S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"} and domain_seed and domain_seed not in encoded and domain_seed not in upstream_encoded:
        findings.append(_finding("docs/agent-world-environment-generation.zh.md#9.1", "artifact does not reference the accepted domain seed", artifact["id"], "medium"))
