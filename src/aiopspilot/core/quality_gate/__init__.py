"""Mixed-model cross-check, deterministic verifier, and RAG grounding. Guards T2 output.

Public exports (P2-B):

- :class:`~aiopspilot.core.quality_gate.gate.QualityGate` — orchestrator.
- :class:`~aiopspilot.core.quality_gate.gate.QualityCandidate` /
  :class:`~aiopspilot.core.quality_gate.gate.QualityDecision` /
  :class:`~aiopspilot.core.quality_gate.gate.QualityOutcome` — data types.
- :class:`~aiopspilot.core.quality_gate.gate.QualityGateConfig` — thresholds.
- :class:`~aiopspilot.core.quality_gate.gate.CrossCheckModel` /
  :class:`~aiopspilot.core.quality_gate.gate.VerifierPolicy` /
  :class:`~aiopspilot.core.quality_gate.gate.GroundingSource` — DI seams.
"""

from aiopspilot.core.quality_gate.gate import (
    CrossCheckModel,
    GroundingSource,
    QualityCandidate,
    QualityDecision,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
    VerifierPolicy,
)

__all__ = [
    "CrossCheckModel",
    "GroundingSource",
    "QualityCandidate",
    "QualityDecision",
    "QualityGate",
    "QualityGateConfig",
    "QualityOutcome",
    "VerifierPolicy",
]
