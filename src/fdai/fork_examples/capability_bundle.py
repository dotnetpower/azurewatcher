"""Copy-ready downstream capability bundle using the state-query tool."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.composition import Container, install_capability_bundle
from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.tools import ToolArtifact
from fdai.shared.providers.state_store import StateStore

_PROVIDER_ID = "StateStoreQueryProvider"
_TOOL_ID = "state.query"


@dataclass(frozen=True, slots=True)
class ForkStateQueryProvider:
    """Read bounded state projections without exposing write access."""

    store: StateStore

    async def call(
        self,
        *,
        artifact: ToolArtifact,
        arguments: Mapping[str, Any],
    ) -> object:
        if artifact.id != _TOOL_ID:
            raise ValueError(f"unsupported tool id {artifact.id!r}")
        target_ref = str(arguments["target_resource_ref"])
        state = await self.store.read_state(target_ref)
        if state is None:
            return {"target_resource_ref": target_ref, "available": False}

        requested = arguments.get("fields")
        if isinstance(requested, list):
            fields = tuple(str(field) for field in requested)
            projected = {field: state[field] for field in fields if field in state}
        else:
            projected = dict(state)
        return {
            "target_resource_ref": target_ref,
            "available": True,
            "state": projected,
        }


def build_state_query_bundle(store: StateStore) -> CapabilityBundle:
    """Build the fork-owned metadata, binding, and concrete provider."""

    return CapabilityBundle(
        capabilities=(
            Capability(
                capability_id="fork.state.query",
                name="Query tracked resource state",
                category=CapabilityCategory.INVESTIGATION,
                summary="Read a bounded projection from the tracked state store.",
                side_effect_class=SideEffectClass.READ,
                required_role="reader",
                tags=("fork", "state", "read-only"),
            ),
        ),
        bindings=(
            CapabilityBinding(
                capability_id="fork.state.query",
                kind=CapabilityBindingKind.REASONING_TOOL,
                target_ref=_TOOL_ID,
                provider_id=_PROVIDER_ID,
            ),
        ),
        tool_providers={_PROVIDER_ID: ForkStateQueryProvider(store)},
    )


def install_state_query_capability(
    container: Container,
    *,
    store: StateStore,
    reasoning_tools: Sequence[ToolArtifact],
) -> Container:
    """Install the example without editing upstream core or composition."""

    return install_capability_bundle(
        container,
        build_state_query_bundle(store),
        reasoning_tools=tuple(reasoning_tools),
    )


__all__ = [
    "ForkStateQueryProvider",
    "build_state_query_bundle",
    "install_state_query_capability",
]
