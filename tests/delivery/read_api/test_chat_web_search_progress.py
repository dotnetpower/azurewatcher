"""Progress visibility for Command Deck public-web research."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.web_search import WebSearchQuery, WebSearchResult, WebSnippet
from fdai.delivery.read_api.routes.chat import make_chat_stream_route
from fdai.delivery.read_api.routes.chat_web_search import ChatWebSearchConfig, ChatWebSearchResolver


class _Provider:
    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        return WebSearchResult(
            query=query,
            snippets=(
                WebSnippet(
                    url="https://learn.microsoft.com/release",
                    domain="learn.microsoft.com",
                    title="Release notes",
                    text="The latest SDK release is version 2.",
                    content_hash="sha256:web-progress",
                    fetched_at=datetime.now(tz=UTC),
                ),
            ),
        )


class _IntentClassifier:
    async def classify_intent(self, prompt: str, *, budget_ms: int) -> dict[str, object]:
        del prompt, budget_ms
        return {
            "route": "web",
            "confidence": 0.93,
            "reason": "public_research",
            "query": "current MTTR platforms",
            "goal": "research",
            "subject": "",
            "capabilities": [],
        }


class _Backend:
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, str]:
        del prompt, view_context, history
        return {"answer": "The latest SDK release is version 2.", "model": "mini-fast"}


async def _allow(request: Request) -> str:
    del request
    return "reader"


def _resolver() -> ChatWebSearchResolver:
    return ChatWebSearchResolver(
        provider=_Provider(),
        intent_classifier=_IntentClassifier(),
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )


async def test_reports_model_routing_search_and_grounding_progress() -> None:
    progress: list[dict[str, object]] = []

    async def observe(event: dict[str, object]) -> None:
        progress.append(event)

    evidence = await _resolver().resolve_with_progress(
        "Recommend suitable MTTR platforms",
        {"_answer_plan": {"intent": "open_question"}},
        progress_observer=observe,
    )

    assert evidence is not None
    assert [event["phase"] for event in progress] == [
        "web_search_classifying",
        "web_search_searching",
        "web_search_grounded",
    ]
    assert "narrator model" in str(progress[0]["label"])
    assert progress[-1]["completed"] == 1
    assert progress[-1]["total"] == 1
    assert progress[-1]["sources"] == [
        {
            "kind": "public-web",
            "label": "Release notes",
            "detail": "learn.microsoft.com",
            "side_effect_class": "ground",
        }
    ]


def test_stream_surfaces_web_search_progress_before_answer() -> None:
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=_Backend(),
                authorize=_allow,
                web_search_resolver=_resolver(),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "request_id": "request-web-progress",
            "prompt": "Recommend suitable MTTR platforms",
            "view_context": {},
        },
    )

    assert response.status_code == 200
    body = response.text
    classifying = body.index('"phase": "web_search_classifying"')
    searching = body.index('"phase": "web_search_searching"')
    grounded = body.index('"phase": "web_search_grounded"')
    provisional = body.index("event: provisional")
    assert classifying < searching < grounded < provisional
