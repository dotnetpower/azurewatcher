"""Local Azure CLI inventory graph projection tests."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.delivery.read_api.dev.azure_inventory_graph import (
    AzureCliInventoryGraphProvider,
    inventory_cache_path,
)
from fdai.delivery.read_api.dev.helpers import build_inventory_graph_provider
from fdai.delivery.read_api.routes.inventory_graph import InventoryGraphViewNotFoundError
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord


class _Inventory:
    def __init__(self, *, final: bool = True) -> None:
        self.calls = 0
        self.final = final

    async def full_snapshot(self, since: str | None = None):  # type: ignore[no-untyped-def]
        del since
        self.calls += 1
        yield InventoryBatch(
            resources=(
                ResourceRecord(
                    resource_id="resourcegroups/rg-example",
                    type="resource-group",
                    props={
                        "name": "rg-example",
                        "resourceGroup": "rg-example",
                        "tags": {"fdai:managed": "true", "fdai:workload": "fdai"},
                    },
                    provider_ref="/subscriptions/example/resourceGroups/rg-example",
                ),
                ResourceRecord(
                    resource_id=(
                        "resourcegroups/rg-example/providers/"
                        "microsoft.compute/virtualmachines/vm-example"
                    ),
                    type="compute.vm",
                    props={
                        "name": "vm-example",
                        "resourceGroup": "rg-example",
                        "powerState": "VM running",
                        "provisioningState": "Succeeded",
                    },
                    provider_ref="/subscriptions/example/resourceGroups/rg-example/vm-example",
                ),
            ),
            cursor="page-1",
        )
        if self.final:
            yield InventoryBatch(cursor="done", final=True)

    async def delta(self, cursor: str):  # type: ignore[no-untyped-def]
        del cursor
        if False:
            yield InventoryBatch()


def test_projects_contains_graph_without_provider_refs_and_caches() -> None:
    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(inventory=inventory, cache_ttl_seconds=60)

    async def _run() -> tuple[dict[str, object], dict[str, object]]:
        first = await provider(None, 4, ("contains",))
        second = await provider(None, 4, ("contains",))
        return first, second

    first, second = asyncio.run(_run())
    assert inventory.calls == 1
    assert first == second
    assert first["source"] == "azure-cli-local"
    assert first["cursor"] == "done"
    resources = first["resources"]
    assert len(resources) == 3
    assert all("provider_ref" not in resource and "props" not in resource for resource in resources)
    assert all(0 <= resource["x"] <= 18 and 0 <= resource["y"] <= 12 for resource in resources)
    assert all(
        resource.get("x", 0) + resource.get("w", 0) <= 18
        and resource.get("y", 0) + resource.get("h", 0) <= 12
        for resource in resources
    )
    vm = next(resource for resource in resources if resource["type"] == "compute.vm")
    assert vm["status"] == "VM running"
    assert first["links"] == [
        {
            "source": "azure-subscription",
            "target": "resourcegroups/rg-example",
            "type": "contains",
        },
        {
            "source": "resourcegroups/rg-example",
            "target": (
                "resourcegroups/rg-example/providers/microsoft.compute/virtualmachines/vm-example"
            ),
            "type": "contains",
        },
    ]


def test_filters_links_and_marks_truncation() -> None:
    provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(), cache_ttl_seconds=0, max_resources=1
    )
    graph = asyncio.run(provider(None, 4, ("depends_on",)))
    assert graph["truncated"] is True
    assert graph["links"] == []


def test_rejects_unknown_named_view() -> None:
    provider = AzureCliInventoryGraphProvider(inventory=_Inventory())

    with pytest.raises(InventoryGraphViewNotFoundError, match="production"):
        asyncio.run(provider("production", 4, ("contains",)))


def test_rejects_snapshot_without_final_fence() -> None:
    provider = AzureCliInventoryGraphProvider(inventory=_Inventory(final=False))
    with pytest.raises(RuntimeError, match="final fence"):
        asyncio.run(provider(None, 4, ("contains",)))


def test_helper_disables_persistent_cache_without_explicit_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_LOCAL_AZURE_DISCOVERY", raising=False)
    monkeypatch.delenv("FDAI_LOCAL_AZURE_SUBSCRIPTION_ID", raising=False)
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
    monkeypatch.delenv("FDAI_LOCAL_AZURE_CONFIG_DIR", raising=False)

    provider = build_inventory_graph_provider()

    assert provider.inventory.subscription_id is None
    assert provider.cache_path is None
    assert provider.cache_identity is None
    assert provider.invalidation_path is None


def test_helper_isolates_cache_by_explicit_subscription_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_LOCAL_AZURE_DISCOVERY", raising=False)
    monkeypatch.delenv("FDAI_LOCAL_AZURE_SUBSCRIPTION_ID", raising=False)
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "subscription-example")
    monkeypatch.setenv("FDAI_LOCAL_AZURE_CONFIG_DIR", "/profiles/example")

    provider = build_inventory_graph_provider()

    assert provider.inventory.subscription_id == "subscription-example"
    assert provider.inventory.azure_config_dir == "/profiles/example"
    assert provider.cache_path is not None
    assert provider.cache_identity is not None
    assert provider.cache_identity in provider.cache_path.name
    assert "subscription-example" not in provider.cache_path.name
    assert provider.invalidation_path == provider.cache_path.with_suffix(".invalidated")


def test_persistent_cache_survives_provider_restart(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    first_inventory = _Inventory()
    first_provider = AzureCliInventoryGraphProvider(
        inventory=first_inventory,
        cache_path=cache_path,
        cache_identity=identity,
    )
    first = asyncio.run(first_provider(None, 4, ("contains",)))

    second_inventory = _Inventory()
    second_provider = AzureCliInventoryGraphProvider(
        inventory=second_inventory,
        cache_path=cache_path,
        cache_identity=identity,
    )
    second = asyncio.run(second_provider(None, 4, ("contains",)))

    assert first_inventory.calls == 1
    assert second_inventory.calls == 0
    assert second["resources"] == first["resources"]
    assert second["cache"] == {
        "status": "fresh",
        "age_seconds": 0,
        "persistent": True,
    }
    assert "subscription-example" not in cache_path.name
    serialized = cache_path.read_text(encoding="utf-8")
    assert "subscription-example" not in serialized
    assert "/subscriptions/" not in serialized
    assert "provider_ref" not in serialized


def test_stale_cache_returns_immediately_and_refreshes_in_background(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir="/profiles/example",
    )
    seed_provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(),
        cache_path=cache_path,
        cache_identity=identity,
    )
    asyncio.run(seed_provider(None, 4, ("contains",)))
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["cached_at"] = (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat()
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_ttl_seconds=60,
        cache_path=cache_path,
        cache_identity=identity,
    )

    async def _run() -> tuple[dict[str, object], dict[str, object]]:
        stale = await provider(None, 4, ("contains",))
        await provider.wait_for_refresh()
        fresh = await provider(None, 4, ("contains",))
        return stale, fresh

    stale, fresh = asyncio.run(_run())
    assert stale["freshness"] == "stale"
    assert stale["cache"]["status"] == "refreshing"
    assert inventory.calls == 1
    assert fresh["freshness"] == "fresh"
    assert fresh["cache"]["status"] == "fresh"


def test_cache_identity_mismatch_forces_new_snapshot(tmp_path: Path) -> None:
    cache_path = tmp_path / "inventory.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "identity": "other-subscription",
                "cached_at": datetime.now(tz=UTC).isoformat(),
                "graph": {"resources": [], "links": []},
            }
        ),
        encoding="utf-8",
    )
    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_path=cache_path,
        cache_identity="expected-subscription",
    )

    graph = asyncio.run(provider(None, 4, ("contains",)))

    assert inventory.calls == 1
    assert len(graph["resources"]) == 3


def test_invalidation_marker_refreshes_cache_before_ttl(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    marker = cache_path.parent / f"{identity}.invalidated"
    seed_provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(),
        cache_path=cache_path,
        cache_identity=identity,
        invalidation_path=marker,
    )
    asyncio.run(seed_provider(None, 4, ("contains",)))
    time.sleep(0.01)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("changed\n", encoding="ascii")

    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_ttl_seconds=3600,
        cache_path=cache_path,
        cache_identity=identity,
        invalidation_path=marker,
    )

    async def _run() -> dict[str, object]:
        stale = await provider(None, 4, ("contains",))
        await provider.wait_for_refresh()
        return stale

    stale = asyncio.run(_run())
    assert stale["cache"]["status"] == "refreshing"
    assert inventory.calls == 1
