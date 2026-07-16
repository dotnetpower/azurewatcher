from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.chat import LatencyRoutedChatBackend, make_chat_route
from fdai.delivery.read_api.routes.model_settings import (
    ModelSettingsService,
    make_model_settings_routes,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Backend:
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {"answer": prompt, "model": "test"}


def _resolved(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "region": "example-region",
                "mixed_model_mode": "hil-only",
                "capabilities": [
                    {
                        "name": "t1.judge",
                        "status": "resolved",
                        "publisher": "OpenAI",
                        "family": "gpt-mini",
                        "capacity_tpm": 1000,
                        "invocation": "always",
                        "reasons": [],
                    },
                    {
                        "name": "t2.reasoner.secondary",
                        "status": "hil-only",
                        "publisher": None,
                        "family": None,
                        "capacity_tpm": 0,
                        "invocation": "always",
                        "reasons": ["not available"],
                    },
                    {
                        "name": "narrator-fast",
                        "status": "resolved",
                        "family": "gpt-fast",
                    },
                    {
                        "name": "narrator-steady",
                        "status": "resolved",
                        "family": "gpt-steady",
                    },
                ],
                "narrator_candidates": [
                    {"deployment": "narrator-fast"},
                    {"deployment": "narrator-steady"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _service(tmp_path: Path) -> ModelSettingsService:
    router = LatencyRoutedChatBackend(
        candidates=[("narrator-fast", _Backend()), ("narrator-steady", _Backend())]
    )
    return ModelSettingsService(
        resolved_models_path=_resolved(tmp_path / "resolved-models.json"),
        store=InMemoryStateStore(),
        backend=router,
    )


async def test_projects_capabilities_provisioning_and_latency_candidates(tmp_path: Path) -> None:
    service = _service(tmp_path)

    projection = await service.projection("user-1")

    assert projection["region"] == "example-region"
    assert projection["discovery"]["automatic"] is True
    assert projection["provisioning"] == {
        "automatic": True,
        "status": "degraded",
        "resolved_count": 1,
        "hil_only_count": 1,
    }
    assert projection["narrator"]["requested"] == "auto"
    assert [item["deployment"] for item in projection["narrator"]["candidates"]] == [
        "narrator-fast",
        "narrator-steady",
    ]
    assert projection["t2_selection_scope"] == "system-governed"


async def test_persists_allowlisted_user_preference(tmp_path: Path) -> None:
    service = _service(tmp_path)

    await service.set_preference("user-1", "narrator-steady")

    assert await service.preferred_model("user-1") == "narrator-steady"
    projection = await service.projection("user-1")
    assert projection["narrator"]["effective"] == "narrator-steady"


async def test_rejects_unavailable_user_preference(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="available candidate"):
        await service.set_preference("user-1", "not-deployed")


def test_saved_preference_routes_the_authenticated_users_chat(tmp_path: Path) -> None:
    service = _service(tmp_path)

    async def authorize(request: Request) -> str:
        return request.headers.get("x-user", "anonymous")

    application = Starlette(
        routes=[
            *make_model_settings_routes(service=service, authorize=authorize),
            make_chat_route(
                backend=service.backend,  # type: ignore[arg-type]
                authorize=authorize,
                model_preference_resolver=service.preferred_model,
            ),
        ]
    )
    client = TestClient(application)

    saved = client.put(
        "/me/model-preferences",
        headers={"x-user": "user-1"},
        json={"preferred_narrator_model": "narrator-steady"},
    )
    reply = client.post(
        "/chat",
        headers={"x-user": "user-1"},
        json={"prompt": "Summarize the current view.", "view_context": {}},
    )

    assert saved.status_code == 200
    assert saved.json()["narrator"]["effective"] == "narrator-steady"
    assert reply.status_code == 200
    assert reply.json()["model"] == "narrator-steady"
    assert reply.json()["router"]["reason"] == "user-preferred"
