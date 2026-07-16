from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from fdai.delivery.identity import EntraHumanIdentityDirectory
from fdai.shared.providers.workload_identity import IdentityToken


class FakeIdentity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="graph-token",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            audience=audience,
        )


async def test_entra_directory_searches_graph_and_normalizes_users() -> None:
    identity = FakeIdentity()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer graph-token"
        assert request.headers["consistencylevel"] == "eventual"
        assert request.url.params["$top"] == "10"
        assert "O''Neil" in request.url.params["$filter"]
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "entra-user-1",
                        "displayName": "O'Neil Kim",
                        "userPrincipalName": "oneil@example.com",
                        "mail": "oneil@example.com",
                        "userType": "Member",
                        "accountEnabled": True,
                    },
                    {
                        "id": "entra-user-2",
                        "displayName": "Disabled User",
                        "userPrincipalName": "disabled@example.com",
                        "userType": "Guest",
                        "accountEnabled": False,
                    },
                    {"id": "missing-display-name"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, identity=identity)
        users = await directory.search("O'Neil", limit=10)

    assert identity.audiences == ["https://graph.microsoft.com/.default"]
    assert [user.to_dict() for user in users] == [
        {
            "provider": "entra",
            "subject_id": "entra-user-1",
            "username": "oneil@example.com",
            "display_name": "O'Neil Kim",
            "user_type": "member",
            "active": True,
        },
        {
            "provider": "entra",
            "subject_id": "entra-user-2",
            "username": "disabled@example.com",
            "display_name": "Disabled User",
            "user_type": "guest",
            "active": False,
        },
    ]


async def test_entra_directory_rejects_invalid_search_before_token_request() -> None:
    identity = FakeIdentity()
    async with httpx.AsyncClient() as client:
        directory = EntraHumanIdentityDirectory(client=client, identity=identity)
        for query, limit in (("x", 20), ("valid", 0), ("valid", 51)):
            try:
                await directory.search(query, limit=limit)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid search input was accepted")
    assert identity.audiences == []


async def test_entra_directory_builds_group_and_people_role_roster() -> None:
    identity = FakeIdentity()

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1.0/groups/group-reader":
            return httpx.Response(200, json={"id": "group-reader", "displayName": "fdai-readers"})
        if path == "/v1.0/groups/group-owner":
            return httpx.Response(200, json={"id": "group-owner", "displayName": "fdai-owners"})
        if path.endswith("/members/microsoft.graph.user"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "user-1",
                            "displayName": "Alex Kim",
                            "userPrincipalName": "alex@example.com",
                            "accountEnabled": True,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, identity=identity)
        roster = await directory.list_role_roster(
            {"Reader": "group-reader", "Owner": "group-owner"}
        )

    assert [(item.principal_type, item.display_name) for item in roster] == [
        ("group", "fdai-readers"),
        ("group", "fdai-owners"),
        ("person", "Alex Kim"),
    ]
    assert roster[-1].roles == ("Reader", "Owner")
