"""Wave W1.3 - HIL callback POST route (opt-in, HMAC-authenticated)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.routes.hil_callback import (
    HilCallbackConfig,
)
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    Mode,
    Operation,
    Provenance,
    Redistribution,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.providers.hil_registry import HilPendingItem
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.providers.testing.hil_registry import InMemoryHilApprovalRegistry

SECRET = "shared-secret-for-tests"


def _sign(secret: str, timestamp: str, body: bytes, *, approval_id: str) -> str:
    """Mirror :func:`fdai.delivery.read_api.routes.hil_callback._compute_hmac`.

    The URL ``approval_id`` MUST be part of the signed material so a
    captured message cannot be replayed against a different pending item
    (URL swap attack).
    """
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(timestamp.encode())
    mac.update(b".")
    mac.update(approval_id.encode())
    mac.update(b".")
    mac.update(body)
    return f"sha256={mac.hexdigest()}"


def _pending(
    *,
    approval_id: str = "appr-1",
    idempotency_key: str = "idem-1",
    submitter_oid: str = "user-submitter",
) -> HilPendingItem:
    return HilPendingItem(
        idempotency_key=idempotency_key,
        approval_id=approval_id,
        event_id="e-1",
        action_id="a-1",
        action_kind="remediate.tag-add",
        target_resource_ref="rg/vm-a",
        reason="short",
        submitter_oid=submitter_oid,
    )


def _build_app_with_callback(
    registry: InMemoryHilApprovalRegistry,
    *,
    coordinator: HilResumeCoordinator | None = None,
    now: datetime | None = None,
) -> object:
    del now  # composition-root wiring uses the default clock
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    return build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            hil_callback=HilCallbackConfig(secret=SECRET),
            hil_registry=registry,
            hil_coordinator=coordinator,
        ),
    )


# ---------------------------------------------------------------------------
# Config invariants
# ---------------------------------------------------------------------------


def test_config_secret_required() -> None:
    with pytest.raises(ValueError, match="secret"):
        HilCallbackConfig(secret="")


def test_config_max_skew_positive() -> None:
    with pytest.raises(ValueError, match="max_skew_seconds"):
        HilCallbackConfig(secret=SECRET, max_skew_seconds=0)


def test_config_max_body_positive() -> None:
    with pytest.raises(ValueError, match="max_body_bytes"):
        HilCallbackConfig(secret=SECRET, max_body_bytes=0)


def test_app_factory_fails_fast_when_callback_set_without_registry() -> None:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    with pytest.raises(ValueError, match="hil_registry"):
        build_app(
            authenticator=auth,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(
                hil_callback=HilCallbackConfig(secret=SECRET),
                hil_registry=None,
            ),
        )


def test_callback_route_only_registered_when_config_set() -> None:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app_without = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(),
    )
    paths = {r.path for r in app_without.routes if hasattr(r, "path")}
    assert not any("/hil/" in p and "/decision" in p for p in paths)

    registry = InMemoryHilApprovalRegistry()
    app_with = _build_app_with_callback(registry)
    paths_with = {r.path for r in app_with.routes if hasattr(r, "path")}
    assert "/hil/{approval_id}/decision" in paths_with


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_approve_records_decision_via_registry() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending(approval_id="appr-1", submitter_oid="user-sub")])
    app = _build_app_with_callback(registry)
    client = TestClient(app)

    body_payload = {
        "decision": "approve",
        "actor_oid": "user-approver",
        "justification": "reviewed and approved by on-call",
    }
    body = json.dumps(body_payload).encode()
    timestamp = datetime.now(UTC).isoformat()
    headers = {
        "x-fdai-timestamp": timestamp,
        "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id="appr-1"),
        "content-type": "application/json",
    }
    response = client.post("/hil/appr-1/decision", content=body, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["decision"] == "approve"
    assert payload["approval_id"] == "appr-1"
    assert payload["already_recorded"] is False


def test_second_call_after_resolution_returns_404() -> None:
    """Once the approval is resolved, the pending item disappears from
    the registry and subsequent callbacks to the same approval_id
    return 404 - the approval is single-use, fail-closed."""

    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {
            "decision": "approve",
            "actor_oid": "user-approver",
            "justification": "reviewed and approved by on-call",
        }
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    headers = {
        "x-fdai-timestamp": timestamp,
        "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id="appr-1"),
        "content-type": "application/json",
    }

    r1 = client.post("/hil/appr-1/decision", content=body, headers=headers)
    r2 = client.post("/hil/appr-1/decision", content=body, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# HMAC / replay
# ---------------------------------------------------------------------------


def test_missing_signature_returns_401() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps({"decision": "approve", "actor_oid": "u", "justification": "x"}).encode()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401


def test_bad_hmac_returns_401() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "reason of some length ok"}
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": "sha256=deadbeef",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["kind"] == "unauthorized"


def test_replay_window_enforced() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "reason of some length ok"}
    ).encode()
    # Timestamp two hours in the past exceeds default 300s window.
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": old,
            "x-fdai-signature": _sign(SECRET, old, body, approval_id="appr-1"),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401
    assert "skew" in response.json()["error"]["message"].lower()


def test_signature_wrong_algorithm_prefix_returns_401() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = b"{}"
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": "md5=deadbeef",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401


def test_url_path_swap_is_rejected() -> None:
    """A signature valid for one ``approval_id`` MUST NOT verify against
    a different path.

    Regression against a captured-message URL-swap attack: the caller
    signs ``timestamp . approval_id . body``, so replaying the exact
    same body + signature against a different pending item's URL breaks
    the HMAC and returns 401.
    """
    registry = InMemoryHilApprovalRegistry()
    # Seed two pending items so the target path resolves to a real item
    # (otherwise a 404 would mask the auth check).
    registry.seed(
        [
            _pending(approval_id="appr-1", idempotency_key="idem-1"),
            _pending(approval_id="appr-2", idempotency_key="idem-2"),
        ]
    )
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "reviewed"}
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    # Signature is computed with approval_id="appr-1"...
    signature = _sign(SECRET, timestamp, body, approval_id="appr-1")
    # ...but the URL swaps in "appr-2", which MUST fail the HMAC compare.
    response = client.post(
        "/hil/appr-2/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": signature,
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["kind"] == "unauthorized"


def test_naive_timestamp_rejected() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = b"{}"
    naive_ts = "2026-07-07T00:00:00"  # no tz offset
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": naive_ts,
            "x-fdai-signature": _sign(SECRET, naive_ts, body, approval_id="appr-1"),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------


def test_bad_json_body_returns_400() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = b"{not json"
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id="appr-1"),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 400


def test_unknown_decision_returns_400() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps({"decision": "escalate", "actor_oid": "u", "justification": "x"}).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id="appr-1"),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 400


def test_missing_actor_oid_returns_400() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps({"decision": "approve"}).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id="appr-1"),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 400


def test_body_too_large_returns_400() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    # Custom config with very small body cap.
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            hil_callback=HilCallbackConfig(secret=SECRET, max_body_bytes=20),
            hil_registry=registry,
        ),
    )
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "x" * 100}
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id="appr-1"),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# no_self_approval + not-found
# ---------------------------------------------------------------------------


def test_self_approval_is_403() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending(submitter_oid="same-user")])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {
            "decision": "approve",
            "actor_oid": "same-user",  # equals submitter_oid -> refused
            "justification": "reviewed and approved by on-call",
        }
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id="appr-1"),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["kind"] == "self_approval_forbidden"


def test_unknown_approval_id_is_404() -> None:
    registry = InMemoryHilApprovalRegistry()
    # Nothing seeded.
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "reviewed and approved"}
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/missing/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id="missing"),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Coordinator (park and resume) path - callback re-dispatches to the executor
# ---------------------------------------------------------------------------

_COORD_REMEDIATION_ROOT = Path(__file__).resolve().parents[3] / "rule-catalog" / "remediation"
_COORD_RULE_ID = "object-storage.owner-tag.required"


def _coord_rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=_COORD_RULE_ID,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.CONFIG_DRIFT,
        resource_type="object-storage",
        check_logic=CheckLogic(
            kind=CheckLogicKind.REGO,
            reference="policies/object_storage/owner_tag_required.rego",
        ),
        remediation=Remediation(
            template_ref="remediation/object_storage/tag_owner.tftpl",
            cost_impact_monthly_usd=0,
        ),
        remediates="remediate.tag-add",
        parameters={"tag_name": "owner", "tag_value": "unknown"},
        provenance=Provenance(
            source_url="https://example.com/rules/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _coord_action() -> Action:
    return Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000010",  # type: ignore[arg-type]
        idempotency_key="cb-idem",
        event_id="00000000-0000-0000-0000-000000000011",  # type: ignore[arg-type]
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/stg1",
        operation=Operation.TAG,
        params={"tag_value": "team-a"},
        stop_condition="target_already_tagged",
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference="pr-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.SHADOW,
        citing_rules=[_COORD_RULE_ID],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


def _make_coordinator() -> tuple[
    HilResumeCoordinator,
    RecordingRemediationPrPublisher,
    InMemoryStateStore,
]:
    publisher = RecordingRemediationPrPublisher()
    store = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=store,
        renderer=TemplateRenderer(remediation_root=_COORD_REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    coordinator = HilResumeCoordinator(
        state_store=store,
        executor=executor,
        hil_channel=InMemoryHilChannel(),
        rules_by_id={_COORD_RULE_ID: _coord_rule()},
    )
    return coordinator, publisher, store


def _post(
    client: TestClient,
    approval_id: str,
    *,
    decision: str = "approve",
    actor_oid: str = "alice@example.com",
    justification: str = "reviewed on-call",
) -> object:
    body = json.dumps(
        {"decision": decision, "actor_oid": actor_oid, "justification": justification}
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    return client.post(
        f"/hil/{approval_id}/decision",
        content=body,
        headers={
            "x-fdai-timestamp": timestamp,
            "x-fdai-signature": _sign(SECRET, timestamp, body, approval_id=approval_id),
            "content-type": "application/json",
        },
    )


def test_callback_approve_resumes_via_coordinator() -> None:
    coordinator, publisher, _ = _make_coordinator()
    asyncio.run(
        coordinator.request_approval(
            action=_coord_action(),
            rule=_coord_rule(),
            submitter_oid="system:control-loop",
            correlation_id="c1",
            approval_id="cpark-1",
        )
    )
    app = _build_app_with_callback(InMemoryHilApprovalRegistry(), coordinator=coordinator)
    client = TestClient(app)

    response = _post(client, "cpark-1", decision="approve")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["path"] == "coordinator"
    assert body["outcome"] == "executed"
    # The approved action was re-dispatched to the executor -> one shadow PR.
    assert len(publisher.records) == 1


def test_callback_reject_via_coordinator_does_not_execute() -> None:
    coordinator, publisher, _ = _make_coordinator()
    asyncio.run(
        coordinator.request_approval(
            action=_coord_action(),
            rule=_coord_rule(),
            submitter_oid="system:control-loop",
            correlation_id="c1",
            approval_id="cpark-2",
        )
    )
    app = _build_app_with_callback(InMemoryHilApprovalRegistry(), coordinator=coordinator)
    client = TestClient(app)

    response = _post(client, "cpark-2", decision="reject")
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "rejected"
    assert publisher.records == ()


def test_callback_no_park_falls_through_to_registry() -> None:
    # Coordinator wired, but the approval_id has no park -> the callback
    # must fall through to the registry path (console-pull approval).
    coordinator, publisher, _ = _make_coordinator()
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending(approval_id="appr-1", submitter_oid="user-sub")])
    app = _build_app_with_callback(registry, coordinator=coordinator)
    client = TestClient(app)

    response = _post(client, "appr-1", decision="approve", actor_oid="user-approver")
    assert response.status_code == 200, response.text
    body = response.json()
    # Registry path response shape (has 'decision', not the coordinator marker).
    assert body.get("path") != "coordinator"
    assert body["decision"] == "approve"
    # Registry path records the decision; it does not itself execute.
    assert publisher.records == ()
