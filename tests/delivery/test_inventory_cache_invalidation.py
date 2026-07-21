from __future__ import annotations

import os
from pathlib import Path

import pytest

from fdai.delivery.inventory_cache_invalidation import InvalidatingInventoryDeltaProjector


async def test_advances_marker_only_after_durable_projection_succeeds(tmp_path: Path) -> None:
    marker = tmp_path / "invalidated"

    async def project(payload: object) -> str:
        assert payload == {"inventory_change": {"kind": "upsert"}}
        return "applied"

    projector = InvalidatingInventoryDeltaProjector(inner=project, marker_path=marker)
    assert await projector({"inventory_change": {"kind": "upsert"}}) == "applied"
    assert marker.read_text(encoding="ascii") == "inventory.resource_changed\n"
    assert os.stat(marker).st_mode & 0o777 == 0o600


async def test_does_not_advance_marker_when_projection_fails(tmp_path: Path) -> None:
    marker = tmp_path / "invalidated"

    async def fail(payload: object) -> None:
        del payload
        raise RuntimeError("projection failed")

    projector = InvalidatingInventoryDeltaProjector(inner=fail, marker_path=marker)
    with pytest.raises(RuntimeError, match="projection failed"):
        await projector({})
    assert not marker.exists()
