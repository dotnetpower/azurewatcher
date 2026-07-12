"""Tests for the console action-submit path (``POST /chat/action``).

Covers the submitter logic (RBAC capability gate, verb -> ActionType mapping,
proposal shape published to the raw event topic) and the route wiring (200
submitted / 403 capability / 400 bad body). The proposal that lands on the bus
is exactly what the pantheon's Huginn ingests, so the judge/approve/execute
pipeline (tested in tests/agents/test_chat_to_pipeline_e2e.py) takes over from
there.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.console_request import PriorRequestOutcome
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.console_action import (
    ConsoleActionSubmitter,
    make_console_action_route,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_TOPIC = "fdai.events"


def _submitter() -> tuple[ConsoleActionSubmitter, InMemoryEventBus]:
    bus = InMemoryEventBus()
    return ConsoleActionSubmitter(event_bus=bus, raw_event_topic=_TOPIC), bus


async def _drain(bus: InMemoryEventBus, topic: str) -> list[Any]:
    out: list[Any] = []
    async for env in bus.subscribe(topic, "test-group"):
        out.append(env)
    return out


def _principal(oid: str, role: Role) -> Principal:
    return Principal(oid=oid, roles=frozenset({role}))


# ---------------------------------------------------------------------------
# Submitter logic
# ---------------------------------------------------------------------------


def test_reader_is_refused_and_nothing_is_published() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u-reader", Role.READER))
    )
    assert res["submitted"] is False
    assert res["reason"] == "rbac_capability"
    assert res["required_capability"] == "author-draft-pr"
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_contributor_submits_and_publishes_the_proposal() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(
            question="restart svc-1 now",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
            session_id="s1",
        )
    )
    assert res["submitted"] is True
    assert res["action_type"] == "ops.restart-service"
    corr = res["correlation_id"]

    envs = asyncio.run(_drain(bus, _TOPIC))
    assert len(envs) == 1
    payload = envs[0].payload
    assert payload["initiator_principal"] == "u-contrib"
    assert payload["operator_initiated"] is True
    assert payload["action_type"] == "ops.restart-service"
    assert payload["event_type"] == "operator_request"
    assert payload["correlation_id"] == corr
    assert payload["idempotency_key"] == corr
    # Keyed by the resource so per-resource ordering holds.
    assert envs[0].key == "svc-1"


def test_owner_may_submit() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(question="failover prod-1", principal=_principal("u-owner", Role.OWNER))
    )
    assert res["submitted"] is True
    assert res["action_type"] == "ops.failover-primary"


def test_unmapped_command_abstains_without_publishing() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(
            question="provision a new cluster",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
        )
    )
    assert res["submitted"] is False
    assert res["reason"] == "unmapped_action_intent"
    assert asyncio.run(_drain(bus, _TOPIC)) == []


# ---------------------------------------------------------------------------
# Scenario B - deny-override block on re-request
# ---------------------------------------------------------------------------


def _submitter_with_prior(
    outcome: PriorRequestOutcome,
) -> tuple[ConsoleActionSubmitter, InMemoryEventBus]:
    bus = InMemoryEventBus()

    async def _lookup(_oid: str, _resource: str | None, _action_type: str) -> PriorRequestOutcome:
        return outcome

    return (
        ConsoleActionSubmitter(event_bus=bus, raw_event_topic=_TOPIC, prior_outcome_lookup=_lookup),
        bus,
    )


def test_prior_deny_blocks_rerequest_and_publishes_nothing() -> None:
    sub, bus = _submitter_with_prior(PriorRequestOutcome.DENIED)
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u", Role.CONTRIBUTOR))
    )
    assert res["submitted"] is False
    assert res["reason"] == "deny_override_forbidden"
    # A deny is authoritative - nothing re-enters the pipeline.
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_prior_no_op_allows_rerequest() -> None:
    sub, bus = _submitter_with_prior(PriorRequestOutcome.NO_OP)
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u", Role.CONTRIBUTOR))
    )
    assert res["submitted"] is True
    # An unnecessary prior conclusion does not block a fresh judgement.
    assert len(asyncio.run(_drain(bus, _TOPIC))) == 1


def test_no_lookup_seam_treats_every_request_as_fresh() -> None:
    # Default submitter (no lookup) never applies the deny-override block.
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u", Role.CONTRIBUTOR))
    )
    assert res["submitted"] is True
    assert len(asyncio.run(_drain(bus, _TOPIC))) == 1


def test_route_prior_deny_gets_403() -> None:
    sub, _bus = _submitter_with_prior(PriorRequestOutcome.DENIED)
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "restart svc-1"})
    assert resp.status_code == 403
    assert resp.json()["reason"] == "deny_override_forbidden"


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


def _app(sub: ConsoleActionSubmitter, principal: Principal) -> Starlette:
    async def _authz(_req: Request) -> Principal:
        return principal

    return Starlette(routes=[make_console_action_route(submitter=sub, authorize_principal=_authz)])


def test_route_contributor_gets_200_submitted() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "restart svc-1", "session_id": "s"})
    assert resp.status_code == 200
    assert resp.json()["submitted"] is True


def test_route_reader_gets_403_capability() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.READER)))
    resp = client.post("/chat/action", json={"prompt": "restart svc-1"})
    assert resp.status_code == 403
    assert resp.json()["reason"] == "rbac_capability"


def test_route_unmapped_is_200_not_submitted() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "provision a cluster"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["submitted"] is False
    assert body["reason"] == "unmapped_action_intent"


def test_route_rejects_empty_prompt() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "   "})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# build_app wiring (dev mode grants a Contributor principal)
# ---------------------------------------------------------------------------


@pytest.fixture
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _built_client(*, wire_action: bool) -> tuple[TestClient, InMemoryEventBus]:
    bus = InMemoryEventBus()
    submitter = ConsoleActionSubmitter(event_bus=bus, raw_event_topic=_TOPIC)
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            console_action=submitter if wire_action else None,
        ),
    )
    return TestClient(app), bus


def test_build_app_registers_action_route_when_wired(_dev_mode: None) -> None:
    client, bus = _built_client(wire_action=True)
    # dev mode grants a Contributor principal, so the submit succeeds.
    resp = client.post("/chat/action", json={"prompt": "restart svc-1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["submitted"] is True
    # The proposal actually reached the bus.
    envs = asyncio.run(_drain(bus, _TOPIC))
    assert len(envs) == 1
    assert envs[0].payload["action_type"] == "ops.restart-service"


def test_build_app_omits_action_route_when_not_wired(_dev_mode: None) -> None:
    client, _bus = _built_client(wire_action=False)
    resp = client.post("/chat/action", json={"prompt": "restart svc-1"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Hardening
# ---------------------------------------------------------------------------


def test_empty_topic_is_rejected_at_construction() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="non-empty topic"):
        ConsoleActionSubmitter(event_bus=InMemoryEventBus(), raw_event_topic="  ")


def test_blank_principal_oid_fails_closed() -> None:
    sub, bus = _submitter()
    blank = Principal(oid="  ", roles=frozenset({Role.CONTRIBUTOR}))
    res = asyncio.run(sub.submit(question="restart svc-1", principal=blank))
    assert res["submitted"] is False
    assert res["reason"] == "invalid_principal"
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_client_idempotency_key_becomes_the_proposal_dedup_key() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(
            question="restart svc-1",
            principal=_principal("u", Role.CONTRIBUTOR),
            idempotency_key="dup-1",
        )
    )
    assert res["submitted"] is True
    envs = asyncio.run(_drain(bus, _TOPIC))
    # The dedup key is namespaced by the initiator so one operator cannot reuse
    # another's key to suppress their action.
    assert envs[0].payload["idempotency_key"] == "u::dup-1"
    # correlation_id stays server-generated and distinct from the dedup key.
    assert envs[0].payload["correlation_id"] != "dup-1"


def test_oversized_operator_values_are_bounded_in_the_proposal() -> None:
    sub, bus = _submitter()
    huge = "restart svc-1 " + ("x" * 10_000)
    res = asyncio.run(
        sub.submit(
            question=huge,
            principal=_principal("u", Role.CONTRIBUTOR),
            session_id="s" * 5_000,
            idempotency_key="k" * 5_000,
        )
    )
    assert res["submitted"] is True
    payload = asyncio.run(_drain(bus, _TOPIC))[0].payload
    assert len(payload["params"]["question"]) <= 2_000
    assert len(payload["params"]["session_id"]) <= 200
    assert len(payload["idempotency_key"]) <= 200


def test_route_rejects_oversized_prompt() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "restart " + ("x" * 5_000)})
    assert resp.status_code == 400


def test_route_rejects_non_string_idempotency_key() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "restart svc-1", "idempotency_key": 5})
    assert resp.status_code == 400
