"""Risk scoring; auto vs HIL vs deny; enforces the four safety invariants.

Public exports (P2-D + P2-E):

- :class:`~aiopspilot.core.risk_gate.gate.RiskGate` — orchestrator.
- :class:`~aiopspilot.core.risk_gate.gate.RiskDecision` /
  :class:`~aiopspilot.core.risk_gate.gate.RiskDecisionOutcome` — data types.
- :class:`~aiopspilot.core.risk_gate.gate.RiskGateConfig` — thresholds.
- :class:`~aiopspilot.core.risk_gate.gate.ActionPromotionRegistry` /
  :class:`~aiopspilot.core.risk_gate.gate.ActionModeRecord` /
  :class:`~aiopspilot.core.risk_gate.gate.PromotionMetrics` — shadow→enforce
  promotion registry (per-ActionType mode + measured provenance).
"""

from aiopspilot.core.risk_gate.gate import (
    ActionModeRecord,
    ActionPromotionRegistry,
    PromotionMetrics,
    RiskDecision,
    RiskDecisionOutcome,
    RiskGate,
    RiskGateConfig,
    duration_since,
)
from aiopspilot.core.risk_gate.precedence import (
    CandidateAction,
    PrecedenceDecision,
    PrecedenceOutcome,
    PrecedenceResolver,
    Vertical,
)

__all__ = [
    "ActionModeRecord",
    "ActionPromotionRegistry",
    "CandidateAction",
    "PrecedenceDecision",
    "PrecedenceOutcome",
    "PrecedenceResolver",
    "PromotionMetrics",
    "RiskDecision",
    "RiskDecisionOutcome",
    "RiskGate",
    "RiskGateConfig",
    "Vertical",
    "duration_since",
]
