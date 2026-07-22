"""Derive an acceptance-critical revision id from in-tree leaf source code.

A successful ``WorkCommit`` may be reused across process runs and across scopes
(sibling evolution candidates) only when the code that would produce it is
unchanged.  The framework already binds ``validator_revision_id`` into
``acceptance_digest``; historically that id was a hand-bumped constant, so a
developer editing a leaf's implementation without bumping the constant could
silently reuse a stale output — a lie the RL training environment must never
tell.  This module replaces the hand-bumped constant with an id derived from
the actual source of the modules that implement a leaf, plus (for Agent
proposals) the model identity.

The digest is deliberately *coarse per layer*: one id covers the whole set of
modules passed in.  Editing any one of them invalidates every cache keyed on
that id.  This over-invalidates (a safe direction — it re-runs work that would
have produced an identical result) but can never under-invalidate (reuse a
result the current code would not produce).  Granularity can be tightened to
per-leaf later without changing the acceptance contract.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from agent_world.contracts import canonical_json_bytes, sha256_digest


def _module_source_bytes(module_name: str) -> bytes:
    """Read the on-disk source of an importable module without importing it.

    Uses the import machinery to locate the file so a renamed or moved module
    is a hard error rather than a silent empty digest.
    """

    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None or spec.origin == "built-in":
        raise ValueError(f"cannot locate source for module {module_name!r}")
    return Path(spec.origin).read_bytes()


def leaf_code_revision(
    *module_names: str,
    model: str | None = None,
    label: str = "impl",
) -> str:
    """Return a stable acceptance-critical revision id for a leaf implementation.

    ``module_names`` are the dotted module paths whose source authors the leaf's
    behavior.  ``model`` binds the Agent model identity when the leaf's output
    depends on it.  The result is stable across processes for identical source
    and model, and changes whenever any named module's source changes.
    """

    if not module_names:
        raise ValueError("leaf_code_revision requires at least one module name")
    payload = {
        "protocol": "framework.leaf-code-revision.v1",
        "modules": {
            name: sha256_digest(_module_source_bytes(name))
            for name in sorted(set(module_names))
        },
        "model": model,
    }
    digest = sha256_digest(canonical_json_bytes(payload))
    short = digest.split(":", 1)[-1][:16] if ":" in digest else digest[:16]
    return f"framework.{label}.{short}"
