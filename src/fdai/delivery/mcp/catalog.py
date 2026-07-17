"""Managed MCP server catalog and read-only tool discovery."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final
from urllib.parse import urlparse

import httpx

from fdai.core.sandbox import ProfiledToolExecutor, ToolSandboxCatalog
from fdai.shared.providers.tool import ToolExecutor
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_MAX_DISCOVERY_BYTES: Final = 1_000_000


@dataclass(frozen=True, slots=True)
class McpServerManifest:
    """Inert server endpoint and ActionType-to-tool allowlist."""

    server_id: str
    server_url: str
    tool_map: Mapping[str, str]
    audience: str | None = None
    enabled: bool = False

    def __post_init__(self) -> None:
        if _ID_PATTERN.fullmatch(self.server_id) is None:
            raise ValueError("MCP server_id MUST be lowercase ASCII with dot or hyphen separators")
        _validate_server_url(self.server_url)
        normalized = dict(self.tool_map)
        if not normalized or any(not key or not value for key, value in normalized.items()):
            raise ValueError("MCP tool_map MUST contain non-empty ActionType and tool names")
        object.__setattr__(self, "tool_map", MappingProxyType(normalized))


class McpCatalogError(ValueError):
    """MCP server registration or activation failed closed."""


class McpServerCatalog:
    """Immutable managed registry; servers install disabled and enable explicitly."""

    __slots__ = ("_servers",)

    def __init__(self, servers: Mapping[str, McpServerManifest] | None = None) -> None:
        self._servers = MappingProxyType(dict(servers or {}))
        _validate_route_ownership(self._servers.values())

    def install(self, manifest: McpServerManifest) -> McpServerCatalog:
        if manifest.server_id in self._servers:
            raise McpCatalogError(f"MCP server {manifest.server_id!r} is already installed")
        if manifest.enabled:
            raise McpCatalogError(
                "MCP servers MUST install disabled and pass discovery before enable"
            )
        servers = dict(self._servers)
        servers[manifest.server_id] = manifest
        return McpServerCatalog(servers)

    def enable(
        self,
        server_id: str,
        *,
        discovered_tools: frozenset[str],
    ) -> McpServerCatalog:
        current = self.get(server_id)
        missing = set(current.tool_map.values()) - discovered_tools
        if missing:
            raise McpCatalogError(f"MCP server discovery is missing tools: {sorted(missing)}")
        servers = dict(self._servers)
        servers[server_id] = replace(current, enabled=True)
        return McpServerCatalog(servers)

    def disable(self, server_id: str) -> McpServerCatalog:
        current = self.get(server_id)
        servers = dict(self._servers)
        servers[server_id] = replace(current, enabled=False)
        return McpServerCatalog(servers)

    def uninstall(self, server_id: str) -> McpServerCatalog:
        current = self.get(server_id)
        if current.enabled:
            raise McpCatalogError("disable an MCP server before uninstalling it")
        servers = dict(self._servers)
        del servers[server_id]
        return McpServerCatalog(servers)

    def get(self, server_id: str) -> McpServerManifest:
        try:
            return self._servers[server_id]
        except KeyError as exc:
            raise McpCatalogError(f"MCP server {server_id!r} is not installed") from exc

    def list(self) -> tuple[McpServerManifest, ...]:
        return tuple(self._servers[key] for key in sorted(self._servers))

    def build_routes(
        self,
        factory: Callable[[McpServerManifest], ToolExecutor],
        *,
        sandbox_catalog: ToolSandboxCatalog,
    ) -> Mapping[str, ToolExecutor]:
        routes: dict[str, ToolExecutor] = {}
        for manifest in self.list():
            if not manifest.enabled:
                continue
            executor = ProfiledToolExecutor(
                catalog=sandbox_catalog,
                executor=factory(manifest),
            )
            for action_type in manifest.tool_map:
                sandbox_catalog.require(action_type)
                routes[action_type] = executor
        return MappingProxyType(routes)


class McpDiscoveryClient:
    """Call MCP `tools/list` without invoking any tool."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        identity: WorkloadIdentity | None = None,
        max_response_bytes: int = _MAX_DISCOVERY_BYTES,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("MCP discovery response cap MUST be positive")
        self._http = http_client
        self._identity = identity
        self._max_response_bytes = max_response_bytes

    async def discover(self, manifest: McpServerManifest) -> frozenset[str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if manifest.audience is not None:
            if self._identity is None:
                raise McpCatalogError("MCP audience requires an injected WorkloadIdentity")
            token = await self._identity.get_token(manifest.audience)
            headers["Authorization"] = f"Bearer {token.token}"
        body = {"jsonrpc": "2.0", "id": "discovery", "method": "tools/list", "params": {}}
        try:
            response = await self._http.post(
                manifest.server_url,
                headers=headers,
                content=json.dumps(body),
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            raise McpCatalogError("MCP discovery transport failed") from exc
        if not response.is_success:
            raise McpCatalogError(f"MCP discovery returned HTTP {response.status_code}")
        if len(response.content) > self._max_response_bytes:
            raise McpCatalogError("MCP discovery response exceeds the configured cap")
        try:
            payload = response.json()
        except ValueError as exc:
            raise McpCatalogError("MCP discovery returned invalid JSON") from exc
        return _parse_discovery(payload)


def _parse_discovery(payload: object) -> frozenset[str]:
    if not isinstance(payload, Mapping) or payload.get("id") != "discovery":
        raise McpCatalogError("MCP discovery returned an invalid JSON-RPC response")
    if payload.get("error") is not None:
        raise McpCatalogError("MCP discovery returned a JSON-RPC error")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise McpCatalogError("MCP discovery response has no result")
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise McpCatalogError("MCP discovery result has no tool list")
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, Mapping):
            raise McpCatalogError("MCP discovery contains an invalid tool entry")
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise McpCatalogError("MCP discovery contains a tool without a name")
        names.add(name)
    return frozenset(names)


def _validate_server_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("MCP server_url MUST NOT contain credentials, query, or fragment")
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("MCP server_url MUST be an absolute HTTP(S) URL")
    if parsed.scheme == "http" and parsed.hostname.lower() not in _LOOPBACK_HOSTS:
        raise ValueError("MCP server_url MUST use HTTPS outside loopback")


def _validate_route_ownership(manifests: Iterable[McpServerManifest]) -> None:
    owners: dict[str, str] = {}
    for manifest in manifests:
        if not manifest.enabled:
            continue
        for action_type in manifest.tool_map:
            prior = owners.get(action_type)
            if prior is not None:
                raise McpCatalogError(
                    f"ActionType {action_type!r} is owned by both {prior!r} and "
                    f"{manifest.server_id!r}"
                )
            owners[action_type] = manifest.server_id


__all__ = [
    "McpCatalogError",
    "McpDiscoveryClient",
    "McpServerCatalog",
    "McpServerManifest",
]
