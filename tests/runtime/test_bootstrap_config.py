from __future__ import annotations

import pytest

from fdai.runtime.bootstrap import _pantheon_start_enabled


def test_pantheon_starts_by_default() -> None:
    assert _pantheon_start_enabled({}) is True


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_pantheon_requires_explicit_disable(value: str) -> None:
    assert _pantheon_start_enabled({"FDAI_START_PANTHEON": value}) is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_pantheon_accepts_explicit_enable(value: str) -> None:
    assert _pantheon_start_enabled({"FDAI_START_PANTHEON": value}) is True
