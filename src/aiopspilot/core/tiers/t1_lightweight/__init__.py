"""Embedding similarity, learned-action reuse, small-model classification of routine cases.

Public exports (P2-C):

- :class:`~aiopspilot.core.tiers.t1_lightweight.tier.T1Tier` - orchestrator.
- :class:`~aiopspilot.core.tiers.t1_lightweight.tier.T1Config` /
  :class:`~aiopspilot.core.tiers.t1_lightweight.tier.T1Decision` /
  :class:`~aiopspilot.core.tiers.t1_lightweight.tier.T1Outcome` - data types.
- :class:`~aiopspilot.core.tiers.t1_lightweight.tier.LearnedAction` /
  :class:`~aiopspilot.core.tiers.t1_lightweight.tier.SimilarityMatch` - records.
- :class:`~aiopspilot.core.tiers.t1_lightweight.tier.EmbeddingModel` /
  :class:`~aiopspilot.core.tiers.t1_lightweight.tier.PatternLibrary` - DI seams.
"""

from aiopspilot.core.tiers.t1_lightweight.tier import (
    EmbeddingModel,
    LearnedAction,
    PatternLibrary,
    SimilarityMatch,
    T1Config,
    T1Decision,
    T1Outcome,
    T1Tier,
    cosine_similarity,
)

__all__ = [
    "EmbeddingModel",
    "LearnedAction",
    "PatternLibrary",
    "SimilarityMatch",
    "T1Config",
    "T1Decision",
    "T1Outcome",
    "T1Tier",
    "cosine_similarity",
]
