"""Render the small Direct-only output addition for one structured LLM turn.

Direct is intentionally only model + rendered Prompt + native schema. It has
no Runtime Skill, workspace/tool instruction, session, or alternate
string-envelope protocol. This helper therefore adds only a caller-owned,
compact node protocol when one is genuinely needed.
"""

from __future__ import annotations


def render_direct_structured_prompt(
    prompt: str,
    *,
    logical_protocol: str | None = None,
) -> str:
    """Add node mechanics while the Provider enforces the native schema.

    Callers must use this only on the tool-free Direct route. Applying it to a
    Codex Agent would duplicate the Agent's mounted Skill and native SDK schema
    channel.
    """

    if logical_protocol is None:
        return prompt
    return f"""{prompt}

Compact output protocol:
The Provider enforces the requested JSON schema. The protocol below supplies
the complete node-specific output mechanics; it does not replace local Pydantic
or deterministic compiler validation.
{logical_protocol.strip()}
"""


__all__ = ["render_direct_structured_prompt"]
