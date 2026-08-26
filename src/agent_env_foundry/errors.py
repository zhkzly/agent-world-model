"""Environment contract error vocabulary (S1 Slice 1).

Ownership split:

- ``EnvironmentContractError``: a deterministic contract violation detected at
  a boundary before domain execution — an invalid reset ``start`` supplied by
  the caller, or a malformed release descriptor/payload manifest/factory
  reference in the artifact being loaded. Repair feedback can point at the
  exact contract clause.
- ``EnvironmentRuntimeError``: the environment side failed while executing —
  domain exceptions/crashes/timeouts, a reset result outside its published
  schema, success data outside the tool output schema, a malformed
  ``ToolObservation`` variant, or domain code squatting the reserved
  ``contract.*`` namespace. Neither error kind ever becomes a fictional
  ``ToolObservation``.
"""

from __future__ import annotations


class EnvironmentContractError(Exception):
    """Caller input or release artifact violated the documented contract."""


class EnvironmentRuntimeError(Exception):
    """The environment failed, crashed, or returned a corrupt result."""
