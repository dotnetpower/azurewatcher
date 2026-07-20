from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/agent/design_context.py"
    spec = importlib.util.spec_from_file_location("design_context", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_required_context_composes_every_matching_route() -> None:
    module = _load_module()

    required = module.required_context(("src/fdai/delivery/read_api/dev/factory.py",))

    assert ".github/copilot-instructions.md" in required
    assert ".github/instructions/coding-conventions.instructions.md" in required
    assert ".github/instructions/app-shape.instructions.md" in required
    assert "docs/roadmap/deployment/dev-and-deploy-parity.md" in required
    assert "docs/roadmap/interfaces/operator-console.md" in required


def test_pre_tool_use_denies_edit_without_current_reads(
    monkeypatch: object, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_state_path", lambda payload: tmp_path / "receipt.json")
    payload = {
        "sessionId": "session-1",
        "toolName": "functions.apply_patch",
        "toolInput": {
            "input": (
                "*** Begin Patch\n"
                "*** Update File: /home/moonchoi/dev/fdai/src/fdai/core/risk_gate/gate.py\n"
                "*** End Patch"
            )
        },
    }

    result = module.enforce_edit(payload)

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "architecture.instructions.md" in result["systemMessage"]


def test_recorded_current_reads_allow_edit(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_module()
    state_path = tmp_path / "receipt.json"
    monkeypatch.setattr(module, "_state_path", lambda payload: state_path)
    target = "scripts/quality/architecture/check-design-routes.py"
    payload = {
        "session_id": "session-2",
        "tool_name": "apply_patch",
        "tool_input": {
            "input": f"*** Begin Patch\n*** Update File: {REPO_ROOT / target}\n*** End Patch"
        },
    }
    reads = {
        relative: module._sha256(REPO_ROOT / relative)
        for relative in module.required_context((target,))
    }
    state_path.write_text(json.dumps({"version": 1, "reads": reads}), encoding="utf-8")

    result = module.enforce_edit(payload)

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
