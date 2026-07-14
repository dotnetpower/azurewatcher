"""StateStore-backed HIL registry projected from durable core park records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Final

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilDecisionReceipt,
    HilItemAlreadyResolvedError,
    HilItemNotFoundError,
    HilPendingItem,
    MutationTarget,
)
from fdai.shared.providers.state_store import StateStore

_PARK_PREFIX: Final[str] = "hil_park:"
_DECISION_PREFIX: Final[str] = "hil_decision:"
_INDEX_KEY: Final[str] = "hil_pending:index"


class StateStoreHilApprovalRegistry(HilApprovalRegistry):
    """Read pending parks and persist idempotent approval decisions."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def list_pending(self, *, limit: int = 50) -> Sequence[HilPendingItem]:
        index = await self._store.read_state(_INDEX_KEY) or {}
        approval_ids = index.get("approval_ids", [])
        if not isinstance(approval_ids, list):
            return ()
        items: list[HilPendingItem] = []
        for approval_id in approval_ids:
            if not isinstance(approval_id, str):
                continue
            park = await self._store.read_state(_park_key(approval_id))
            item = _pending_from_park(park)
            if item is not None:
                items.append(item)
        items.sort(
            key=lambda item: (
                item.requested_at or datetime.min.replace(tzinfo=UTC),
                item.idempotency_key,
            ),
            reverse=True,
        )
        return tuple(items[: max(1, limit)])

    async def get_pending(self, idempotency_key: str) -> HilPendingItem | None:
        for item in await self.list_pending(limit=10_000):
            if item.idempotency_key == idempotency_key:
                return item
        return None

    async def record_decision(
        self,
        *,
        idempotency_key: str,
        decision: HilApprovalDecision,
        approver_oid: str,
        justification: str = "",
        decided_at: datetime | None = None,
    ) -> HilDecisionReceipt:
        existing = await self._store.read_state(_decision_key(idempotency_key))
        if existing is not None:
            prior = _receipt_from_mapping(existing, already_recorded=True)
            if prior.decision is not decision:
                raise HilItemAlreadyResolvedError(
                    idempotency_key,
                    prior_decision=prior.decision.value,
                )
            return prior

        pending = await self.get_pending(idempotency_key)
        if pending is None:
            raise HilItemNotFoundError(idempotency_key)

        now = decided_at or datetime.now(tz=UTC)
        receipt_ref = (
            "hil-receipt:"
            + hashlib.sha256(
                f"{idempotency_key}:{decision.value}:{approver_oid}".encode()
            ).hexdigest()
        )
        receipt = HilDecisionReceipt(
            approval_id=pending.approval_id,
            idempotency_key=idempotency_key,
            decision=decision,
            approver_oid=approver_oid,
            decided_at=now,
            receipt_ref=receipt_ref,
            already_recorded=False,
            justification=justification,
        )
        await self._store.write_state(
            _decision_key(idempotency_key),
            {
                "approval_id": receipt.approval_id,
                "idempotency_key": receipt.idempotency_key,
                "decision": receipt.decision.value,
                "approver_oid": receipt.approver_oid,
                "decided_at": receipt.decided_at.isoformat(),
                "receipt_ref": receipt.receipt_ref,
                "justification": receipt.justification,
            },
        )
        return receipt


