"""Durable ActionRun persistence tests for Thor + the composition seam."""

from __future__ import annotations

import asyncio

from fdai.agents.provider_adapters import StateStoreActionRunStore
from fdai.agents.runtime import PantheonRuntime
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_RAW_TOPIC = "fdai.events"


class _FakeActionRunStore:
    """Minimal in-memory ActionRunStore double."""

    def __init__(self) -> None:
        self.saved: dict[str, ActionRun] = {}
        self.deleted: list[str] = []

    async def save(self, run: ActionRun) -> None:
        self.saved[run.correlation_id] = run

    async def load_active(self) -> list[ActionRun]:
        return list(self.saved.values())

    async def delete(self, correlation_id: str) -> None:
        self.deleted.append(correlation_id)
        self.saved.pop(correlation_id, None)


def test_action_run_dict_round_trip() -> None:
    run = ActionRun(
        correlation_id="c",
        action_type="ops.restart-service",
        resource_id="r",
        state=ActionRunState.EXECUTING,
        verdict="auto",
        shadow_mode=True,
        outcome="x",
    )
    run.transition(ActionRunState.SUCCEEDED)
    back = ActionRun.from_dict(run.to_dict())
    assert back.correlation_id == run.correlation_id
    assert back.state == ActionRunState.SUCCEEDED
    assert back.history == run.history
    assert back.shadow_mode is True
    assert back.outcome == "x"


def test_thor_deletes_terminal_run_from_store() -> None:
    store = _FakeActionRunStore()
    thor = Thor(state_store=store, shadow_by_default=True)

    async def _dispatch() -> ActionRun:
        return await thor.dispatch_verdict(
            {
                "correlation_id": "c",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-1",
            }
        )

    run = asyncio.run(_dispatch())
    assert run.state == ActionRunState.SUCCEEDED  # shadow success is terminal
    assert "c" in store.deleted  # terminal run removed from the durable store


def test_thor_persists_in_flight_hil_run() -> None:
    store = _FakeActionRunStore()
    thor = Thor(state_store=store)

    async def _dispatch() -> ActionRun:
        return await thor.dispatch_verdict(
            {
                "correlation_id": "c2",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resource_id": "vm-2",
            }
        )

    run = asyncio.run(_dispatch())
    assert run.state == ActionRunState.HIL_PENDING
    assert "c2" in store.saved  # non-terminal run is persisted


def test_thor_rehydrate_restores_runs_and_locks() -> None:
    store = _FakeActionRunStore()
    pending = ActionRun(
        correlation_id="c3",
        action_type="remediate.enable-encryption",
        resource_id="vm-3",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
    )
    asyncio.run(store.save(pending))

    thor = Thor(state_store=store)
    restored = asyncio.run(thor.rehydrate())
    assert restored == 1
    assert "c3" in thor.action_runs
    assert "vm-3" in thor._resource_locks


def test_statestore_action_run_store_round_trip() -> None:
    store = StateStoreActionRunStore(store=InMemoryStateStore())
    run = ActionRun(
        correlation_id="c",
        action_type="ops.restart-service",
        resource_id="r",
        state=ActionRunState.EXECUTING,
        verdict="auto",
    )
    asyncio.run(store.save(run))
    active = asyncio.run(store.load_active())
    assert len(active) == 1
    assert active[0].correlation_id == "c"
    assert active[0].state == ActionRunState.EXECUTING

    asyncio.run(store.delete("c"))
    assert asyncio.run(store.load_active()) == []


def test_runtime_rehydrates_thor_on_run() -> None:
    store = _FakeActionRunStore()
    pending = ActionRun(
        correlation_id="c9",
        action_type="remediate.enable-encryption",
        resource_id="vm-9",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
    )
    asyncio.run(store.save(pending))

    provider = InMemoryEventBus()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        thor_state_store=store,
    )

    async def _drive() -> None:
        run_task = asyncio.create_task(runtime.run())
        for _ in range(20):
            await asyncio.sleep(0)
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())
    thor = runtime.agents["Thor"]
    assert isinstance(thor, Thor)
    assert "c9" in thor.action_runs
