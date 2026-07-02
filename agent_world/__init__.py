"""Agent-World-like request-driven environment generation runtime."""

from agent_world.agents import InvocationBackendRegistry, InvocationRequest, InvocationResult, default_invocation_backend_registry, invoke_backend
from agent_world.envpack import assemble_environment_pack, load_environment_pack, run_environment_pack_check, run_portable_envpkg_check
from agent_world.generated_project import GeneratedProjectPackageResult, run_packaged_generated_project_check
from agent_world.pipeline import PipelineRunConfig, PipelineRunRecord, PipelineRunner, request_driven_node_registry, run_request_driven_pipeline

__all__ = [
    "InvocationBackendRegistry",
    "InvocationRequest",
    "InvocationResult",
    "GeneratedProjectPackageResult",
    "PipelineRunConfig",
    "PipelineRunRecord",
    "PipelineRunner",
    "default_invocation_backend_registry",
    "assemble_environment_pack",
    "invoke_backend",
    "load_environment_pack",
    "request_driven_node_registry",
    "run_environment_pack_check",
    "run_packaged_generated_project_check",
    "run_portable_envpkg_check",
    "run_request_driven_pipeline",
]
