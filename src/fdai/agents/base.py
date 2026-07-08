"""Agent contract and base class.

The `Agent` class is the runtime shell; per-agent behavior lives in
subclasses under this package (added in Waves 2 through 5). `AgentSpec`
is the immutable declaration read by the registry - see
`docs/roadmap/agent-pantheon.md` \u00a75.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.agents.bus import PantheonBus


class Layer(StrEnum):
    """Pantheon layers - see `agent-pantheon.md` \u00a74.

    - ``DOMAIN``: specialists (Njord / Freyr / Loki).
    - ``PIPELINE``: sensing / judgment / operations / interface.
    - ``GOVERNANCE``: staff (Odin / Mimir / Muninn / Saga / Norns).
    """

    DOMAIN = "domain"
    PIPELINE = "pipeline"
    GOVERNANCE = "governance"


@dataclass(frozen=True, slots=True)
class RateLimits:
    """Per-agent proposal caps (`agent-pantheon.md` \u00a78 default 20 / 100)."""

    per_minute: int = 20
    per_hour: int = 100


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Immutable declaration of one pantheon agent.

    The registry rejects any spec whose ``owns`` overlaps with another
    agent's ``owns`` (single-writer invariant, see
    ``docs/roadmap/agent-pantheon.md`` \u00a76.1).
    """

    name: str
    layer: Layer
    reports_to: str | None
    owns: tuple[str, ...]
    """ObjectType names this agent is the single writer of."""
    executes: tuple[str, ...] = ()
    """ActionType names this agent may execute as the sole mutation principal."""
    initiates: tuple[str, ...] = ()
    """ActionType names this agent may propose (initiator role)."""
    subscribes: tuple[str, ...] = ()
    publishes: tuple[str, ...] = ()
    question_domains: tuple[str, ...] = ()
    owns_code_paths: tuple[str, ...] = ()
    hot_path_llm: bool = False
    """True only for Bragi (translator) and Forseti (T2 abstain)."""
    off_path_llm: bool = False
    """True only for Norns (batch discovery)."""
    rate_limits: RateLimits = field(default_factory=RateLimits)
    hard_dependency: bool = False
    """Saga and Vidar only: without them, mutation is refused / demoted."""

    def __post_init__(self) -> None:
        # publishes MUST equal the topic form of owns (single-writer
        # invariant). We derive this at spec-build time so the registry
        # never has to reconcile two lists.
        object.__setattr__(
            self,
            "publishes",
            tuple(f"object.{_kebab(o)}" for o in self.owns),
        )


class Agent:
    """Runtime base class for a pantheon agent.

    Subclasses live under `src/fdai/agents/` (one file per canonical name,
    added wave-by-wave). Wave 1 ships stub subclasses that implement no
    behavior beyond registering their `AgentSpec`.
    """

    spec: AgentSpec

    #: Typed pub/sub port. Publishing agents bind a concrete
    #: :class:`~fdai.agents.bus.PantheonBus` (``InMemoryBus`` in tests,
    #: ``EventBusBridge`` in production) via :meth:`bind_bus`; agents that
    #: never publish leave it ``None``. Declared on the base so the
    #: composition root (:class:`~fdai.agents.runtime.PantheonRuntime`)
    #: can bind every agent uniformly without duck-typing.
    bus: PantheonBus | None = None

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec

    def bind_bus(self, bus: PantheonBus) -> None:
        """Bind the typed pub/sub port.

        Publishing subclasses may override to keep a narrower type, but
        the base implementation is sufficient: it stores the bus so
        :meth:`Agent.on_typed_message` handlers can publish. Idempotent -
        re-binding replaces the bus.
        """
        self.bus = bus

    # --- typed port (hot-path pub/sub) ---------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle a message from a typed topic this agent subscribes to.

        Wave 1 stubs default to a no-op. Behavior lands in later waves.
        """
        return None

    # --- conversational port (LLM-backed NL Q&A) -----------------------

    async def on_conversation_turn(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        """Answer a natural-language query directed at this agent.

        Every agent MUST implement this in a later wave. Wave 1 stubs
        return a "not-yet-implemented" abstain payload so Bragi can log
        the handoff.
        """
        return {
            "primary_agent": self.spec.name,
            "answer": None,
            "abstain_reason": "not_yet_implemented",
        }

    # --- lifecycle & health --------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return the health snapshot Heimdall probes (Wave 3+)."""
        return {"agent": self.spec.name, "status": "stub"}


def _kebab(name: str) -> str:
    """Camel or PascalCase ObjectType name -> kebab topic form.

    Examples:
        ``Event`` -> ``event``
        ``ActionRun`` -> ``action-run``
        ``SecurityEvent`` -> ``security-event``
    """
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i and not name[i - 1].isupper():
            out.append("-")
        out.append(ch.lower())
    return "".join(out)


__all__ = ["Agent", "AgentSpec", "Layer", "RateLimits"]
