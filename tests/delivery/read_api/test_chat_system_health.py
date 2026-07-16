"""System-health evidence routing for Command Deck chat."""

from __future__ import annotations

import json
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.chat import (
    _with_tool_evidence,
    make_chat_route,
    make_chat_stream_route,
)
from fdai.delivery.read_api.routes.chat_claims import verify_screen_claims
from fdai.delivery.read_api.routes.chat_system_health import (
    SystemHealthChatTools,
    render_system_health_answer,
)


def _model() -> InMemoryConsoleReadModel:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "correlation_id": "corr-1",
            "outcome": "auto",
            "tier": "t0",
        },
        actor="Thor",
        action_kind="ops.restart-service",
        mode="shadow",
    )
    return model


class _NoCallBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError("system-health fast path must not call the model backend")


async def _allow(_: Request) -> str:
    return "test-reader"


def _done_event(body: str) -> dict[str, Any]:
    for block in body.split("\n\n"):
        if not block.startswith("event: done\n"):
            continue
        data = next(line[6:] for line in block.splitlines() if line.startswith("data: "))
        return json.loads(data)  # type: ignore[no-any-return]
    raise AssertionError("done event missing")


async def test_broad_health_query_uses_server_metrics_from_any_screen() -> None:
    resolver = SystemHealthChatTools(_model())
    context = await _with_tool_evidence(
        "\uc804\ubc18\uc801\uc778 \ub3d9\uc791\uc774 \uc798 \ud558\uace0 \uc788\uc5b4?",
        {
            "routeId": "documents",
            "facts": [{"key": "selected_files", "value": 0}],
        },
        resolver,
    )

    evidence = context["_tool_evidence"]
    assert evidence["tool"] == "get_system_health"
    assert evidence["authority"] == "server_read_model"
    assert evidence["result"]["event_count"] == 1

    answer = render_system_health_answer(context, locale="ko")
    assert answer is not None
    assert "\uac10\uc0ac \uc774\ubca4\ud2b8 \uc218(event count) 1\uac74" in answer
    assert (
        "\ubaa8\ub4e0 \uad6c\uc131\uc694\uc18c\uac00 \uc815\uc0c1\uc774\ub77c\uace0 \ub2e8\uc815"
    ) in answer

    verification = verify_screen_claims(
        answer,
        context,
    )
    assert verification.supported is True
    assert verification.manifest.authority == "server_read_model"
    assert verification.claims[0].evidence_refs == ("tool:result:event_count",)


async def test_route_local_control_question_stays_with_the_screen() -> None:
    resolver = SystemHealthChatTools(_model())
    context = await _with_tool_evidence(
        "Is this upload button working?",
        {"routeId": "documents", "facts": []},
        resolver,
    )

    assert "_tool_evidence" not in context


def test_empty_health_sample_abstains_without_claiming_failure() -> None:
    answer = render_system_health_answer(
        {
            "_tool_evidence": {
                "tool": "get_system_health",
                "authority": "server_read_model",
                "result": {
                    "event_count": 0,
                    "hil_pending": 0,
                    "shadow_share": 0.0,
                    "enforce_share": 0.0,
                    "last_recorded_at": None,
                },
            }
        },
        locale="en",
    )

    assert answer is not None
    assert "overall system health cannot be confirmed" in answer
    assert "does not prove a failure" in answer


def test_sync_route_returns_canonical_health_without_model_call() -> None:
    backend = _NoCallBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SystemHealthChatTools(_model()),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "Is the overall system working properly?",
            "view_context": {"routeId": "documents", "facts": []},
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "read-model-health"
    assert response.json()["verification"]["authority"] == "server_read_model"
    assert response.json()["verification"]["status"] != "unverified"
    assert backend.calls == 0


def test_stream_route_returns_canonical_health_without_model_call() -> None:
    backend = _NoCallBackend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SystemHealthChatTools(_model()),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": (
                "\uc804\uccb4 \uc2dc\uc2a4\ud15c\uc774 \uc815\uc0c1 "
                "\uc791\ub3d9\ud558\uace0 \uc788\uc5b4?"
            ),
            "view_context": {"routeId": "documents", "facts": []},
        },
    )
    done = _done_event(response.text)

    assert response.status_code == 200
    assert done["model"] == "read-model-health"
    assert done["source"] == "evidence:system-health"
    assert done["verification"]["authority"] == "server_read_model"
    assert done["verification"]["status"] != "unverified"
    assert backend.calls == 0
