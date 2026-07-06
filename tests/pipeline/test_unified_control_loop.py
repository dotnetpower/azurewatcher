"""Unified P1 control-loop coverage across all three verticals.

Proves the phase-3 § Unified Control Loop invariant *for the P1 slice*:
a single :class:`ControlLoop` instance routes Change Safety, Resilience,
and Cost Governance events end-to-end without vertical-specific
branching. P1 does not wire the risk-gate / T1 / T2 into the loop, so
the assertion is scoped to what P1 actually delivers:

- **Same loop instance handles all three verticals.** One
  :class:`ControlLoop` with the shipped catalog processes events from
  every domain; each domain reaches ``EXECUTED`` on a matching rule.
- **Shadow-mode invariant** holds cross-vertical — every published PR
  carries the ``shadow`` label, every executed action reports
  :class:`Mode.SHADOW`.
- **Vertical isolation** — an event routed by resource_type never fires
  a rule from a different vertical (Change rule never fires on FinOps
  event, etc.). This proves resource_type routing is the right isolation
  boundary; verticals do not need per-loop instances.
- **Idempotency across verticals** — replaying a burst of mixed-domain
  events under the same idempotency keys deduplicates deterministically.

The full P3 unified loop (risk-gate precedence, cross-vertical lock,
per-vertical Managed Identity) is beyond the P1 loop's contract; that
gets tested in P3 once the risk-gate is wired.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from aiopspilot.core.control_loop import (
    ControlLoop,
    ControlLoopOutcome,
    ControlLoopResult,
)
from aiopspilot.core.event_ingest import EventIngest
from aiopspilot.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from aiopspilot.core.executor.action_builder import ActionBuilder
from aiopspilot.core.tiers.t0_deterministic import (
    OpaRegoEvaluator,
    RuleIndex,
    T0Engine,
)
from aiopspilot.core.trust_router import TrustRouter
from aiopspilot.rule_catalog.schema.action_type import load_action_type_catalog
from aiopspilot.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from aiopspilot.rule_catalog.schema.rule import load_rule_catalog
from aiopspilot.shared.contracts.models import Mode
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry
from aiopspilot.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from aiopspilot.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

_OPA_PRESENT = shutil.which("opa") is not None
requires_opa = pytest.mark.skipif(
    not _OPA_PRESENT,
    reason="opa binary not found on PATH; skip unified-loop e2e",
)


@pytest.fixture(scope="module")
def shipped_catalog() -> tuple[Any, Any]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    return rules, action_types


def _make_loop(
    shipped_catalog: tuple[Any, Any],
) -> tuple[ControlLoop, RecordingRemediationPrPublisher, InMemoryStateStore]:
    rules, action_types = shipped_catalog
    index = RuleIndex.build(rules)
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    publisher = RecordingRemediationPrPublisher()
    audit = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    action_builder = ActionBuilder(action_types_by_name={a.name: a for a in action_types})
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=evaluator),
        action_builder=action_builder,
        executor=executor,
        audit_store=audit,
        rules_by_id={r.id: r for r in rules},
    )
    return loop, publisher, audit


def _event(
    *,
    idempotency_key: str,
    resource_type: str,
    resource_id: str,
    props: dict[str, Any],
    event_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "idempotency_key": idempotency_key,
        "source": "example_activity_log",
        "event_type": "config_changed",
        "detected_at": "2026-07-06T08:00:00Z",
        "ingested_at": "2026-07-06T08:00:01Z",
        "mode": "shadow",
        "payload": {
            "resource": {
                "resource_id": resource_id,
                "type": resource_type,
                "props": props,
            }
        },
    }


# ---------------------------------------------------------------------------
# Per-vertical trigger events — each fires a shipped rule of its family
# ---------------------------------------------------------------------------

_VERTICAL_TRIGGERS: dict[str, dict[str, Any]] = {
    "change": {
        "idempotency_key": "unified-change-1",
        "resource_type": "object-storage",
        "resource_id": "stg-open",
        "props": {"public_access": "enabled", "tags": {"owner": "team-a"}},
        "event_id": "00000000-0000-0000-0000-000000000201",
        "expected_rule_family": "object-storage.public-access.deny",
    },
    "resilience": {
        "idempotency_key": "unified-resilience-1",
        "resource_type": "sql-database",
        "resource_id": "sqldb-1",
        "props": {
            "tde_enabled": False,
        },
        "event_id": "00000000-0000-0000-0000-000000000202",
        "expected_rule_family": "sql-database.tde-required",
    },
    "finops": {
        "idempotency_key": "unified-finops-1",
        "resource_type": "network.public-ip",
        "resource_id": "pip-orphan-1",
        "props": {"associated_resource_id": ""},
        "event_id": "00000000-0000-0000-0000-000000000203",
        "expected_rule_family": "network.public-ip.orphan",
    },
}


@requires_opa
@pytest.mark.asyncio
async def test_single_loop_handles_all_three_verticals(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """One :class:`ControlLoop` instance routes all three verticals.

    Proves the shape of the P3 unified-loop contract at the P1 level:
    the loop is domain-agnostic; verticals are configuration, not code
    branches inside the loop.
    """
    loop, publisher, audit = _make_loop(shipped_catalog)
    domain_outcomes: dict[str, ControlLoopResult] = {}

    for domain, spec in _VERTICAL_TRIGGERS.items():
        payload = dict(spec)
        payload.pop("expected_rule_family", None)
        result = await loop.process(_event(**payload))
        domain_outcomes[domain] = result

    for domain, result in domain_outcomes.items():
        expected_rule = _VERTICAL_TRIGGERS[domain]["expected_rule_family"]
        assert result.outcome is ControlLoopOutcome.EXECUTED, (
            f"{domain} vertical: expected EXECUTED, got {result.outcome} (reason={result.reason})"
        )
        assert result.tier == "t0"
        assert result.decision == "auto"
        assert expected_rule in result.citing_rule_ids, (
            f"{domain} vertical: expected shipped rule {expected_rule!r} "
            f"in citing_rule_ids={result.citing_rule_ids}"
        )
        # Shadow-mode invariant per execution.
        for execution in result.execution_results:
            assert execution.mode is Mode.SHADOW

    # Shadow-mode invariant on the publisher — every PR carries the
    # shadow label, no vertical is bypassing it.
    assert publisher.records, "no PRs published for any vertical"
    for pr in publisher.records:
        assert pr.mode is Mode.SHADOW
        assert "shadow" in pr.labels

    # Every vertical wrote at least one audit entry.
    audit_entries = list(audit.audit_entries)
    assert len(audit_entries) >= len(_VERTICAL_TRIGGERS)


@requires_opa
@pytest.mark.asyncio
async def test_vertical_isolation_no_cross_family_matches(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """A vertical's event MUST cite only rules that target its resource_type.

    Guarantees resource_type is the correct isolation boundary: a Change
    Safety event never accidentally fires a FinOps rule, and so on.
    """
    loop, _publisher, _audit = _make_loop(shipped_catalog)
    rules, _action_types = shipped_catalog
    rules_by_id = {r.id: r for r in rules}

    for domain, spec in _VERTICAL_TRIGGERS.items():
        payload = dict(spec)
        payload.pop("expected_rule_family", None)
        # Give each event a unique idempotency_key so the loop doesn't
        # dedupe against the previous test's audit.
        payload["idempotency_key"] = f"isolation-{domain}"
        result = await loop.process(_event(**payload))
        assert result.outcome is ControlLoopOutcome.EXECUTED

        expected_type = spec["resource_type"]
        for cited_id in result.citing_rule_ids:
            cited_rule = rules_by_id[cited_id]
            assert cited_rule.resource_type == expected_type, (
                f"{domain} vertical fired {cited_id!r} whose resource_type "
                f"{cited_rule.resource_type!r} != event resource_type "
                f"{expected_type!r} — cross-vertical leak"
            )


@requires_opa
@pytest.mark.asyncio
async def test_idempotent_replay_across_verticals(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """Re-delivering the same event batch produces zero new PRs.

    A single instance of the loop MUST dedupe by ``idempotency_key``
    regardless of which vertical the event belongs to.
    """
    loop, publisher, _audit = _make_loop(shipped_catalog)

    def _events() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in _VERTICAL_TRIGGERS.values():
            payload = dict(spec)
            payload.pop("expected_rule_family", None)
            out.append(_event(**payload))
        return out

    # First delivery — every event executes.
    first_results = [await loop.process(event) for event in _events()]
    for result in first_results:
        assert result.outcome is ControlLoopOutcome.EXECUTED
    pr_count_first = len(publisher.records)
    assert pr_count_first >= len(_VERTICAL_TRIGGERS)

    # Second delivery — every event dedupes; PR count MUST NOT grow.
    second_results = [await loop.process(event) for event in _events()]
    for result in second_results:
        assert result.outcome is ControlLoopOutcome.DEDUPED
    assert len(publisher.records) == pr_count_first, (
        "re-delivered events opened new PRs — dedupe regressed"
    )
