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

Over-invalidation is safe only while it stays *semantic*.  The physical
invocation control plane (``agent_world.invocation.*``) decides how one attempt
is admitted, supervised, retried and settled — never what a correct answer is.
Binding it into an acceptance digest made every transport or liveness repair
invalidate already-committed semantic Artifacts, so no run could converge while
the control plane was under repair.  ``leaf_code_revision`` therefore rejects
those modules outright: an acceptance identity may not depend on them.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from pathlib import Path

from agent_world.contracts import canonical_json_bytes, sha256_digest

# The physical invocation control plane: adapters, worker lifecycle, liveness
# supervision, retry/fallback routing, ownership, recovery and audit.  None of
# it authors meaning, so none of it may enter an acceptance identity.
_CONTROL_PLANE_MODULE_PREFIX = "agent_world.invocation."


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
    assets: Mapping[str, Path] | None = None,
) -> str:
    """Return a stable acceptance-critical revision id for a leaf implementation.

    ``module_names`` are the dotted module paths whose source authors the leaf's
    behavior. ``assets`` optionally binds named, in-tree runtime assets such as
    a mounted Runtime Skill. ``model`` binds the Agent model identity when the
    leaf's output depends on it. The result is stable across processes for
    identical inputs and changes whenever a named module or asset changes.

    Physical invocation-control modules are rejected: an acceptance identity may
    depend on what a leaf asks for and what counts as correct, never on how one
    attempt was transported, supervised or retried.
    """

    if not module_names:
        raise ValueError("leaf_code_revision requires at least one module name")
    control_plane = sorted(
        name for name in set(module_names) if name.startswith(_CONTROL_PLANE_MODULE_PREFIX)
    )
    if control_plane:
        raise ValueError(
            "leaf_code_revision cannot bind physical invocation-control modules "
            f"into an acceptance identity: {', '.join(control_plane)}. "
            "A transport, liveness, retry or ownership change must not make an "
            "already-committed semantic Artifact stale; record it in the "
            "Invocation Control Store instead."
        )
    payload: dict[str, object] = {
        "protocol": "framework.leaf-code-revision.v1",
        "modules": {
            name: sha256_digest(_module_source_bytes(name)) for name in sorted(set(module_names))
        },
        "model": model,
    }
    if assets:
        resolved_assets: dict[str, str] = {}
        for name, asset_path in sorted(assets.items()):
            if not name:
                raise ValueError("leaf_code_revision asset name cannot be empty")
            candidate = Path(asset_path)
            if not candidate.is_file():
                raise ValueError(f"cannot locate runtime asset {name!r}")
            resolved_assets[name] = sha256_digest(candidate.read_bytes())
        payload["assets"] = resolved_assets
    digest = sha256_digest(canonical_json_bytes(payload))
    short = digest.split(":", 1)[-1][:16] if ":" in digest else digest[:16]
    return f"framework.{label}.{short}"
