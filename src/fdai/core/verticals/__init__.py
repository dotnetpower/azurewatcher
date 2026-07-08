"""Verticals - Resilience (DR/Chaos), Change Safety, Cost Governance.

Each vertical composes existing P1/P2 primitives (`T0Engine`, `RiskGate`,
`ShadowExecutor`, `ContinuousRulePipeline`) with vertical-specific
scheduling / guardrails. This package is the P3 integration surface.

New operational domains onboard through the `VerticalRegistry` seam
(`registry.py`) - a fork registers a `VerticalDescriptor` at the
composition root rather than editing `core/`.
"""

from fdai.core.verticals.registry import (
    VerticalDescriptor,
    VerticalRegistrationError,
    VerticalRegistry,
)

__all__ = [
    "VerticalDescriptor",
    "VerticalRegistrationError",
    "VerticalRegistry",
]
