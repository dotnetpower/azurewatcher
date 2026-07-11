"""Vertical Protocol - shared shape for every domain vertical (G-6).

Each vertical (resilience, change_safety, cost_governance) composes P1/P2
primitives (`T0Engine`, `RiskGate`, `ShadowExecutor`,
`ContinuousRulePipeline`) with vertical-specific scheduling / guardrails
into a single named orchestrator. This Protocol is what the composition
root binds against; per-vertical modules provide the concrete
implementation.

Kept intentionally small - the whole point of the vertical layer is to
give each domain freedom in *how* it composes primitives, so the shared
contract is only the identity + wiring surface, not the orchestration
mechanics themselves.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Vertical(Protocol):
    """The shared shape of an FDAI vertical.

    Implementations MUST expose:

    - :attr:`name` - the vertical identifier (kebab-case, matches the
      subpackage directory name and the entry in
      :file:`../../../../rule-catalog/profiles/`).
    - :attr:`description` - one-line human-readable summary used in the
      capability catalog and operator console.

    Additional methods (schedulers, guards, orchestrators) live on the
    concrete class and are looked up by the composition root through the
    registry. Keeping them off the Protocol lets each vertical evolve its
    own shape without forcing every vertical to conform to a single
    orchestration signature.
    """

    name: str
    description: str


__all__ = ["Vertical"]
