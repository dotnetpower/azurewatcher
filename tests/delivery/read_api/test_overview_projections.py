from __future__ import annotations

from pathlib import Path

from fdai.core.verticals.cost_governance.finops import FinOpsActionKind
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.audit_finops import AuditFinOpsPanel
from fdai.delivery.read_api.routes.audit_measurement_summary import (
    AuditAutonomyMeasurementPanel,
)
from fdai.delivery.read_api.routes.persisted_promotion_gates import (
    PersistedPromotionGatesPanel,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[3]


async def test_empty_audit_keeps_unobserved_autonomy_metrics_unavailable() -> None:
    payload = await AuditAutonomyMeasurementPanel(InMemoryConsoleReadModel()).render(params={})

    assert payload["synthetic"] is False
    assert payload["sample_size"] == 0
    assert payload["success"]["auto_resolution_rate"]["value"] is None
    assert payload["success"]["auto_resolution_rate"]["baseline"] is None
    assert payload["success"]["mttr_seconds"]["value"] is None
    assert payload["verticals"][0]["events"] == 0


async def test_audit_overview_projects_only_recorded_measurements() -> None:
    model = InMemoryConsoleReadModel()
    action_kind = next(iter(FinOpsActionKind)).value
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "action_kind": action_kind,
            "mode": "shadow",
            "outcome": "resolved",
            "tier": "t0",
            "estimated_savings": 12.5,
            "measurement": {"mttr_seconds": 120.0},
            "baseline": {"mttr_seconds": 300.0},
        }
    )

    autonomy = await AuditAutonomyMeasurementPanel(model).render(params={})
    finops = await AuditFinOpsPanel(model).render(params={})

    assert autonomy["success"]["auto_resolution_rate"]["value"] == 1.0
    assert autonomy["success"]["auto_resolution_rate"]["baseline"] is None
    assert autonomy["success"]["mttr_seconds"] == {
        "value": 120.0,
        "baseline": 300.0,
        "direction": "lower",
    }
    assert finops["estimated_monthly_savings"] == 12.5
    assert finops["source"] == "postgres-audit"
    assert finops["durable"] is True


async def test_persisted_promotion_panel_holds_without_durable_evidence() -> None:
    action_type = load_action_type_catalog(
        REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=None,
    )[0]
    store = InMemoryStateStore()
    panel = PersistedPromotionGatesPanel(action_types=(action_type,), store=store)

    missing = await panel.render(params={})
    assert missing["ready_count"] == 0
    assert missing["rows"][0]["gaps"] == ["no_persisted_promotion_evidence"]

    gate = action_type.promotion_gate
    await store.write_state(
        f"action_promotion:{action_type.name}",
        {
            "metrics": {
                "shadow_days": gate.min_shadow_days,
                "samples": gate.min_samples,
                "accuracy": gate.min_accuracy,
                "policy_escapes": gate.max_policy_escapes,
            }
        },
    )
    ready = await panel.render(params={})
    assert ready["ready_count"] == 1
    assert ready["rows"][0]["ready"] is True
