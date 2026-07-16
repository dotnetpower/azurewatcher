"""Copy-ready fork capability bundle integration tests."""

from pathlib import Path

from fdai.composition import default_container
from fdai.core.tools import FileSystemToolRegistry
from fdai.fork_examples.capability_bundle import install_state_query_capability
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ROOT = Path(__file__).resolve().parents[2]


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "example:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake"},
        }
    )


async def test_example_installs_and_reads_bounded_state() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "resource:compute/vm/example",
        {"kind": "compute.vm", "location": "krc", "internal": "hidden"},
    )
    tools = FileSystemToolRegistry(_ROOT / "rule-catalog").artifacts()
    container = install_state_query_capability(
        default_container(_config()),
        store=store,
        reasoning_tools=tools,
    )
    resolved = container.capability_runtime.resolve("fork.state.query")
    artifact = next(tool for tool in tools if tool.id == "state.query")

    result = await resolved.provider.call(  # type: ignore[union-attr]
        artifact=artifact,
        arguments={
            "target_resource_ref": "resource:compute/vm/example",
            "fields": ["kind", "location"],
        },
    )

    assert result == {
        "target_resource_ref": "resource:compute/vm/example",
        "available": True,
        "state": {"kind": "compute.vm", "location": "krc"},
    }
