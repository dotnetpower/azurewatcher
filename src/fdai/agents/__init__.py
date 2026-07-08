"""FDAI pantheon runtime.

The pantheon is a fixed upstream set of 15 named agents that own the
runtime control plane. This package exposes the agent contract, the
registry, and the topic naming convention. Behavior for individual
agents lands wave-by-wave (see
`docs/roadmap/agent-pantheon-implementation.md`); Wave 1 ships the
scaffolding only.

Design authority: `docs/roadmap/agent-pantheon.md`.
"""

from fdai.agents.base import Agent, AgentSpec, Layer
from fdai.agents.bus import PantheonBus
from fdai.agents.divergence import ShadowDivergenceLedger
from fdai.agents.factory import instantiate_pantheon
from fdai.agents.pantheon import (
    HARD_DEPENDENCY_AGENTS,
    LLM_HOT_PATH_ALLOWLIST,
    PANTHEON_NAMES,
    PANTHEON_SPECS,
)
from fdai.agents.registry import PantheonRegistry, load_pantheon
from fdai.agents.runtime import PantheonRuntime
from fdai.agents.topics import (
    OWNED_OBJECT_TOPICS,
    partition_key_for,
    topic_for_object_type,
)

__all__ = [
    "Agent",
    "AgentSpec",
    "Layer",
    "PantheonBus",
    "PantheonRegistry",
    "PantheonRuntime",
    "ShadowDivergenceLedger",
    "load_pantheon",
    "instantiate_pantheon",
    "PANTHEON_SPECS",
    "PANTHEON_NAMES",
    "HARD_DEPENDENCY_AGENTS",
    "LLM_HOT_PATH_ALLOWLIST",
    "OWNED_OBJECT_TOPICS",
    "topic_for_object_type",
    "partition_key_for",
]
