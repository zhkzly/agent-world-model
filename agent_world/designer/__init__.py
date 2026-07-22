"""Environment Designer: evidence, world semantics, discovery, and expansion intent selection."""

from agent_world.control.repair import StructuredRepairAuthority, StructuredRepairDenied

from .budget import DesignerBudgetPlanError, derive_designer_invocation_budget
from .discovery import AdmissionBundle, DiscoveryBundle, DiscoveryService
from .evidence_synthesis_leaf import EvidenceSynthesisLeaf
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
from .one_shot import (
    StructuredProfileProvider,
    StructuredTurnResult,
    invoke_structured_once,
)
from .research_acquisition_leaf import ResearchAcquisitionLeaf
from .research_leaf import ResearchPlanLeaf
from .service import (
    DIRECT_DESIGN_BASE_TURNS,
    DIRECT_DESIGN_MAX_CORRECTIONS,
    DIRECT_DESIGN_MAX_TURNS,
    AgentProfileProvider,
    DesignBundle,
    DesignerError,
    EnvironmentDesigner,
)
from .world_architecture_leaf import WorldArchitectureLeaf

__all__ = [
    "AskBudget",
    "AdmissionBundle",
    "AgentProfileProvider",
    "DesignBundle",
    "DIRECT_DESIGN_BASE_TURNS",
    "DIRECT_DESIGN_MAX_CORRECTIONS",
    "DIRECT_DESIGN_MAX_TURNS",
    "DiscoveryBundle",
    "DiscoveryService",
    "DesignerError",
    "DesignerBudgetPlanError",
    "EnvironmentDesigner",
    "EvidenceSynthesisLeaf",
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
    "ResearchPlanLeaf",
    "ResearchAcquisitionLeaf",
    "ResolvedExpansionClue",
    "ResolvedExpansionParent",
    "StopDecision",
    "StructuredRepairAuthority",
    "StructuredProfileProvider",
    "StructuredTurnResult",
    "StructuredRepairDenied",
    "WideSearchPolicy",
    "WorldArchitectureLeaf",
    "derive_designer_invocation_budget",
    "project_capability_feedback_for_source",
    "invoke_structured_once",
]
