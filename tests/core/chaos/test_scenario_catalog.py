"""Tests for the chaos-scenario catalog loader."""

from __future__ import annotations

import pathlib
from textwrap import dedent

import pytest

from fdai.core.chaos.scenario_catalog import (
    CatalogEntry,
    ScenarioCatalogError,
    load_all,
    load_promoted,
)


def _write(root: pathlib.Path, sub: str, name: str, body: str) -> pathlib.Path:
    d = root / sub
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.yaml"
    p.write_text(dedent(body).lstrip())
    return p


def _valid_body(scenario_id: str = "chaos.aks.pod-kill-mild") -> str:
    return f"""
    id: {scenario_id}
    version: 1
    provenance:
      source: chaos-mesh
      synthesis_method: collected
    category: compute
    target_type: pod
    fault_family: stop
    intensity: mild
    duration_seconds: 360
    expected_signal: pod_restart
    injector: chaos-mesh:PodChaos
    blast_radius_cap: 1
    rollback_note: ReplicaSet reschedules the killed pod.
    gates:
      shadow_status: passed
      enforce_status: passed
    requires_hardware: false
    """


def _stage_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """Copy the real schema next to a scratch catalog root under tmp."""
    scenarios_root = tmp_path / "chaos-scenarios"
    schema_dir = scenarios_root / "schema"
    schema_dir.mkdir(parents=True)
    real_schema = (
        pathlib.Path(__file__).resolve().parents[3]
        / "rule-catalog"
        / "chaos-scenarios"
        / "schema"
        / "chaos-scenario.schema.json"
    )
    (schema_dir / "chaos-scenario.schema.json").write_bytes(real_schema.read_bytes())
    return scenarios_root


def test_load_promoted_returns_valid_entries(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(root, "promoted", "s1", _valid_body())
    entries = load_promoted(root=root)
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, CatalogEntry)
    assert e.id == "chaos.aks.pod-kill-mild"
    assert e.expected_signal == "pod_restart"
    assert e.category == "compute"
    assert e.gpu_domain is None
    assert e.requires_hardware is False


