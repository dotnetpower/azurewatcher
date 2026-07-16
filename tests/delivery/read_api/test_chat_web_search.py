from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.web_search import WebSearchQuery, WebSearchResult, WebSnippet
from fdai.delivery.read_api.routes.chat import make_chat_health_route, make_chat_route
from fdai.delivery.read_api.routes.chat_web_search import (
    ChatWebSearchConfig,
    ChatWebSearchResolver,
)


class _Provider:
    def __init__(self) -> None:
        self.calls: list[WebSearchQuery] = []

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        self.calls.append(query)
        return WebSearchResult(
            query=query,
            snippets=(
                WebSnippet(
                    url="https://learn.microsoft.com/release",
                    domain="learn.microsoft.com",
                    title="Release notes",
                    text="The latest SDK release is version 2.",
                    content_hash="sha256:web",
                    fetched_at=datetime.now(tz=UTC),
                ),
            ),
        )


class _Backend:
    def __init__(self) -> None:
        self.view_context: dict[str, Any] | None = None

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        self.view_context = view_context
        return {"answer": "The latest SDK release is version 2.", "model": "mini-fast"}


async def _allow(_: Request) -> str:
    return "reader"


def _resolver(provider: _Provider) -> ChatWebSearchResolver:
    return ChatWebSearchResolver(
        provider=provider,
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )


async def test_normal_screen_question_does_not_search() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve("What does this screen show?", {})

    assert evidence is None
    assert provider.calls == []


async def test_latest_public_fact_searches_and_returns_sanitized_evidence() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve(
        "What is the latest Azure SDK version?",
        {},
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert len(provider.calls) == 1
    assert provider.calls[0].metadata["tier"] == "chat-t2"
    assert evidence["snippets"][0].startswith('<web_snippet trusted="false"')


async def test_explicit_search_can_fill_gap_after_internal_evidence() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve(
        "Search the web for the latest Azure SDK release.",
        {"_agent_evidence": {"answer": "internal"}},
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert len(provider.calls) == 1


async def test_sensitive_query_is_blocked_before_provider_call() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve(
        "Search the web for subscription 00000000-0000-0000-0000-000000000000",
        {},
    )

    assert evidence == {
        "status": "skipped",
        "reason": "query_not_public_safe",
        "sources": [],
    }
    assert provider.calls == []


def test_chat_route_injects_and_surfaces_public_web_evidence() -> None:
    provider = _Provider()
    resolver = _resolver(provider)
    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                web_search_resolver=resolver,
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "Search the web for the latest Azure SDK release.",
            "view_context": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert backend.view_context is not None
    assert backend.view_context["_web_evidence"]["status"] == "matched"
    assert payload["web_search"]["status"] == "matched"
    assert payload["web_search"]["sources"][0]["url"] == ("https://learn.microsoft.com/release")
    assert payload["verification"]["authority"] == "public_web_snapshot"


def test_chat_health_describes_web_search_without_exposing_snippets() -> None:
    resolver = _resolver(_Provider())
    app = Starlette(
        routes=[
            make_chat_health_route(
                backend=_Backend(),
                authorize=_allow,
                web_search_resolver=resolver,
            )
        ]
    )

    payload = TestClient(app).get("/chat/health").json()

    assert payload["web_search"]["available"] is True
    assert payload["web_search"]["allowed_domains"] == ["learn.microsoft.com"]
    assert "snippets" not in payload["web_search"]
