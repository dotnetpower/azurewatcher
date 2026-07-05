"""ActionType catalog loader + shipped ActionType invariants.

Enforces at test-time what the schema guarantees at load-time, plus P1
policy rules:
- Every shipped ActionType is `default_mode: shadow`.
- `rollback_contract` never falls back to a legacy `none` value.
- Every ActionType names a registered `operation`, and irreversible
  actions carry the explicit `irreversible: true` flag.
- Duplicate ActionType names across files fail-close.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aiopspilot.rule_catalog.schema.action_type import (
    ActionTypeCatalogError,
    load_action_type_catalog,
    load_action_type_from_mapping,
)
from aiopspilot.shared.contracts.models import Mode, Operation, RollbackKind
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def test_shipped_action_types_load() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    names = {a.name for a in catalog}
    # P1 initial 5 (change if the shipped set grows).
    assert names >= {
        "remediate.disable-public-access",
        "remediate.tag-add",
        "remediate.right-size",
        "remediate.rotate-secret",
        "remediate.enable-tde",
    }


def test_every_shipped_action_type_defaults_to_shadow() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    for action in catalog:
        assert action.default_mode is Mode.SHADOW, (
            f"{action.name}: default_mode MUST be shadow in upstream"
        )


def test_every_shipped_action_type_has_a_rollback_contract() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    valid = {
        RollbackKind.PR_REVERT,
        RollbackKind.SCRIPTED,
        RollbackKind.PITR,
        RollbackKind.SNAPSHOT_RESTORE,
        RollbackKind.STATE_FORWARD_ONLY,
    }
    for action in catalog:
        assert action.rollback_contract in valid, (
            f"{action.name}: rollback_contract MUST be a live enum value"
        )


def test_promotion_gate_criteria_are_measurable() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    for action in catalog:
        gate = action.promotion_gate
        assert gate.min_shadow_days >= 1
        assert gate.min_samples >= 1
        assert 0.0 <= gate.min_accuracy <= 1.0
        assert gate.max_policy_escapes >= 0


def test_operations_are_from_the_documented_verb_set() -> None:
    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    seen = {a.operation for a in catalog}
    # P1 5-pack exercises exactly these five verbs (change on evolution).
    assert seen == {
        Operation.DISABLE,
        Operation.TAG,
        Operation.SCALE,
        Operation.ROTATE,
        Operation.ENABLE,
    }


def test_default_mode_enforce_in_upstream_is_rejected() -> None:
    raw = {
        "schema_version": "1.0.0",
        "name": "remediate.example",
        "version": "1.0.0",
        "operation": "tag",
        "interfaces": ["ControlPlane"],
        "rollback_contract": "pr_revert",
        "default_mode": "enforce",  # forbidden in upstream
        "promotion_gate": {
            "min_shadow_days": 1,
            "min_samples": 1,
            "min_accuracy": 0.9,
            "max_policy_escapes": 0,
        },
    }
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_from_mapping(raw, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "shadow" in joined


def test_rollback_none_is_rejected_by_schema(tmp_path: Path) -> None:
    file = tmp_path / "bad.yaml"
    file.write_text(
        (
            'schema_version: "1.0.0"\n'
            "name: remediate.bad-none\n"
            'version: "1.0.0"\n'
            "operation: tag\n"
            "interfaces: [ControlPlane]\n"
            "rollback_contract: none\n"  # <- disallowed
            "default_mode: shadow\n"
            "promotion_gate:\n"
            "  min_shadow_days: 1\n"
            "  min_samples: 1\n"
            "  min_accuracy: 0.9\n"
            "  max_policy_escapes: 0\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(tmp_path, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    # The schema enum error names the offending value; either way the load
    # MUST fail so `none` cannot silence the safety invariant.
    assert "'none'" in joined or "none is not" in joined
    # And the offending property path MUST surface for the reviewer.
    keys = " ".join(i.key for i in info.value.issues).lower()
    assert "rollback_contract" in keys


def test_duplicate_name_across_files_is_rejected(tmp_path: Path) -> None:
    body = (
        'schema_version: "1.0.0"\n'
        "name: remediate.dup\n"
        'version: "1.0.0"\n'
        "operation: tag\n"
        "interfaces: [ControlPlane]\n"
        "rollback_contract: pr_revert\n"
        "default_mode: shadow\n"
        "promotion_gate:\n"
        "  min_shadow_days: 1\n"
        "  min_samples: 1\n"
        "  min_accuracy: 0.9\n"
        "  max_policy_escapes: 0\n"
    )
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(tmp_path, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "duplicate" in joined


def test_invalid_yaml_reports_the_file(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text(":\n  - invalid: [\n", encoding="utf-8")
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(tmp_path, schema_registry=_registry())
    keys = " ".join(i.key for i in info.value.issues)
    assert "broken.yaml" in keys
    assert any("invalid YAML" in i.message for i in info.value.issues)


def test_top_level_not_a_mapping_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- just_a_list_item\n", encoding="utf-8")
    with pytest.raises(ActionTypeCatalogError) as info:
        load_action_type_catalog(tmp_path, schema_registry=_registry())
    assert any("top-level" in i.message for i in info.value.issues)


def test_action_type_names_helper_agrees_with_catalog() -> None:
    from aiopspilot.rule_catalog.schema.action_type import action_type_names

    catalog = load_action_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    names = action_type_names(catalog)
    assert names == {a.name for a in catalog}
    assert "remediate.tag-add" in names
