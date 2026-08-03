"""Request, budget, release policy, and job contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import ArtifactRef, Identifier, NonEmptyStr, V2Contract


class Budget(V2Contract):
    """A vector budget; no dimension may be silently traded for another."""

    llm_tokens: Annotated[int, Field(ge=0)] = 0
    agent_turns: Annotated[int, Field(ge=0)] = 0
    search_calls: Annotated[int, Field(ge=0)] = 0
    tool_calls: Annotated[int, Field(ge=0)] = 0
    process_calls: Annotated[int, Field(ge=0)] = 0
    build_seconds: Annotated[float, Field(ge=0)] = 0
    evaluation_episodes: Annotated[int, Field(ge=0)] = 0
    container_seconds: Annotated[float, Field(ge=0)] = 0
    live_probe_cost: Annotated[float, Field(ge=0)] = 0
    repair_attempts: Annotated[int, Field(ge=0)] = 0
    wall_seconds: Annotated[float, Field(ge=0)] = 0
    monetary_cost: Annotated[float, Field(ge=0)] = 0


class BudgetUsage(Budget):
    """Observed consumption using the same dimensions as a reservation."""


class PermissionScope(V2Contract):
    filesystem_read_roots: tuple[NonEmptyStr, ...] = ()
    filesystem_write_roots: tuple[NonEmptyStr, ...] = ()
    network_domains: tuple[NonEmptyStr, ...] = ()
    executable_allowlist: tuple[NonEmptyStr, ...] = ()
    tool_allowlist: tuple[Identifier, ...] = ()
    credential_handles: tuple[Identifier, ...] = ()
    allow_external_side_effects: bool = False


class ReleaseProfile(V2Contract):
    profile_id: Identifier
    required_hard_gates: tuple[Identifier, ...] = (
        "schema",
        "supply_chain",
        "static_assurance",
        "runtime_protocol",
        "task_materialization",
        "task_reachability",
        "behavior",
        "sealed_release",
        "clean_deployment",
    )
    minimum_coverage_dimensions: tuple[Identifier, ...] = ()
    maximum_risk: Literal["low", "medium", "high", "critical"] = "medium"
    require_reproducible_reset: bool = True
    require_unknown_seed_testing: bool = True
    require_clean_install: bool = True
    require_package_relative_paths: bool = True
    allow_unresolved_assumptions: bool = False

    @property
    def effective_required_hard_gates(self) -> tuple[Identifier, ...]:
        """Return framework-authoritative gates without rewriting frozen data.

        Older durable profiles may still name Candidate-authored public
        self-checks as hard gates.  They remain readable provenance, but they
        cannot grant a generated test authority to block or authorize a
        release.  Keeping this as a view rather than a model normalisation is
        important: normalising on deserialisation would change the bytes of a
        historical ``GenerationContext`` and break its exact artifact closure.
        """

        return tuple(
            gate_id
            for gate_id in self.required_hard_gates
            if gate_id != "public_self_check"
        )


class EnvironmentRequest(V2Contract):
    request_id: Identifier
    need: NonEmptyStr
    supplied_asset_refs: tuple[ArtifactRef, ...] = ()
    allowed_source_kinds: tuple[Identifier, ...] = ("web",)
    fidelity_requirements: tuple[NonEmptyStr, ...] = ()
    permissions: PermissionScope = Field(default_factory=PermissionScope)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    unknowns_requiring_human: tuple[NonEmptyStr, ...] = ()
    budget: Budget = Field(default_factory=Budget)
    release_profile: ReleaseProfile

    @model_validator(mode="after")
    def implemented_research_sources_only(self) -> EnvironmentRequest:
        if self.allowed_source_kinds != ("web",):
            raise ValueError(
                "the production research adapter currently implements exactly the web source "
                "kind; tool surfaces such as MCP/CLI/API/SDK are discovered from fetched Web "
                "evidence, not advertised as unimplemented source transports"
            )
        return self


class EnvironmentJob(V2Contract):
    job_id: Identifier
    kind: Literal["generate", "expand"]
    request_ref: ArtifactRef | None = None
    anchor_package_refs: tuple[ArtifactRef, ...] = ()
    expansion_campaign_ref: ArtifactRef | None = None
    permissions: PermissionScope = Field(default_factory=PermissionScope)
    budget: Budget = Field(default_factory=Budget)
    release_profile: ReleaseProfile

    @model_validator(mode="after")
    def validate_job_inputs(self) -> EnvironmentJob:
        if self.kind == "generate":
            if self.request_ref is None:
                raise ValueError("generate jobs require request_ref")
            if self.anchor_package_refs or self.expansion_campaign_ref is not None:
                raise ValueError("generate jobs cannot carry expansion anchors or campaign")
        else:
            if self.expansion_campaign_ref is None:
                raise ValueError("expand jobs require expansion_campaign_ref")
            if not self.anchor_package_refs:
                raise ValueError("expand jobs require at least one anchor package")
        return self


class GenerationContext(V2Contract):
    """The immutable common root for one Direct or Evolve generation graph.

    A context is written by framework code before the first real Agent/tool
    execution.  It removes the former implicit coupling where Research read a
    request from Controller state while later nodes consumed only selected
    artifacts.  Every WorkGraph root now has one auditable request/job,
    permission, budget and seed closure.
    """

    context_id: Identifier
    job_ref: ArtifactRef
    kind: Literal["generate", "expand"]
    request_ref: ArtifactRef | None = None
    anchor_package_refs: tuple[ArtifactRef, ...] = ()
    expansion_campaign_ref: ArtifactRef | None = None
    admitted_clue_refs: tuple[ArtifactRef, ...] = ()
    permissions: PermissionScope
    budget: Budget
    release_profile: ReleaseProfile
    target_identity_policy: Identifier = "identity:environment-package.v3"

    @model_validator(mode="after")
    def validate_context(self) -> GenerationContext:
        if self.job_ref.artifact_type != "control.environment_job":
            raise ValueError("GenerationContext job_ref must be an EnvironmentJob Artifact")
        if self.request_ref is not None and (
            self.request_ref.artifact_type != "control.environment_request"
        ):
            raise ValueError("GenerationContext request_ref has the wrong artifact type")
        if self.expansion_campaign_ref is not None and (
            self.expansion_campaign_ref.artifact_type != "control.expansion_campaign"
        ):
            raise ValueError("GenerationContext expansion campaign has the wrong artifact type")
        if any(ref.artifact_type != "release.record" for ref in self.anchor_package_refs):
            raise ValueError("GenerationContext anchors must be released Registry records")
        roots = (
            self.job_ref,
            *((self.request_ref,) if self.request_ref is not None else ()),
            *self.anchor_package_refs,
            *((self.expansion_campaign_ref,) if self.expansion_campaign_ref is not None else ()),
            *self.admitted_clue_refs,
        )
        if len(set(roots)) != len(roots):
            raise ValueError("GenerationContext root refs must be unique")
        if self.kind == "generate":
            if (
                self.request_ref is None
                or self.anchor_package_refs
                or self.expansion_campaign_ref is not None
            ):
                raise ValueError("generate GenerationContext requires only an EnvironmentRequest")
        elif (
            self.request_ref is not None
            or not self.anchor_package_refs
            or self.expansion_campaign_ref is None
        ):
            raise ValueError("expand GenerationContext requires campaign and released anchors")
        return self

    @property
    def root_refs(self) -> tuple[ArtifactRef, ...]:
        return (
            self.job_ref,
            *((self.request_ref,) if self.request_ref is not None else ()),
            *self.anchor_package_refs,
            *((self.expansion_campaign_ref,) if self.expansion_campaign_ref else ()),
            *self.admitted_clue_refs,
        )


__all__ = [
    "Budget",
    "BudgetUsage",
    "EnvironmentJob",
    "GenerationContext",
    "EnvironmentRequest",
    "PermissionScope",
    "ReleaseProfile",
]
