"""ActionBuilder - safety-invariant mapping from Finding to Action."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from fdai.core.executor.action_builder import (
    ActionBuilder,
    ActionBuildError,
)
from fdai.core.tiers.t0_deterministic.models import Finding
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import (
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    Event,
    Mode,
    Operation,
    Provenance,
    Redistribution,
    Remediation,
    RollbackKind,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


def _shipped_action_types() -> dict[str, object]:
    catalog = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=PackageResourceSchemaRegistry()
    )
    return {a.name: a for a in catalog}


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "e1",
            "source": "src",
            "event_type": "change_detected",
            "detected_at": "2026-07-05T08:00:00Z",
            "ingested_at": "2026-07-05T08:00:01Z",
            "mode": "shadow",
        }
    )


def _rule(rule_id: str, remediates: str, parameters: dict | None = None) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        resource_type="object-storage",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates=remediates,
        parameters=parameters or {},
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _finding(rule: Rule, *, resource_id: str = "rid-1") -> Finding:
    return Finding(
        finding_id=f"{rule.id}::{rule.version}::{resource_id}::sig-1",
        rule_id=rule.id,
        rule_version=rule.version,
        resource_id=resource_id,
        signal_id="sig-1",
        severity=rule.severity,
        context={"deny_reason": "example"},
    )


# ---------------------------------------------------------------------------
# Happy path - every shipped ActionType produces a valid Action
# ---------------------------------------------------------------------------


def test_builds_valid_action_for_tag_add_type() -> None:
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    rule = _rule("r1", "remediate.tag-add", parameters={"tag_name": "owner"})
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert action.action_type == "remediate.tag-add"
    assert action.operation is Operation.TAG
    assert action.target_resource_ref == "rid-1"
    assert action.mode is Mode.SHADOW
    assert action.citing_rules == ["r1"]
    assert action.rollback_ref.kind is RollbackKind.PR_REVERT
    assert action.blast_radius.scope is BlastRadiusScope.RESOURCE


def test_deterministic_action_id_across_replays() -> None:
    types = _shipped_action_types()
    rule = _rule("r1", "remediate.tag-add")
    b1 = ActionBuilder(action_types_by_name=types)  # type: ignore[arg-type]
    b2 = ActionBuilder(action_types_by_name=types)  # type: ignore[arg-type]
    a1 = b1.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    a2 = b2.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert a1.action_id == a2.action_id
    assert isinstance(a1.action_id, UUID)


def test_idempotency_key_derives_from_event_rule_resource() -> None:
    rule = _rule("r1", "remediate.tag-add")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(
        event=_event(), finding=_finding(rule, resource_id="stg1"), rule=rule
    )
    assert action.idempotency_key == "e1::r1::stg1"


def test_finding_context_stays_out_of_action_params() -> None:
    """Finding context (e.g. ``deny_reason``) is audit-log data, not a
    template placeholder - the ActionBuilder MUST NOT inject it into
    ``Action.params`` or the renderer's scalar-only rule breaks."""
    rule = _rule("r1", "remediate.tag-add", parameters={"tag_name": "owner"})
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert action.params == {"tag_name": "owner"}
    assert "_finding_context" not in action.params


def test_unknown_remediates_raises_action_build_error() -> None:
    rule = _rule("r1", "remediate.does-not-exist")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    with pytest.raises(ActionBuildError, match="does-not-exist"):
        builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)


# ---------------------------------------------------------------------------
# Blast-radius mapping across the two computation modes
# ---------------------------------------------------------------------------


def test_static_bucket_blast_radius_maps_to_action_shape() -> None:
    """`remediate.tag-add` uses `static_enum` with `static_bucket: resource`."""
    rule = _rule("r1", "remediate.tag-add")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert action.blast_radius.scope is BlastRadiusScope.RESOURCE
    assert action.blast_radius.count == 1


def test_graph_derived_blast_radius_carries_max_count() -> None:
    """`remediate.disable-public-access` uses `graph_derived` with
    `max_affected_resources: 5`. The action should carry that as its
    cap so the executor's blast-radius check is exercised."""
    rule = _rule("r1", "remediate.disable-public-access")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert action.blast_radius.count == 5


# ---------------------------------------------------------------------------
# Stop-condition derivation
# ---------------------------------------------------------------------------


def test_stop_condition_uses_first_action_type_stop_kind() -> None:
    rule = _rule("r1", "remediate.tag-add")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    # `remediate.tag-add`'s first stop_condition is
    # `kind: provider_api_error_streak`.
    assert action.stop_condition == "provider_api_error_streak"


def test_action_type_without_stop_conditions_raises(tmp_path: Path) -> None:
    """Defense-in-depth: the schema allows an empty stop_conditions list,
    but the builder refuses to synthesize a placeholder."""
    from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping

    raw = {
        "schema_version": "1.0.0",
        "name": "remediate.custom-empty",
        "version": "1.0.0",
        "operation": "tag",
        "interfaces": ["ControlPlane"],
        "rollback_contract": "pr_revert",
        "default_mode": "shadow",
        "promotion_gate": {
            "min_shadow_days": 1,
            "min_samples": 1,
            "min_accuracy": 0.9,
            "max_policy_escapes": 0,
        },
        # deliberately no stop_conditions
    }
    action_type = load_action_type_from_mapping(
        raw, schema_registry=PackageResourceSchemaRegistry()
    )
    rule = _rule("r1", "remediate.custom-empty")
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})
    with pytest.raises(ActionBuildError, match="stop_conditions"):
        builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
