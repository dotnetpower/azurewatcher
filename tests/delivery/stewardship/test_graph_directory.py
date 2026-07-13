"""Graph stewardship adapter tests (httpx MockTransport, no network)."""

from __future__ import annotations

import httpx
import pytest

from fdai.delivery.stewardship import (
    GraphGroupMembershipProvider,
    GraphIdentityDirectory,
)


async def _token() -> str:
    return "test-token"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_is_active_true_when_account_enabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"accountEnabled": True})

    async with _client(handler) as client:
        directory = GraphIdentityDirectory(client=client, token_provider=_token)
        assert await directory.is_active("oid-1") is True


async def test_is_active_false_when_disabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accountEnabled": False})

    async with _client(handler) as client:
        directory = GraphIdentityDirectory(client=client, token_provider=_token)
        assert await directory.is_active("oid-1") is False


async def test_is_active_false_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})

    async with _client(handler) as client:
        directory = GraphIdentityDirectory(client=client, token_provider=_token)
        assert await directory.is_active("missing") is False


async def test_is_active_raises_on_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with _client(handler) as client:
        directory = GraphIdentityDirectory(client=client, token_provider=_token)
        with pytest.raises(httpx.HTTPStatusError):
            await directory.is_active("oid-1")


async def test_members_of_follows_pagination() -> None:
    page1 = {
        "value": [{"id": "u1"}, {"id": "u2"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/groups/g/members?page=2",
    }
    page2 = {"value": [{"id": "u3"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if "page=2" in str(request.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    async with _client(handler) as client:
        provider = GraphGroupMembershipProvider(client=client, token_provider=_token)
        members = await provider.members_of("g")
        assert members == ("u1", "u2", "u3")


async def test_members_of_unknown_group_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _client(handler) as client:
        provider = GraphGroupMembershipProvider(client=client, token_provider=_token)
        assert await provider.members_of("missing") == ()
