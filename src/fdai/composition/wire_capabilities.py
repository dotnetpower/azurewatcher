"""Capability bundle composition helpers for downstream forks."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.capability_catalog import (
    CapabilityBundle,
    CapabilityRuntime,
    build_capability_references,
    default_capability_catalog,
)
from fdai.core.tools.types import ToolArtifact
from fdai.shared.contracts.models import OntologyActionType, Workflow

from ._helpers import Container


def default_capability_runtime() -> CapabilityRuntime:
    """Return the upstream discovery catalog with no executable bindings."""

    return CapabilityRuntime(catalog=default_capability_catalog())


def install_capability_bundle(
    container: Container,
    bundle: CapabilityBundle,
    *,
    reasoning_tools: tuple[ToolArtifact, ...] = (),
    action_types: tuple[OntologyActionType, ...] = (),
    workflows: tuple[Workflow, ...] = (),
) -> Container:
    """Validate and install one downstream capability bundle.

    The returned container is new and the input remains unchanged. ActionType
    and Workflow bindings are references only; invocation still goes through
    the control loop, risk gate, and existing executor paths.
    """

    runtime = container.capability_runtime.install(
        bundle,
        references=build_capability_references(
            reasoning_tools=reasoning_tools,
            action_types=action_types,
            workflows=workflows,
        ),
    )
    return replace(container, capability_runtime=runtime)


__all__ = ["default_capability_runtime", "install_capability_bundle"]
