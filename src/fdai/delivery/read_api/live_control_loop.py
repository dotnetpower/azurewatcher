"""Dev-only :class:`LiveEmitter` that pumps synthetic events through a
real :class:`~fdai.core.control_loop.ControlLoop`.

Where :class:`~fdai.delivery.read_api.live_stream.SyntheticLiveEmitter`
publishes hand-crafted ``StageEvent`` frames straight into an
:class:`~fdai.shared.providers.sse.SseSink`, this emitter runs an
actual :class:`ControlLoop` in-process with the shipped rule catalog,
attached to a :class:`SseSinkStagePublisher` on the same sink. Every
frame the local console renders is produced by the pipeline that would
run in production - the trust router, T0 engine, action builder, and
shadow executor really evaluate the event.

This is **dev only**. Production wires a Kafka-backed
:class:`~fdai.core.control_loop.ControlLoop` (see ``__main__.py``); the
read-API pod there does NOT run the pipeline, it subscribes to the
``aw.pipeline.stages`` Kafka topic via
:class:`~fdai.shared.streaming.broadcaster.SseBroadcaster` and fans out
to browsers. Both paths land on the same wire (SSE ``event: stage``
frames), so the FE code does not change between them.

Failure modes
-------------

- **Missing OPA binary** - T0 evaluates every candidate to "abstain"
  (same fallback as :mod:`fdai.__main__`), and only ingest / route /
  audit stages fire. The FE still receives a live cockpit, just without
  gate / execute frames.
- **Rule catalog load error** - :meth:`start` raises
  :class:`ControlLoopEmitterUnavailable`; the app factory catches and
  falls back to :class:`SyntheticLiveEmitter` so the console is still
  populated.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fdai.core.control_loop import ControlLoop
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.tiers.t0_deterministic import (
    MissingOpaBinaryError,
    OpaRegoEvaluator,
    RuleIndex,
    T0Engine,
)
from fdai.core.trust_router import TrustRouter
from fdai.delivery.read_api.live_stream import LiveEmitter
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.sse import SseSink
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)
from fdai.shared.streaming.stage_publisher import SseSinkStagePublisher

_LOGGER = logging.getLogger(__name__)


class ControlLoopEmitterUnavailableError(RuntimeError):
    """Raised when the dev ControlLoop cannot be composed.

    The caller (``_local.py``) SHOULD catch this and fall back to a
    simpler emitter so the console still renders something.
    """


# Backward-compat alias for the shorter name used in earlier drafts / docs.
ControlLoopEmitterUnavailable = ControlLoopEmitterUnavailableError


@dataclass
class ControlLoopLiveEmitter(LiveEmitter):
    """Pump synthetic events through a real ControlLoop.

    The emitter's task is one loop that:

    1. Picks the next event from :attr:`event_source` (cycling).
    2. Rewrites its ``idempotency_key`` so ``event_ingest`` does not
       deduplicate the cycle.
    3. Calls :meth:`ControlLoop.process(event)`. The loop's injected
       :class:`SseSinkStagePublisher` publishes stage frames onto the
       sink; the SSE route wakes up and streams them to browsers.
    4. Sleeps to keep the rate near :attr:`events_per_second`.
    """

    sink: SseSink
    channel: str = "aw.pipeline.stages"
    events_per_second: float = 10.0
    repo_root: Path | None = None
    """Repository root. When ``None`` we infer from ``fdai.__file__``."""

    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    _loop: ControlLoop | None = field(default=None, init=False, repr=False)
    _events: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.events_per_second <= 0:
            raise ValueError("events_per_second MUST be positive")
        if not self.channel:
            raise ValueError("channel MUST be non-empty")

    async def start(self) -> None:
        if self._running:
            return
        self._loop = self._build_control_loop()
        self._events = self._load_events()
        if not self._events:
            raise ControlLoopEmitterUnavailable(
                "no scenario events found for the dev pump - "
                "check tests/scenarios/v2026.07/ ships with the repo"
            )
        self._running = True
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run(), name="fdai.live.control-loop-emitter")

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                _LOGGER.debug("live_control_loop_emitter_stop_exception", exc_info=True)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _resolve_repo_root(self) -> Path:
        if self.repo_root is not None:
            return self.repo_root
        # ``src/fdai/delivery/read_api/live_control_loop.py`` -> repo root
        return Path(__file__).resolve().parents[4]

    def _build_control_loop(self) -> ControlLoop:
        repo_root = self._resolve_repo_root()
        catalog_root = repo_root / "rule-catalog" / "catalog"
        action_types_root = repo_root / "rule-catalog" / "action-types"
        policies_root = repo_root / "policies"
        remediation_root = repo_root / "rule-catalog" / "remediation"
        vocabulary_file = repo_root / "rule-catalog" / "vocabulary" / "resource-types.yaml"
        for path in (
            catalog_root,
            action_types_root,
            policies_root,
            remediation_root,
            vocabulary_file,
        ):
            if not path.exists():
                raise ControlLoopEmitterUnavailable(f"missing catalog path: {path}")

        try:
            registry = PackageResourceSchemaRegistry()
            action_types = load_action_type_catalog(action_types_root, schema_registry=registry)
            with vocabulary_file.open("r", encoding="utf-8") as fh:
                resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
            rules = load_rule_catalog(
                catalog_root,
                schema_registry=registry,
                action_types=action_types,
                resource_types=resource_types,
                policies_root=policies_root,
                remediation_root=remediation_root,
            )
        except Exception as exc:  # noqa: BLE001 - propagate as unavailable
            raise ControlLoopEmitterUnavailable(f"rule catalog load failed: {exc}") from exc

        try:
            evaluator: Any = OpaRegoEvaluator(policies_root=policies_root)
        except MissingOpaBinaryError:
            _LOGGER.warning("live_control_loop_emitter_no_opa_fallback_to_abstain")
            evaluator = None

        index = RuleIndex.build(rules)
        audit_store = InMemoryStateStore()
        executor = ShadowExecutor(
            publisher=RecordingRemediationPrPublisher(),
            audit_store=audit_store,
            renderer=TemplateRenderer(remediation_root=remediation_root),
            resource_lock=ResourceLockManager(),
        )
        action_types_by_name = {a.name: a for a in action_types}
        validator = JsonSchemaEventValidator(
            JsonSchemaContractValidator(PackageResourceSchemaRegistry())
        )
        stage_publisher = SseSinkStagePublisher(self.sink, channel=self.channel)
        return ControlLoop(
            event_ingest=EventIngest(validator=validator),
            trust_router=TrustRouter(index=index),
            t0_engine=T0Engine(index=index, evaluator=evaluator),
            action_builder=ActionBuilder(action_types_by_name=action_types_by_name),
            executor=executor,
            audit_store=audit_store,
            rules_by_id={r.id: r for r in rules},
            action_types_by_name=action_types_by_name,
            stage_publisher=stage_publisher,
        )

    def _load_events(self) -> list[dict[str, Any]]:
        """Load the shipped v2026.07 scenario events as the dev event source.

        Each scenario file has an ``event`` field with the frozen event
        payload. Some scenarios also carry an ``enrichment_payload_resource``
        override, but for the dev pump we use the raw event which is enough
        to exercise T0 routing.
        """
        repo_root = self._resolve_repo_root()
        scenario_dir = repo_root / "tests" / "scenarios" / "v2026.07"
        enrichment_dir = repo_root / "tests" / "scenarios" / "enrichment" / "v2026.07"
        events: list[dict[str, Any]] = []
        for path in sorted(scenario_dir.glob("*.json")):
            try:
                scenario = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            event = scenario.get("event")
            if not isinstance(event, dict):
                continue
            merged = dict(event)
            # Fold in the enrichment overlay when present so T0 gets the
            # resource payload it needs to match rules.
            enrichment_path = enrichment_dir / path.name
            if enrichment_path.exists():
                try:
                    overlay = json.loads(enrichment_path.read_text(encoding="utf-8"))
                    resource = overlay.get("event_payload_resource")
                    if isinstance(resource, dict):
                        payload = dict(merged.get("payload") or {})
                        payload["resource"] = resource
                        merged["payload"] = payload
                except (OSError, ValueError):
                    pass
            events.append(merged)
        return events

    async def _run(self) -> None:
        if self._loop is None:  # defensive; start() populates this before create_task
            return
        loop = self._loop
        interval = 1.0 / self.events_per_second
        try:
            while self._running:
                base = self._events[self._counter % len(self._events)]
                self._counter += 1
                event = dict(base)
                # Rewrite the idempotency key so EventIngest does not
                # dedupe our cycle.
                event["idempotency_key"] = f"live-{self._counter:012d}"
                event["ingested_at"] = datetime.now(UTC).isoformat()
                try:
                    await loop.process(event)
                except Exception:  # noqa: BLE001 - dev pump keeps going
                    _LOGGER.debug("live_control_loop_process_error", exc_info=True)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass


def build_control_loop_emitter(
    sink: SseSink,
    channel: str,
    *,
    events_per_second: float = 10.0,
    repo_root: Path | None = None,
) -> ControlLoopLiveEmitter:
    """Factory suitable for ``LiveStreamConfig.emitter_factory``.

    ``build_app`` invokes the ``emitter_factory`` with ``(sink,
    channel)`` and expects a :class:`LiveEmitter`. This helper adds the
    other ControlLoop-specific parameters using defaults.
    """
    return ControlLoopLiveEmitter(
        sink=sink,
        channel=channel,
        events_per_second=events_per_second,
        repo_root=repo_root,
    )


__all__ = [
    "ControlLoopEmitterUnavailable",
    "ControlLoopEmitterUnavailableError",
    "ControlLoopLiveEmitter",
    "build_control_loop_emitter",
]
