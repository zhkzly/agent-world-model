"""Environment Designer: evidence, world semantics, discovery, and expansion intent selection."""

from agent_world.control.repair import StructuredRepairAuthority, StructuredRepairDenied

from .budget import DesignerBudgetPlanError, derive_designer_invocation_budget
from .discovery import AdmissionBundle, DiscoveryBundle, DiscoveryService
from .expansion import (
    AskBudget,
    EnvironmentExpansionPolicy,
    EvolutionaryArchivePolicy,
    ExpansionContext,
    OperatorCatalog,
    ParentDescriptor,
    PolicyCheckpoint,
    RandomSearchPolicy,
    StopDecision,
    WideSearchPolicy,
)
from .expansion_service import (
    ExpansionDesignBundle,
    ExpansionDesigner,
    ResolvedExpansionClue,
    ResolvedExpansionParent,
)
from .expansion_source import (
    EvidenceBackedExpansionSource,
    ExpansionSource,
    ExpansionSourceBundle,
    ExpansionSourceEngine,
    ExpansionSourceRouter,
    project_capability_feedback_for_source,
)
from .service import (
    DIRECT_DESIGN_BASE_TURNS,
    DIRECT_DESIGN_EVIDENCE_BASE_TURNS,
    DIRECT_DESIGN_TAIL_BASE_TURNS,
    AgentProfileProvider,
    DesignBundle,
    DesignerError,
    EnvironmentDesigner,
)

__all__ = [
    "AskBudget",
    "AdmissionBundle",
    "AgentProfileProvider",
    "DesignBundle",
    "DIRECT_DESIGN_BASE_TURNS",
    "DIRECT_DESIGN_EVIDENCE_BASE_TURNS",
    "DIRECT_DESIGN_TAIL_BASE_TURNS",
    "DiscoveryBundle",
    "DiscoveryService",
    "DesignerError",
    "DesignerBudgetPlanError",
    "EnvironmentDesigner",
    "EnvironmentExpansionPolicy",
    "EvidenceBackedExpansionSource",
    "EvolutionaryArchivePolicy",
    "ExpansionContext",
    "ExpansionDesignBundle",
    "ExpansionDesigner",
    "ExpansionSource",
    "ExpansionSourceBundle",
    "ExpansionSourceEngine",
    "ExpansionSourceRouter",
    "OperatorCatalog",
    "ParentDescriptor",
    "PolicyCheckpoint",
    "RandomSearchPolicy",
    "ResolvedExpansionClue",
    "ResolvedExpansionParent",
    "StopDecision",
    "StructuredRepairAuthority",
    "StructuredRepairDenied",
    "WideSearchPolicy",
    "derive_designer_invocation_budget",
    "project_capability_feedback_for_source",
]