class PostgresHilApprovalRegistry(StateStoreHilApprovalRegistry):
    """Multi-replica-safe HIL registry over Postgres ``state_kv``."""

    def __init__(
        self,
        *,
        store: StateStore,
        dsn: str,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        super().__init__(store=store)
        if not dsn:
            raise ValueError("dsn MUST be non-empty")
        if statement_timeout_ms < 1 or connect_timeout_s < 1:
            raise ValueError("timeouts MUST be positive")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def record_decision(
        self,
        *,
        idempotency_key: str,
        decision: HilApprovalDecision,
        approver_oid: str,
        justification: str = "",
        decided_at: datetime | None = None,
    ) -> HilDecisionReceipt:
        pending = await self.get_pending(idempotency_key)
        now = decided_at or datetime.now(tz=UTC)
        approval_id = pending.approval_id if pending is not None else ""
        receipt_ref = (
            "hil-receipt:"
            + hashlib.sha256(
                f"{idempotency_key}:{decision.value}:{approver_oid}".encode()
            ).hexdigest()
        )
        payload = {
            "approval_id": approval_id,
            "idempotency_key": idempotency_key,
            "decision": decision.value,
            "approver_oid": approver_oid,
            "decided_at": now.isoformat(),
            "receipt_ref": receipt_ref,
            "justification": justification,
        }
        key = _decision_key(idempotency_key)
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._statement_timeout_ms),),
                )
                inserted = await conn.execute(
                    "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                    "ON CONFLICT (key) DO NOTHING",
                    (key, json.dumps(payload)),
                )
                row_payload: Mapping[str, object]
                if inserted.rowcount == 1:
                    if pending is None:
                        raise HilItemNotFoundError(idempotency_key)
                    row_payload = payload
                else:
                    cursor = await conn.execute(
                        "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                        (key,),
                    )
                    row = await cursor.fetchone()
                    if row is None:  # pragma: no cover - transaction invariant
                        raise RuntimeError("HIL decision row disappeared during conflict read")
                    value = row["value"]
                    if not isinstance(value, Mapping):
                        raise RuntimeError("stored HIL decision is not a JSON object")
                    row_payload = value

        prior = _receipt_from_mapping(
            row_payload,
            already_recorded=inserted.rowcount != 1,
        )
        if prior.decision is not decision:
            raise HilItemAlreadyResolvedError(
                idempotency_key,
                prior_decision=prior.decision.value,
            )
        return prior


async def add_pending_approval(store: StateStore, approval_id: str) -> None:
    """Add an approval id to the durable projection index idempotently."""
    index = await store.read_state(_INDEX_KEY) or {}
    raw_ids = index.get("approval_ids", [])
    approval_ids = [str(value) for value in raw_ids] if isinstance(raw_ids, list) else []
    if approval_id not in approval_ids:
        approval_ids.append(approval_id)
        await store.write_state(_INDEX_KEY, {"approval_ids": approval_ids})


def _park_key(approval_id: str) -> str:
    return f"{_PARK_PREFIX}{approval_id}"


def _decision_key(idempotency_key: str) -> str:
    return f"{_DECISION_PREFIX}{idempotency_key}"


def _pending_from_park(park: Mapping[str, object] | None) -> HilPendingItem | None:
    if park is None or park.get("status") != "pending":
        return None
    action = park.get("action")
    if not isinstance(action, Mapping):
        return None
    approval_id = str(park.get("approval_id") or "")
    idempotency_key = str(park.get("idempotency_key") or "")
    if not approval_id or not idempotency_key:
        return None
    parked_at = park.get("parked_at")
    requested_at: datetime | None = None
    if isinstance(parked_at, str):
        try:
            requested_at = datetime.fromisoformat(parked_at.replace("Z", "+00:00"))
        except ValueError:
            requested_at = None
    mutation_target = None
    execution_path = park.get("execution_path")
    if isinstance(execution_path, str):
        try:
            mutation_target = MutationTarget(execution_path)
        except ValueError:
            mutation_target = None
    citing_rules = action.get("citing_rules", ())
    return HilPendingItem(
        idempotency_key=idempotency_key,
        approval_id=approval_id,
        event_id=str(action.get("event_id") or ""),
        action_id=str(action.get("action_id") or ""),
        action_kind=str(park.get("action_type") or action.get("action_type") or ""),
        target_resource_ref=str(action.get("target_resource_ref") or ""),
        reason="Approval required by the risk gate.",
        submitter_oid=str(park.get("submitter_oid") or ""),
        citing_rule_ids=tuple(str(value) for value in citing_rules),
        requested_at=requested_at,
        correlation_id=str(park.get("correlation_id") or "") or None,
        mutation_target=mutation_target,
    )


def _receipt_from_mapping(
    value: Mapping[str, object], *, already_recorded: bool
) -> HilDecisionReceipt:
    decided_at_raw = value.get("decided_at")
    if not isinstance(decided_at_raw, str):
        raise RuntimeError("stored HIL decision is missing decided_at")
    return HilDecisionReceipt(
        approval_id=str(value.get("approval_id") or ""),
        idempotency_key=str(value.get("idempotency_key") or ""),
        decision=HilApprovalDecision(str(value.get("decision") or "")),
        approver_oid=str(value.get("approver_oid") or ""),
        decided_at=datetime.fromisoformat(decided_at_raw.replace("Z", "+00:00")),
        receipt_ref=str(value.get("receipt_ref") or ""),
        already_recorded=already_recorded,
        justification=str(value.get("justification") or ""),
    )


__all__ = [
    "PostgresHilApprovalRegistry",
    "StateStoreHilApprovalRegistry",
    "add_pending_approval",
]
