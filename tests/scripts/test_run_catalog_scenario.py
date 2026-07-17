"""Regression tests for scripts/run-catalog-scenario.py."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from fdai.delivery.chaos.factories import default_factory

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run-catalog-scenario.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_catalog_scenario", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dry_run_builds_every_executable_catalog_entry(capsys: object) -> None:
    module = _load_script()

    result = asyncio.run(module._dry_run(default_factory()))

    assert result == 0
    output = capsys.readouterr().out
    assert "dry-run: 92/92 entries dispatchable" in output
