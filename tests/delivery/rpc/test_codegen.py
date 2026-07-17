"""Deterministic typed RPC Python stub generation tests."""

from __future__ import annotations

import ast

import pytest

from fdai.delivery.rpc.codegen import RpcCodegenError, generate_python_client_stub


def test_codegen_is_deterministic_compilable_and_requires_side_effect_key() -> None:
    descriptors = (
        {"name": "workflow.request", "side_effect": True},
        {"name": "inventory.query", "side_effect": False},
    )

    first = generate_python_client_stub(descriptors)
    second = generate_python_client_stub(tuple(reversed(descriptors)))

    assert first == second
    ast.parse(first)
    assert "async def inventory_query(" in first
    assert "params: Mapping[str, Any]\n" in first
    assert "async def workflow_request(" in first
    assert "params: Mapping[str, Any], idempotency_key: str" in first
    assert 'method="workflow.request"' in first


def test_codegen_rejects_normalized_name_collision() -> None:
    with pytest.raises(RpcCodegenError, match="collide"):
        generate_python_client_stub(
            (
                {"name": "inventory.query", "side_effect": False},
                {"name": "inventory-query", "side_effect": False},
            )
        )


@pytest.mark.parametrize(
    "descriptor",
    (
        {"name": "BAD", "side_effect": False},
        {"name": "inventory.query", "side_effect": "false"},
    ),
)
def test_codegen_rejects_malformed_discovery(descriptor: dict[str, object]) -> None:
    with pytest.raises(RpcCodegenError):
        generate_python_client_stub((descriptor,))
