"""Framework-owned API-key provider constants for the Codex SDK adapter.

The provider definition itself is constructed only in the private worker's
per-thread SDK request config.  This module intentionally contains names and
the provider identifier only; it never receives credential or routing values.
"""

from __future__ import annotations

API_KEY_RUNTIME_PROVIDER = "agent_world_api_key"
OPENAI_API_KEY_ENVIRONMENT = "OPENAI_API_KEY"
OPENAI_BASE_URL_ENVIRONMENT = "OPENAI_BASE_URL"

__all__ = (
    "API_KEY_RUNTIME_PROVIDER",
    "OPENAI_API_KEY_ENVIRONMENT",
    "OPENAI_BASE_URL_ENVIRONMENT",
)
