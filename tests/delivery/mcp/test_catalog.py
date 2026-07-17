"""Managed MCP catalog, endpoint, discovery, and ownership tests."""

from __future__ import annotations

import json

import httpx
import pytest

from fdai.core.sandbox import (
    ProfiledToolExecutor,
    SandboxPolicyError,
    ToolSandboxCatalog,
    ToolSandboxProfile,
)
from fdai.delivery.mcp import (
    McpCatalogError,
    McpDiscoveryClient,
    McpServerCatalog,
    McpServerManifest,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.tool import RecordingToolExecutor


def _manifest(server_id: str = "example.tools", action: str = "tool.example") -> McpServerManifest:
    return McpServerManifest(
        server_id=server_id,
        server_url="https://tools.example.com/mcp",
        tool_map={action: "example_tool"},
    )


def test_server_installs_disabled_and_requires_discovered_allowlist() -> None:
    catalog = McpServerCatalog().install(_manifest())

    assert catalog.get("example.tools").enabled is False
    with pytest.raises(McpCatalogError, match="missing tools"):
        catalog.enable("example.tools", discovered_tools=frozenset())

    enabled = catalog.enable("example.tools", discovered_tools=frozenset({"example_tool"}))
    assert enabled.get("example.tools").enabled is True


def test_two_enabled_servers_cannot_own_the_same_action_type() -> None:
    catalog = McpServerCatalog().install(_manifest())
    catalog = catalog.enable("example.tools", discovered_tools=frozenset({"example_tool"}))
    catalog = catalog.install(_manifest("other.tools"))

    with pytest.raises(McpCatalogError, match="owned by both"):
        catalog.enable("other.tools", discovered_tools=frozenset({"example_tool"}))


def _sandbox_catalog() -> ToolSandboxCatalog:
    return ToolSandboxCatalog(
        (
            ToolSandboxProfile(
                profile_id="mcp.example",
                action_type_names=frozenset({"tool.example"}),
                allowed_modes=frozenset({Mode.SHADOW}),
                max_argument_items=4,
                max_argument_bytes=1_000,
                max_tool_ref_bytes=200,
            ),
        )
    )


def test_enabled_routes_require_and_attach_sandbox_profile() -> None:
    catalog = McpServerCatalog().install(_manifest())
    catalog = catalog.enable("example.tools", discovered_tools=frozenset({"example_tool"}))

    routes = catalog.build_routes(
        lambda _: RecordingToolExecutor(),
        sandbox_catalog=_sandbox_catalog(),
    )

    assert isinstance(routes["tool.example"], ProfiledToolExecutor)


def test_enabled_route_without_sandbox_profile_is_rejected() -> None:
    catalog = McpServerCatalog().install(_manifest())
    catalog = catalog.enable("example.tools", discovered_tools=frozenset({"example_tool"}))

    with pytest.raises(SandboxPolicyError, match="no sandbox profile"):
        catalog.build_routes(
            lambda _: RecordingToolExecutor(),
            sandbox_catalog=ToolSandboxCatalog(),
        )


@pytest.mark.parametrize(
    "url",
    (
        "http://tools.example.com/mcp",
        "https://user:password@tools.example.com/mcp",
        "file:///tmp/mcp",
        "https://tools.example.com/mcp?token=value",
    ),
)
def test_endpoint_validation_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError, match="MCP server_url"):
        McpServerManifest(
            server_id="example.tools",
            server_url=url,
            tool_map={"tool.example": "example_tool"},
        )


def test_loopback_http_is_allowed_for_sidecars() -> None:
    manifest = McpServerManifest(
        server_id="example.sidecar",
        server_url="http://127.0.0.1:9000/mcp",
        tool_map={"tool.example": "example_tool"},
    )
    assert manifest.server_url.startswith("http://127.0.0.1")


async def test_discovery_lists_tools_without_invoking_them() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "discovery",
                "result": {"tools": [{"name": "example_tool"}, {"name": "other_tool"}]},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tools = await McpDiscoveryClient(http_client=client).discover(_manifest())

    assert captured["method"] == "tools/list"
    assert tools == frozenset({"example_tool", "other_tool"})


async def test_discovery_rejects_mismatched_rpc_id() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "wrong", "result": {"tools": []}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(McpCatalogError, match="invalid JSON-RPC"):
            await McpDiscoveryClient(http_client=client).discover(_manifest())
