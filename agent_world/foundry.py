"""One small, sequential Direct path from a need to a Registry package."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from agent_world.artifacts import ArtifactStore, safe_url
from agent_world.config import (
    ConfigurationError,
    FoundrySettings,
    credential_from_environment,
    load_settings,
)
from agent_world.contracts import (
    ArtifactRef,
    CandidateManifest,
    DesignContract,
    DirectRun,
    EnvironmentRequest,
    GateResult,
    GateStatus,
    JudgeReport,
    PublicStep,
    RegistryReceipt,
    SafeFailure,
    ToolDraft,
)
from agent_world.invocation import CodexAgentBackend, DirectChatBackend, InvocationError
from agent_world.runtime import integrate, judge

_HTTP_TIMEOUT_SECONDS = 120
_URL = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
_MODEL_AUTHORITY_FIELDS = frozenset(
    {"hash", "digest", "manifest", "gate", "judge", "release", "reward", "termination", "seed"}
)

_RESEARCH_SKILL = """---
name: research-world-evidence
description: Synthesize bounded source evidence for one Foundry request.
---

Read `.foundry-evidence.json`. Produce only short, source-backed claims. Do not
invent sources, write candidate code, or decide any gate or release outcome.
Return exactly {"claims":["short source-backed claim"]}. Before returning,
self-check that `claims` contains 1-8 unique, nonempty short source-backed text
items.
"""

_PLAN_SKILL = """---
name: engineer-build-planning
description: Give a compact implementation plan for one frozen design.
---

Read `.foundry-design.json`. Return implementation advice only. Do not write
candidate files, change the design, run a candidate, or decide verification.
Return exactly {"steps":["short advisory item"]}. Before returning, self-check
that `steps` contains 1-8 unique, nonempty items, each at most 500 characters.
"""

_CHALLENGE_SKILL = """---
name: challenge-agent-world
description: Identify public conformance risks in one frozen design.
---

Read `.foundry-design.json`. Return only concise public risks. Do not write
candidate code, read sealed data, or decide a Judge or release verdict.
Return exactly {"risks":["short public risk"]}. Before returning, self-check
that `risks` contains 1-8 unique, nonempty items, each at most 500 characters.
"""

_CODEGEN_SKILL = """---
name: engineer-environment-codegen
description: Implement one standalone candidate runtime from a frozen design.
---

