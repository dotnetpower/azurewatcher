"""Tests for the manual-distillation CLI (smoke over a drop directory)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai.rule_catalog.pipeline.distill_cli import main


def test_cli_reports_held_and_writes_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "runbook.md").write_text("# Restart\nRestart the pod.\n", encoding="utf-8")
    snapshot = tmp_path / "snap.json"

    rc = main(["--drop-dir", str(drop), "--snapshot", str(snapshot), "--json"])
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    # Upstream defaults: the one manual routes to HIL as uncertain, none distilled.
    assert out["distilled_manuals"] == 0
    assert out["held"] == 1
    assert out["held_by_reason"] == {"classifier:uncertain": 1}

    written = json.loads(snapshot.read_text(encoding="utf-8"))
    assert written == {"drop://runbook.md": written["drop://runbook.md"]}
    assert written["drop://runbook.md"]  # non-empty sha


def test_cli_detects_deletion_from_prior_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    drop = tmp_path / "drop"
    drop.mkdir()
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"drop://gone.md": "oldsha"}), encoding="utf-8")

    rc = main(["--drop-dir", str(drop), "--snapshot", str(snapshot), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["retirements"] == ["drop://gone.md"]


def test_cli_missing_drop_dir_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--drop-dir", str(tmp_path / "nope")])
    assert rc == 64
    assert "drop directory not found" in capsys.readouterr().err


def test_cli_human_readable_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "a.md").write_text("hello", encoding="utf-8")
    rc = main(["--drop-dir", str(drop)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "distilled manuals" in text
    assert "held (HIL)" in text


def test_cli_rejects_malformed_snapshot(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    drop.mkdir()
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(ValueError, match="MUST be a JSON object"):
        main(["--drop-dir", str(drop), "--snapshot", str(snapshot)])
