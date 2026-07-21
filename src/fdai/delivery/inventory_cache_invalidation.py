"""Local inventory-cache invalidation after durable change projection."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

InventoryDeltaProjector = Callable[[Mapping[str, Any]], Awaitable[Any]]


class InvalidatingInventoryDeltaProjector:
    """Advance a local invalidation marker after the durable projector succeeds."""

    def __init__(self, *, inner: InventoryDeltaProjector, marker_path: Path) -> None:
        self._inner = inner
        self._marker_path = marker_path

    async def __call__(self, payload: Mapping[str, Any]) -> Any:
        result = await self._inner(payload)
        await asyncio.to_thread(_advance_marker, self._marker_path)
        return result


def _advance_marker(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write("inventory.resource_changed\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["InvalidatingInventoryDeltaProjector"]