def test_load_promoted_skips_collected(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(root, "promoted", "p", _valid_body("chaos.aks.pod-kill-a"))
    _write(root, "collected/chaos-mesh", "c", _valid_body("chaos.aks.pod-kill-b"))
    ids = {e.id for e in load_promoted(root=root)}
    assert ids == {"chaos.aks.pod-kill-a"}


def test_load_all_includes_collected(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(root, "promoted", "p", _valid_body("chaos.aks.pod-kill-a"))
    _write(root, "collected/chaos-mesh", "c", _valid_body("chaos.aks.pod-kill-b"))
    ids = {e.id for e in load_all(root=root)}
    assert ids == {"chaos.aks.pod-kill-a", "chaos.aks.pod-kill-b"}


def test_schema_violation_is_hard_error(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(
        root,
        "promoted",
        "bad",
        """
        id: not-a-namespaced-id
        version: 1
        provenance:
          source: chaos-mesh
          synthesis_method: collected
        category: compute
        target_type: pod
        fault_family: stop
        intensity: mild
        duration_seconds: 360
        expected_signal: pod_restart
        injector: chaos-mesh:PodChaos
        blast_radius_cap: 1
        rollback_note: rn
        gates:
          shadow_status: passed
          enforce_status: passed
        requires_hardware: false
        """,
    )
    with pytest.raises(ScenarioCatalogError, match="schema validation failed"):
        load_promoted(root=root)


def test_unknown_signal_is_rejected(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(
        root,
        "promoted",
        "sig",
        _valid_body().replace("expected_signal: pod_restart", "expected_signal: no_such_signal"),
    )
    with pytest.raises(ScenarioCatalogError, match="not registered"):
        load_promoted(root=root)


def test_needs_injector_rejected_in_promoted(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(
        root,
        "promoted",
        "ni",
        _valid_body().replace("injector: chaos-mesh:PodChaos", "injector: needs-injector"),
    )
    with pytest.raises(ScenarioCatalogError, match="needs-injector"):
        load_promoted(root=root)


def test_cross_csp_reference_rejected_in_promoted(tmp_path: pathlib.Path) -> None:
    """`cross-csp-reference` is also a non-executable marker; the loader
    must reject it in promoted/ so borrowed catalog data cannot pretend
    to be a shippable scenario."""
    root = _stage_root(tmp_path)
    _write(
        root,
        "promoted",
        "xc",
        _valid_body().replace("injector: chaos-mesh:PodChaos", "injector: cross-csp-reference"),
    )
    with pytest.raises(ScenarioCatalogError, match="cross-csp-reference"):
        load_promoted(root=root)


def test_needs_injector_allowed_in_collected(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(
        root,
        "collected/synthesized",
        "ni",
        _valid_body().replace("injector: chaos-mesh:PodChaos", "injector: needs-injector"),
    )
    entries = load_all(root=root)
    assert len(entries) == 1
    assert entries[0].spec["injector"] == "needs-injector"


def test_cross_csp_reference_allowed_in_collected(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(
        root,
        "collected/aws-fis",
        "xc",
        _valid_body().replace("injector: chaos-mesh:PodChaos", "injector: cross-csp-reference"),
    )
    entries = load_all(root=root)
    assert len(entries) == 1
    assert entries[0].spec["injector"] == "cross-csp-reference"


def test_duplicate_id_is_hard_error(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(root, "promoted", "a", _valid_body("chaos.aks.pod-kill-a"))
    _write(root, "promoted", "b", _valid_body("chaos.aks.pod-kill-a"))
    with pytest.raises(ScenarioCatalogError, match="duplicate scenario id"):
        load_promoted(root=root)


def test_fork_custom_augments_promoted(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(root, "promoted", "p", _valid_body("chaos.aks.pod-kill-a"))
    # Fork custom lives OUTSIDE root, as a sibling directory.
    custom_dir = root.parent / "chaos-scenarios-custom"
    custom_dir.mkdir()
    (custom_dir / "b.yaml").write_text(dedent(_valid_body("chaos.aks.pod-kill-b")).lstrip())
    ids = {e.id for e in load_promoted(root=root)}
    assert ids == {"chaos.aks.pod-kill-a", "chaos.aks.pod-kill-b"}


def test_fork_overrides_merge_params(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    # Write a base scenario with a params block already present.
    base_body = dedent(_valid_body("chaos.aks.pod-kill-a")).lstrip().rstrip() + (
        "\nparams:\n  grace_period_seconds: '0'\n"
    )
    (root / "promoted").mkdir(parents=True, exist_ok=True)
    (root / "promoted" / "p.yaml").write_text(base_body)
    overrides_dir = root.parent / "chaos-scenarios-overrides"
    overrides_dir.mkdir()
    (overrides_dir / "o.yaml").write_text(
        dedent(
            """
            id: chaos.aks.pod-kill-a
            duration_seconds: 720
            params:
              grace_period_seconds: '5'
              new_key: hi
            """
        ).lstrip()
    )
    entries = load_promoted(root=root)
    assert len(entries) == 1
    e = entries[0]
    assert e.spec["duration_seconds"] == 720
    assert e.spec["params"] == {"grace_period_seconds": "5", "new_key": "hi"}


def test_override_without_matching_base_is_ignored(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    _write(root, "promoted", "p", _valid_body("chaos.aks.pod-kill-a"))
    overrides_dir = root.parent / "chaos-scenarios-overrides"
    overrides_dir.mkdir()
    (overrides_dir / "orphan.yaml").write_text(
        "id: chaos.does.not.exist\nduration_seconds: 999\n"
    )
    entries = load_promoted(root=root)
    assert len(entries) == 1
    assert entries[0].spec["duration_seconds"] == 360


def test_empty_root_returns_empty(tmp_path: pathlib.Path) -> None:
    root = _stage_root(tmp_path)
    assert load_promoted(root=root) == []
    assert load_all(root=root) == []
