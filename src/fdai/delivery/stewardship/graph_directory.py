"""Microsoft Graph adapters for the stewardship identity seams.

Concrete, fork-facing implementations of the two Protocols in
:mod:`fdai.core.stewardship.directory`:

- :class:`GraphIdentityDirectory` - OID liveness via ``GET /users/{oid}``.
- :class:`GraphGroupMembershipProvider` - group expansion via
  ``GET /groups/{oid}/members``.

Delivery-layer code (may use an HTTP client), bound at the composition root and
injected into the off-hot-path stewardship checks. Both take an injected
``httpx.AsyncClient`` and an async token provider so the transport, auth, and
base URL stay a fork concern; core never sees Graph.

Auth: the token provider returns a bearer access token for the
``https://graph.microsoft.com/.default`` scope (a fork wires
``DefaultAzureCredential`` or a client-credentials flow behind it).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

_DEFAULT_BASE_URL = "https://graph.microsoft.com/v1.0"

TokenProvider = Callable[[], Awaitable[str]]


class GraphIdentityDirectory:
    """:class:`~fdai.core.stewardship.directory.IdentityDirectory` over Graph.

    ``is_active`` returns ``True`` only when the account exists and
    ``accountEnabled`` is true. A ``404`` (deleted / unknown user) is a clean
    ``False``. Other non-success responses raise, so a scheduled stale-OID
    sweep can retry rather than silently marking a live steward stale.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        token_provider: TokenProvider,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._client = client
        self._token = token_provider
        self._base = base_url.rstrip("/")

    async def is_active(self, oid: str) -> bool:
        token = await self._token()
        resp = await self._client.get(
            f"{self._base}/users/{oid}",
            params={"$select": "accountEnabled"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        payload = resp.json()
        return bool(payload.get("accountEnabled", False))


class GraphGroupMembershipProvider:
    """:class:`~fdai.core.stewardship.directory.GroupMembershipProvider` over Graph.

    ``members_of`` returns the member **user** object ids, following Graph
    ``@odata.nextLink`` pagination. Per the Protocol contract it never raises for
    an unknown group - a ``404`` yields an empty tuple so escalation degrades to
    treating the group as one opaque unit.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        token_provider: TokenProvider,
        base_url: str = _DEFAULT_BASE_URL,
        page_limit: int = 20,
    ) -> None:
        self._client = client
        self._token = token_provider
        self._base = base_url.rstrip("/")
        self._page_limit = page_limit

    async def members_of(self, group_oid: str) -> tuple[str, ...]:
        token = await self._token()
        headers = {"Authorization": f"Bearer {token}"}
        url: str | None = f"{self._base}/groups/{group_oid}/members"
        params: dict[str, str] | None = {"$select": "id"}
        members: list[str] = []
        pages = 0
        while url is not None and pages < self._page_limit:
            resp = await self._client.get(url, params=params, headers=headers)
            if resp.status_code == 404:
                return ()
            resp.raise_for_status()
            payload = resp.json()
            for entry in payload.get("value", []):
                member_id = entry.get("id")
                if isinstance(member_id, str) and member_id:
                    members.append(member_id)
            url = payload.get("@odata.nextLink")
            params = None  # nextLink already carries the query
            pages += 1
        return tuple(members)


__all__ = [
    "GraphGroupMembershipProvider",
    "GraphIdentityDirectory",
    "TokenProvider",
]