Read `.foundry-design.json`, `.foundry-plan.json`, and `.foundry-challenge.json`.
Write only `runtime.py` in the current workspace. It must be a standalone Python
JSONL server: `handshake` returns exactly operations handshake/reset/invoke/close;
`reset` returns status ok; `invoke` accepts tool and arguments and returns status
ok plus result fields required by the design; `close` returns status ok and exits.
Do not write manifests, hashes, package metadata, gates, Judge results, or release
claims. Do not use network access or framework imports.
"""


class FoundryFailure(RuntimeError):
    def __init__(self, failure: SafeFailure) -> None:
        super().__init__(failure.code)
        self.failure = failure


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _reference(ref: ArtifactRef) -> dict[str, str]:
    return {"artifact_id": ref.artifact_id, "kind": ref.kind, "digest": ref.digest}


def _safe_text(value: object, code: str, *, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise FoundryFailure(SafeFailure(code, "rejected"))
    return value.strip()


def _strings(
    value: object,
    code: str,
    *,
    limit: int,
    allow_empty: bool = False,
    item_limit: int = 100,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value) or len(value) > limit:
        raise FoundryFailure(SafeFailure(code, "rejected"))
    output = tuple(_safe_text(item, code, limit=item_limit) for item in value)
    if len(set(output)) != len(output):
        raise FoundryFailure(SafeFailure(code, "rejected"))
    return output


def _atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, path)


class DirectFoundry:
    """The five framework owners assembled as one linear Direct run."""

    def __init__(self, settings: FoundrySettings) -> None:
        self.settings = settings
        self.direct = DirectChatBackend(settings.direct_primary, settings.direct_fallback)
        self.agent = CodexAgentBackend(settings.agent_primary, settings.agent_fallback)

    def generate(self, need: str) -> dict[str, Any]:
        request = EnvironmentRequest.create(need)
        run = DirectRun.create(request)
        store = ArtifactStore(self.settings.state_root / "runs" / run.run_id)
        self._event(store, run, "intake", "passed")

        try:
            research = self._research(request, store)
            self._event(store, run, "research", "passed", (research["artifact"],))

            design = self._design(request, research, store)
            self._event(store, run, "modeling", "passed", (design.artifact,))

            with tempfile.TemporaryDirectory(prefix="foundry-candidate-") as temporary:
                candidate_root = Path(temporary)
                candidate, build_refs = self._build(design, candidate_root, store)
                self._event(store, run, "build", "passed", (candidate.artifact, *build_refs))

                integration = integrate(candidate_root, design.public_steps[0])
                integration_ref = store.put_json("integration", integration)
                self._event(store, run, "integration", integration["status"], (integration_ref,))

                report = self._judge(candidate_root, design, candidate, store)
                self._event(
                    store, run, "judge", "passed" if report.passed else "failed", (report.artifact,)
                )
                if not report.passed:
                    raise FoundryFailure(SafeFailure("judge_required_gate_failed", "rejected"))

                receipt, release_refs = self._release(
                    design, candidate, report, candidate_root, store
                )
                self._event(store, run, "registry", "released", (*release_refs, receipt.artifact))
                run.finish("released", receipt=receipt)
                store.write_run(run.to_dict())
                return self._result(run)
        except FoundryFailure as exc:
            return self._fail(store, run, exc.failure)
        except InvocationError as exc:
            return self._fail(store, run, exc.failure)
        except (OSError, ValueError, zipfile.BadZipFile):
            return self._fail(store, run, SafeFailure("foundry_internal_error", "error"))

    def _event(
        self,
        store: ArtifactStore,
        run: DirectRun,
        stage: str,
        status: str,
        artifacts: tuple[ArtifactRef, ...] = (),
        *,
        code: str | None = None,
    ) -> None:
        run.add_event(stage, status, code=code, artifacts=artifacts)
        store.write_run(run.to_dict())

    def _fail(self, store: ArtifactStore, run: DirectRun, failure: SafeFailure) -> dict[str, Any]:
        self._event(store, run, "failure", "failed", code=failure.code)
        run.finish(failure.status, code=failure.code)
        store.write_run(run.to_dict())
        return self._result(run)

    @staticmethod
    def _result(run: DirectRun) -> dict[str, Any]:
        release = run.release
        return {
            "run_id": run.run_id,
            "status": run.status,
            "release": (
                {
                    "status": "released",
                    "package_id": release.package_id,
                    "version": release.version,
                    "package_digest": release.package_digest,
                    "receipt_digest": release.receipt_digest,
                }
                if release is not None
                else {"status": "not_published"}
            ),
        }

    def _http_text(self, url: str, *, key: str | None, stage: str) -> str:
        headers = {
            "Accept": "text/plain, text/markdown, text/html",
            "User-Agent": "agent-world-foundry/0.3",
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            with urlopen(Request(url, headers=headers), timeout=_HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
                body = response.read()
        except HTTPError as exc:
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
            raise FoundryFailure(SafeFailure(f"{stage}_http_failure", "error", retryable)) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise FoundryFailure(SafeFailure(f"{stage}_network_failure", "error", True)) from exc
        text = body.decode("utf-8", errors="replace").strip()
        if not text:
            raise FoundryFailure(SafeFailure(f"{stage}_empty", "rejected"))
        return text

    @staticmethod
    def _source_urls(search_body: str) -> tuple[str, ...]:
        urls: list[str] = []
        for match in _URL.finditer(search_body):
            url = match.group(0).rstrip(".,;:)")
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower()
            if (
                parsed.scheme not in {"http", "https"}
                or not host
                or host.endswith("jina.ai")
                or host == "localhost"
                or host.endswith(".local")
                or host.startswith("127.")
                or parsed.username
                or parsed.password
            ):
                continue
            if url not in urls:
                urls.append(url)
            if len(urls) == 3:
                break
        return tuple(urls)

    def _research(self, request: EnvironmentRequest, store: ArtifactStore) -> dict[str, Any]:
        try:
            key = credential_from_environment(self.settings.research.api_key_env)
        except ConfigurationError as exc:
            raise FoundryFailure(SafeFailure(str(exc), "needs_human")) from exc

        query = quote(request.need, safe="")
        search_body = self._http_text(
            f"{self.settings.research.search_url}/{query}", key=key, stage="research_search"
        )
        sources = self._source_urls(search_body)
        if not sources:
            raise FoundryFailure(SafeFailure("research_no_provenance_sources", "rejected"))

        staged: list[dict[str, Any]] = []
        commitments: list[dict[str, Any]] = []
        for source in sources:
            document = self._http_text(
                f"{self.settings.research.reader_url}/{source}", key=key, stage="research_fetch"
            )
            body = document.encode("utf-8")
            commitments.append(
                {
                    "url": safe_url(source),
                    "content_digest": f"sha256:{sha256(body).hexdigest()}",
                    "content_length": len(body),
                }
            )
            staged.append({"url": safe_url(source), "text": document[:12000]})

        with tempfile.TemporaryDirectory(prefix="foundry-research-") as temporary:
            workspace = Path(temporary)
            (workspace / ".foundry-evidence.json").write_bytes(
                _canonical({"request_digest": request.need_digest, "sources": staged})
            )
            result = self.agent.invoke_json(
                work="researcher",
                skill_name="research-world-evidence",
                skill_body=_RESEARCH_SKILL,
                workspace=workspace,
                instruction=(
                    "Read staged evidence and return exactly "
                    '{"claims":["short source-backed claim"]}.'
                ),
            )
        claims = _strings(
            result.value.get("claims"), "research_claims_invalid", limit=8, item_limit=500
        )
        artifact = store.put_json(
            "research",
            {"sources": commitments, "claims": claims, "agent_model": result.route_model},
        )
        return {"sources": commitments, "claims": claims, "artifact": artifact}

    def _design(
        self, request: EnvironmentRequest, research: dict[str, Any], store: ArtifactStore
    ) -> DesignContract:
        result = self.direct.invoke_json(
            system=(
                "You are a Direct semantic designer. You have no tools, Skills, "
                "workspace, or release authority. "
                "Return only the requested JSON object."
            ),
            user=json.dumps(
                {
                    "need": request.need,
                    "evidence": {
                        "sources": [item["url"] for item in research["sources"]],
                        "claims": research["claims"],
                    },
                    "output": {
                        "name": "lowercase-kebab-name",
                        "summary": "short semantic description",
                        "tools": [
                            {
                                "name": "tool_name",
                                "description": "what it does",
                                "arguments": ["argument-name"],
                                "result_fields": ["field-name"],
                            }
                        ],
                        "scenario": [
                            {
                                "tool": "tool_name",
                                "arguments": {"argument-name": "public value"},
                                "expected_result": {"field-name": "expected public value"},
                            }
                        ],
                        "invariants": ["short business rule"],
                    },
                    "rules": (
                        "Use exactly these top-level fields, one public scenario, and 1-4 tools. "
                        "Every tool name must use lower snake_case matching [a-z][a-z0-9_]{0,59}; "
                        "the scenario tool must exactly equal one declared tool name. "
                        "Each tool's result_fields must be a nonempty list of at most 6 unique, "
                        "nonempty short public text field names. "
                        "Each tool's arguments must be a list of at most 6 unique, nonempty short "
                        "public argument names; use [] when none. "
                        "Do not include hash, schema, reward, gate, Judge, manifest, seed, "
                        "termination, or release fields."
                    ),
                },
                ensure_ascii=False,
            ),
        )
        return self._compile_design(result.value, store)

    def _compile_design(self, proposal: dict[str, Any], store: ArtifactStore) -> DesignContract:
        if set(proposal) != {"name", "summary", "tools", "scenario", "invariants"}:
            raise FoundryFailure(SafeFailure("design_shape_invalid", "rejected"))
        if _MODEL_AUTHORITY_FIELDS.intersection(proposal):
            raise FoundryFailure(SafeFailure("design_model_authority_claim", "rejected"))
        name = _safe_text(proposal.get("name"), "design_name_invalid", limit=80)
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,79}", name):
            raise FoundryFailure(SafeFailure("design_name_invalid", "rejected"))
        summary = _safe_text(proposal.get("summary"), "design_summary_invalid")
        raw_tools = proposal.get("tools")
        if not isinstance(raw_tools, list) or not 1 <= len(raw_tools) <= 4:
            raise FoundryFailure(SafeFailure("design_tools_invalid", "rejected"))
        tools: list[ToolDraft] = []
        for item in raw_tools:
            if not isinstance(item, dict) or set(item) != {
                "name",
                "description",
                "arguments",
                "result_fields",
            }:
                raise FoundryFailure(SafeFailure("design_tool_invalid", "rejected"))
            tool_name = _safe_text(item.get("name"), "design_tool_invalid", limit=60)
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", tool_name):
                raise FoundryFailure(SafeFailure("design_tool_invalid", "rejected"))
            tools.append(
                ToolDraft(
                    name=tool_name,
                    description=_safe_text(item.get("description"), "design_tool_invalid"),
                    arguments=_strings(
                        item.get("arguments"), "design_tool_invalid", limit=6, allow_empty=True
                    ),
                    result_fields=_strings(
                        item.get("result_fields"), "design_tool_invalid", limit=6
                    ),
                )
            )
        if len({tool.name for tool in tools}) != len(tools):
            raise FoundryFailure(SafeFailure("design_tool_duplicate", "rejected"))

        scenarios = proposal.get("scenario")
        if (
            not isinstance(scenarios, list)
            or len(scenarios) != 1
            or not isinstance(scenarios[0], dict)
        ):
            raise FoundryFailure(SafeFailure("design_scenario_invalid", "rejected"))
        scenario = scenarios[0]
        if set(scenario) != {"tool", "arguments", "expected_result"}:
            raise FoundryFailure(SafeFailure("design_scenario_invalid", "rejected"))
        tool_name = _safe_text(scenario.get("tool"), "design_scenario_invalid", limit=60)
        selected = next((tool for tool in tools if tool.name == tool_name), None)
        if selected is None or not isinstance(scenario.get("arguments"), dict):
            raise FoundryFailure(SafeFailure("design_scenario_invalid", "rejected"))
        arguments = scenario["arguments"]
        if set(arguments) != set(selected.arguments):
            raise FoundryFailure(SafeFailure("design_scenario_arguments_invalid", "rejected"))
        expected_result = scenario.get("expected_result")
        if (
            not isinstance(expected_result, dict)
            or not expected_result
            or not all(type(field) is str for field in expected_result)
            or not set(expected_result).issubset(selected.result_fields)
            or any(
                type(value) not in (type(None), bool, int, float, str)
                or (type(value) is float and not math.isfinite(value))
                for value in expected_result.values()
            )
        ):
            raise FoundryFailure(SafeFailure("design_scenario_invalid", "rejected"))
        expected_result = dict(expected_result)
        invariants = _strings(
            proposal.get("invariants"),
            "design_invariants_invalid",
            limit=5,
            allow_empty=True,
            item_limit=500,
        )
        public_step = PublicStep(
            tool=tool_name, arguments=arguments, expected_result=expected_result
        )
        compiled = {
            "environment_name": name,
            "summary": summary,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "arguments": tool.arguments,
                    "result_fields": tool.result_fields,
                }
                for tool in tools
            ],
            "public_steps": [
                {
                    "tool": public_step.tool,
                    "arguments": public_step.arguments,
                    "expected_result": expected_result,
                }
            ],
            "invariants": invariants,
            "runtime_protocol": ["handshake", "reset", "invoke", "close"],
        }
        artifact = store.put_json("design", compiled)
        return DesignContract(
            environment_name=name,
            summary=summary,
            tools=tuple(tools),
            public_steps=(public_step,),
            invariants=invariants,
            artifact=artifact,
        )

    def _advice(
        self,
        *,
        work: str,
        skill_name: str,
        skill_body: str,
        design: DesignContract,
        field: str,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=f"foundry-{work}-") as temporary:
            workspace = Path(temporary)
            (workspace / ".foundry-design.json").write_bytes(
                _canonical(self._design_projection(design))
            )
            result = self.agent.invoke_json(
                work=work,
                skill_name=skill_name,
                skill_body=skill_body,
                workspace=workspace,
                instruction=f'Return exactly {{"{field}":["short advisory item"]}}.',
            )
        return {
            field: _strings(
                result.value.get(field), f"{work}_response_invalid", limit=8, item_limit=500
            ),
            "model": result.route_model,
        }

    def _build(
        self, design: DesignContract, candidate_root: Path, store: ArtifactStore
    ) -> tuple[CandidateManifest, tuple[ArtifactRef, ...]]:
        plan = self._advice(
            work="build_implementation_plan",
            skill_name="engineer-build-planning",
            skill_body=_PLAN_SKILL,
            design=design,
            field="steps",
        )
        plan_ref = store.put_json("build-plan", plan)
        challenge = self._advice(
            work="verifier_intent",
            skill_name="challenge-agent-world",
            skill_body=_CHALLENGE_SKILL,
            design=design,
            field="risks",
        )
        challenge_ref = store.put_json("verifier-intent", challenge)

        candidate_root.mkdir(parents=True, exist_ok=True)
        (candidate_root / ".foundry-design.json").write_bytes(
            _canonical(self._design_projection(design))
        )
        (candidate_root / ".foundry-plan.json").write_bytes(_canonical(plan))
        (candidate_root / ".foundry-challenge.json").write_bytes(_canonical(challenge))
        self.agent.invoke_json(
            work="candidate_build",
            skill_name="engineer-environment-codegen",
            skill_body=_CODEGEN_SKILL,
            workspace=candidate_root,
            instruction='Implement runtime.py now, then return {"status":"written"}.',
            writable=True,
            require_json=False,
        )
        manifest = self._scan_candidate(candidate_root, store)
        # These inputs are framework control files, never candidate source or package input.
        for control in candidate_root.glob(".foundry-*.json"):
            control.unlink()
        return manifest, (plan_ref, challenge_ref)

    @staticmethod
    def _design_projection(design: DesignContract) -> dict[str, Any]:
        return {
            "environment_name": design.environment_name,
            "summary": design.summary,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "arguments": tool.arguments,
                    "result_fields": tool.result_fields,
                }
                for tool in design.tools
            ],
            "public_step": {
                "tool": design.public_steps[0].tool,
                "arguments": design.public_steps[0].arguments,
                "expected_result": design.public_steps[0].expected_result,
            },
        }

    @staticmethod
    def _scan_candidate(candidate_root: Path, store: ArtifactStore) -> CandidateManifest:
        files: list[dict[str, Any]] = []
        for path in sorted(candidate_root.rglob("*")):
            if path.is_dir() or path.name.startswith(".foundry-"):
                continue
            if path.is_symlink():
                raise FoundryFailure(SafeFailure("candidate_source_symlink", "rejected"))
            if path.suffix != ".py":
                raise FoundryFailure(SafeFailure("candidate_source_non_python", "rejected"))
            body = path.read_bytes()
            relative = path.relative_to(candidate_root).as_posix()
            files.append(
                {
                    "path": relative,
                    "digest": f"sha256:{sha256(body).hexdigest()}",
                    "size": len(body),
                }
            )
        if not files:
            raise FoundryFailure(SafeFailure("candidate_source_empty", "rejected"))
        if len(files) > 8:
            raise FoundryFailure(SafeFailure("candidate_source_file_count_exceeded", "rejected"))
        if sum(item["size"] for item in files) > 100_000:
            raise FoundryFailure(SafeFailure("candidate_source_size_exceeded", "rejected"))
        if [item["path"] for item in files] != ["runtime.py"]:
            raise FoundryFailure(SafeFailure("candidate_entrypoint_invalid", "rejected"))
        source_digest = f"sha256:{sha256(_canonical(files)).hexdigest()}"
        artifact = store.put_json(
            "candidate-manifest",
            {"entrypoint": "runtime.py", "source_digest": source_digest, "files": files},
        )
        return CandidateManifest(
            entrypoint="runtime.py",
            source_digest=source_digest,
            files=tuple(files),
            artifact=artifact,
        )

    @staticmethod
    def _judge(
        candidate_root: Path,
        design: DesignContract,
        candidate: CandidateManifest,
        store: ArtifactStore,
    ) -> JudgeReport:
        gates: list[GateResult] = []
        for outcome in judge(candidate_root, design.public_steps[0]):
            evidence = store.put_json("judge-gate", outcome)
            gates.append(
                GateResult(
                    gate_id=outcome["gate_id"],
                    status=cast(GateStatus, outcome["status"]),
                    code=outcome["code"],
                    evidence=evidence,
                )
            )
        report_ref = store.put_json(
            "judge-report",
            {
                "candidate_digest": candidate.source_digest,
                "gates": [
                    {
                        "gate_id": gate.gate_id,
                        "status": gate.status,
                        "code": gate.code,
                        "evidence": _reference(gate.evidence) if gate.evidence else None,
                    }
                    for gate in gates
                ],
            },
        )
        return JudgeReport(
            candidate_digest=candidate.source_digest, gates=tuple(gates), artifact=report_ref
        )

    def _release(
        self,
        design: DesignContract,
        candidate: CandidateManifest,
        report: JudgeReport,
        candidate_root: Path,
        store: ArtifactStore,
    ) -> tuple[RegistryReceipt, tuple[ArtifactRef, ...]]:
        dossier = store.put_json(
            "release-dossier",
            {
                "candidate_digest": candidate.source_digest,
                "design_digest": design.artifact.digest,
                "judge_digest": report.artifact.digest,
                "required_gates": [gate.gate_id for gate in report.gates],
            },
        )
        package_id = f"direct-{design.environment_name}"
        manifest = {
            "package_id": package_id,
            "origin": "direct",
            "parent_package_refs": [],
            "entrypoint": candidate.entrypoint,
            "source_digest": candidate.source_digest,
            "files": list(candidate.files),
            "contract_digests": {
                "design": design.artifact.digest,
                "candidate": candidate.artifact.digest,
                "judge": report.artifact.digest,
                "release_dossier": dossier.digest,
            },
        }
        package_bytes = self._package_bytes(manifest, candidate_root, candidate)
        package_ref = store.put_bytes("package", package_bytes, media_type="application/zip")
        digest = f"sha256:{sha256(package_bytes).hexdigest()}"
        version = f"v-{digest.removeprefix('sha256:')[:16]}"
        receipt_value, receipt_digest = self._publish(
            package_id, version, digest, package_bytes, manifest
        )
        receipt_ref = store.put_json("registry-receipt", receipt_value)
        return (
            RegistryReceipt(
                package_id=package_id,
                version=version,
                package_digest=digest,
                receipt_digest=receipt_digest,
                artifact=receipt_ref,
            ),
            (dossier, package_ref),
        )

    @staticmethod
    def _package_bytes(
        manifest: dict[str, Any], candidate_root: Path, candidate: CandidateManifest
    ) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temporary:
            path = Path(temporary.name)
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                DirectFoundry._zip_entry(archive, "manifest.json", _canonical(manifest))
                for item in candidate.files:
                    DirectFoundry._zip_entry(
                        archive, item["path"], (candidate_root / item["path"]).read_bytes()
                    )
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _zip_entry(archive: zipfile.ZipFile, name: str, body: bytes) -> None:
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, body)

    def _publish(
        self,
        package_id: str,
        version: str,
        package_digest: str,
        package_bytes: bytes,
        manifest: dict[str, Any],
    ) -> tuple[dict[str, str], str]:
        package_hex = package_digest.removeprefix("sha256:")
        package_path = self.settings.state_root / "registry" / "packages" / f"{package_hex}.zip"
        if package_path.exists() and package_path.read_bytes() != package_bytes:
            raise FoundryFailure(SafeFailure("registry_version_conflict", "rejected"))
        if not package_path.exists():
            _atomic_write(package_path, package_bytes)
        self._verify_package(package_path, package_digest, manifest)
        receipt = {
            "status": "released",
            "package_id": package_id,
            "version": version,
            "package_digest": package_digest,
        }
        receipt_digest = f"sha256:{sha256(_canonical(receipt)).hexdigest()}"
        receipt_path = (
            self.settings.state_root
            / "registry"
            / "receipts"
            / f"{receipt_digest.removeprefix('sha256:')}.json"
        )
        if receipt_path.exists() and receipt_path.read_bytes() != _canonical(receipt):
            raise FoundryFailure(SafeFailure("registry_receipt_conflict", "rejected"))
        if not receipt_path.exists():
            _atomic_write(receipt_path, _canonical(receipt))
        verified = json.loads(receipt_path.read_text(encoding="utf-8"))
        if verified != receipt:
            raise FoundryFailure(SafeFailure("registry_receipt_invalid", "rejected"))
        return receipt, receipt_digest

    @staticmethod
    def _verify_package(path: Path, expected_digest: str, manifest: dict[str, Any]) -> None:
        body = path.read_bytes()
        if f"sha256:{sha256(body).hexdigest()}" != expected_digest:
            raise FoundryFailure(SafeFailure("registry_package_digest_invalid", "rejected"))
        with zipfile.ZipFile(path) as archive:
            try:
                stored = json.loads(archive.read("manifest.json"))
                runtime = archive.read("runtime.py")
            except (KeyError, json.JSONDecodeError) as exc:
                raise FoundryFailure(SafeFailure("registry_package_invalid", "rejected")) from exc
        if stored != manifest or not runtime:
            raise FoundryFailure(SafeFailure("registry_package_invalid", "rejected"))


def generate(need: str, config_path: Path | str) -> dict[str, Any]:
    """Public Direct API. It returns an honest terminal result, never a fake package."""

    return DirectFoundry(load_settings(config_path)).generate(need)


def check_config(config_path: Path | str) -> dict[str, str]:
    settings = load_settings(config_path)
    return {
        "status": "ok",
        "direct_primary": settings.direct_primary.model,
        "direct_fallback": settings.direct_fallback.model,
        "agent_primary": settings.agent_primary.model,
        "agent_fallback": settings.agent_fallback.model,
        "research": "configured",
    }
