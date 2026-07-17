"""Deterministic Python method-stub generation from typed RPC discovery."""

from __future__ import annotations

import keyword
import re
from collections.abc import Mapping, Sequence

_METHOD = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")


class RpcCodegenError(ValueError):
    """RPC discovery cannot produce an unambiguous safe client stub."""


def generate_python_client_stub(descriptors: Sequence[Mapping[str, object]]) -> str:
    """Render deterministic methods that delegate to the strict generic client."""
    methods: list[tuple[str, str, bool]] = []
    names: set[str] = set()
    for descriptor in descriptors:
        rpc_name = descriptor.get("name")
        side_effect = descriptor.get("side_effect")
        if not isinstance(rpc_name, str) or _METHOD.fullmatch(rpc_name) is None:
            raise RpcCodegenError("RPC discovery contains an invalid method name")
        if not isinstance(side_effect, bool):
            raise RpcCodegenError("RPC discovery contains an invalid side_effect flag")
        python_name = _python_name(rpc_name)
        if python_name in names:
            raise RpcCodegenError("RPC method names collide after Python normalization")
        names.add(python_name)
        methods.append((python_name, rpc_name, side_effect))
    lines = [
        '"""Generated FDAI RPC client methods. Do not edit."""',
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping",
        "from typing import Any",
        "",
        "from fdai.core.rpc import RpcRequest, RpcResponse",
        "from fdai.delivery.rpc import RpcHttpClient",
        "",
        "",
        "class GeneratedRpcMethods:",
        "    def __init__(self, client: RpcHttpClient) -> None:",
        "        self._client = client",
    ]
    for python_name, rpc_name, side_effect in sorted(methods):
        lines.extend(_method_lines(python_name, rpc_name, side_effect))
    if not methods:
        lines.extend(("", "    pass"))
    lines.append("")
    return "\n".join(lines)


def _method_lines(python_name: str, rpc_name: str, side_effect: bool) -> tuple[str, ...]:
    key_argument = ", idempotency_key: str" if side_effect else ""
    key_value = "idempotency_key" if side_effect else "None"
    return (
        "",
        f"    async def {python_name}(",
        f"        self, request_id: str, params: Mapping[str, Any]{key_argument}",
        "    ) -> RpcResponse:",
        "        return await self._client.invoke(",
        "            RpcRequest(",
        "                request_id=request_id,",
        f'                method="{rpc_name}",',
        "                params=params,",
        f"                idempotency_key={key_value},",
        "            )",
        "        )",
    )


def _python_name(rpc_name: str) -> str:
    value = re.sub(r"[.-]+", "_", rpc_name)
    if not value.isidentifier() or keyword.iskeyword(value):
        raise RpcCodegenError("RPC method name cannot be represented safely in Python")
    return value


__all__ = ["RpcCodegenError", "generate_python_client_stub"]
