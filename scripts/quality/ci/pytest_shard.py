"""Select a deterministic file-level pytest shard for CI."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest


def _positive_int(name: str) -> int:
    raw = os.environ.get(name, "")
    try:
        value = int(raw)
    except ValueError as exc:
        raise pytest.UsageError(f"{name} must be an integer") from exc
    if value < 1:
        raise pytest.UsageError(f"{name} must be >= 1")
    return value


def _shard_for(path: Path, count: int) -> int:
    digest = hashlib.sha256(path.as_posix().encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    count = _positive_int("FDAI_PYTEST_SHARD_COUNT")
    index = _positive_int("FDAI_PYTEST_SHARD_INDEX") - 1
    if index >= count:
        raise pytest.UsageError("FDAI_PYTEST_SHARD_INDEX must not exceed shard count")

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    root = Path(str(config.rootpath))
    for item in items:
        path = Path(str(item.path)).resolve().relative_to(root.resolve())
        target = selected if _shard_for(path, count) == index else deselected
        target.append(item)
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
