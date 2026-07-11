"""Additional read-only console tools (describe_event, explain_verdict,
query_audit, query_inventory).

These complete the Day-1 read-only surface described in
[operator-console.md § 3.1](../../../../docs/roadmap/interfaces/operator-console.md).
Each tool is a self-contained :class:`SystemConsoleTool` implementation
that delegates to already-composed Layer-1 modules (T0Engine +
TrustRouter, StateStore, Inventory) via constructor injection.

Design invariants (each tool has a matching test):

- ``side_effect_class == 'read'`` on every shipped implementation.
- No cloud SDK, no HTTP, no mutation surface.
- ``describe_event`` runs the T0 pipeline **in memory**; no PR is
  opened, no audit entry written, no state mutated - even the shipped
  ShadowExecutor is intentionally not invoked.
- ``explain_verdict`` / ``query_audit`` read the InMemoryStateStore
  ``audit_entries`` iterable (or any provider that implements the
  local :class:`AuditReader` Protocol below); real Postgres backends
  will implement the same shape.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import (
    SideEffectClass,
    ToolResult,
    _optional_int,
    _optional_str,
    _require_str,
    _summary,
)
from fdai.core.operator_memory.store import OperatorMemoryStore
from fdai.core.operator_memory.types import ScopeKind
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.trust_router import RoutingTier, TrustRouter
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.observation import (
    DeploymentHistoryProvider,
    IncidentCorrelator,
    LogQueryProvider,
    MetricQueryProvider,
    ObservationError,
)


@runtime_checkable
class AuditReader(Protocol):
    """Minimal surface the audit-reading tools depend on.

    :class:`~fdai.shared.providers.testing.state_store.InMemoryStateStore`
    exposes ``audit_entries`` as a **read-only property** (returning a
    deep-copied tuple); a Postgres backend will expose a matching
    attribute or a callable adapter. This Protocol lets both shapes
    satisfy the tool contract.
    """

    audit_entries: Iterable[Mapping[str, Any]]


@runtime_checkable
class InventoryProvider(Protocol):
    """A read-only inventory that iterates :class:`InventoryBatch`."""

    def full_snapshot(self, since: str | None = None) -> AsyncIterator[Any]: ...


# ---------------------------------------------------------------------------
# describe_event
# ---------------------------------------------------------------------------


class DescribeEventTool:
    """Run one hypothetical event through the T0 pipeline in memory.

    Arguments:

    - ``resource_type`` (str, required) - the CSP-neutral resource type
      the trust router keys on (e.g. ``object-storage``,
      ``compute.vm``).
    - ``resource_id`` (str, required) - opaque resource id used by the
      audit trail; not persisted.
    - ``resource_props`` (Mapping, required) - the property bag the T0
      policy evaluators consume.
    - ``signal_type`` (str, optional) - event type marker (default
      ``synthetic.chat.describe_event``).

    Returns a :class:`ToolResult` whose ``data`` block carries the
    routing tier, decision, candidate rule ids, and every
    :class:`Finding` T0 produced. **Nothing is written to the audit
    log or the state store** - this is a strict what-if.
    """

    name = "describe_event"
    description = (
        "Run one hypothetical event through EventIngest -> TrustRouter -> T0 in "
        "memory; return the routing tier, decision, candidate rule ids, and any "
        "findings without opening a PR or writing an audit entry."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(
        self,
        *,
        trust_router: TrustRouter,
        t0_engine: T0Engine,
    ) -> None:
        self._trust_router = trust_router
        self._t0_engine = t0_engine

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002 - RBAC applied by coordinator
    ) -> ToolResult:
        resource_type = _require_str(arguments, "resource_type").strip()
        resource_id = _require_str(arguments, "resource_id").strip()
        if not resource_type or not resource_id:
            return ToolResult(
                status="error",
                preview="describe_event requires non-empty resource_type and resource_id",
            )
        raw_props = arguments.get("resource_props", {})
        if not isinstance(raw_props, Mapping):
            return ToolResult(
                status="error",
                preview="describe_event 'resource_props' MUST be a mapping",
            )
        signal_type = _optional_str(
            arguments, "signal_type", default="synthetic.chat.describe_event"
        )

        # Build a minimal, schema-valid Event. Idempotency key uses the
        # ``chat.describe_event.`` prefix so an accidental audit write
        # (guarded against below) would never collide with a real
        # event.
        now = datetime.now(tz=UTC)
        event = Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=f"chat.describe_event.{uuid4().hex[:16]}",
            source="operator-console",
            event_type=signal_type,
            resource_ref=resource_id,
            payload={
                "resource": {"type": resource_type, "id": resource_id},
                "properties": dict(raw_props),
            },
            detected_at=now,
            ingested_at=now,
            mode=Mode.SHADOW,
        )

        routing = self._trust_router.route(event)
        result: dict[str, Any] = {
            "tier": routing.tier.value,
            "resource_type": routing.resource_type,
            "candidate_rule_ids": list(routing.candidate_rule_ids),
            "reason": routing.reason,
            "findings": [],
        }
        evidence: list[str] = []

        if routing.tier == RoutingTier.T0 and routing.resource_type:
            verdict = self._t0_engine.evaluate(
                event_id=str(event.event_id),
                signal_id=str(event.event_id),
                resource_id=resource_id,
                resource_type=routing.resource_type,
                resource_props=dict(raw_props),
                signal_type=signal_type,
            )
            result["decision"] = "match" if verdict.matched else "abstain"
            findings_payload = []
            for f in verdict.findings:
                findings_payload.append(
                    {
                        "rule_id": f.rule_id,
                        "resource_id": f.resource_id,
                        "severity": _enum_value(f.severity),
                        "reason": getattr(f, "reason", None),
                    }
                )
                evidence.append(f"rule:{f.rule_id}")
            result["findings"] = findings_payload
            if verdict.audit_hint:
                result["stage"] = getattr(verdict.audit_hint, "stage", "L1_evaluate")
                result["hint_reason"] = getattr(verdict.audit_hint, "reason", None)
        else:
            result["decision"] = "abstain"

        preview = (
            f"describe_event[{resource_type}/{resource_id}]: tier={result['tier']} "
            f"decision={result['decision']} findings={len(result['findings'])}"
        )
        status: Literal["ok", "error", "abstain"] = "ok" if result["findings"] else "abstain"
        # An abstain-with-candidates is still ok-shaped so the caller
        # can inspect the reason. Preserve status='ok' for match.
        if result["decision"] == "match":
            status = "ok"
        return ToolResult(
            status=status,
            data=result,
            preview=preview,
            evidence_refs=tuple(evidence)
            + tuple(f"candidate:{rid}" for rid in result["candidate_rule_ids"]),
        )


# ---------------------------------------------------------------------------
# explain_verdict
# ---------------------------------------------------------------------------


class ExplainVerdictTool:
    """Read the audit trail for one event id and summarise the outcome.

    Arguments:

    - ``event_id`` (str UUID, required) - the event whose disposition
      the caller wants explained.

    Returns every audit entry associated with the event (control-loop
    abstains, execution outcomes, shadow-authority parallels), sorted
    by ``recorded_at`` timestamp ascending. Empty result = the event
    was not seen (or has not been audited yet).
    """

    name = "explain_verdict"
    description = (
        "Return the audit-trail projection for one event_id: tier, decision, "
        "citing rule ids, and mode. Read-only."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, audit_reader: AuditReader) -> None:
        self._audit = audit_reader

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002
    ) -> ToolResult:
        raw_event_id = _require_str(arguments, "event_id").strip()
        if not raw_event_id:
            return ToolResult(
                status="error",
                preview="explain_verdict requires a non-empty 'event_id'",
            )
        # Sanity check: valid UUID shape or return error.
        try:
            UUID(raw_event_id)
        except ValueError:
            return ToolResult(
                status="error",
                preview=f"explain_verdict 'event_id' must be a UUID, got {raw_event_id!r}",
            )

        matched = _select_audit(self._audit, event_id=raw_event_id)
        projections = [_project_audit_entry(entry) for entry in matched]
        preview = f"explain_verdict[{raw_event_id[:8]}...]: {len(projections)} entry(ies)"
        return ToolResult(
            status="ok" if projections else "abstain",
            data={"event_id": raw_event_id, "entries": projections},
            preview=preview,
            evidence_refs=tuple(f"audit:{p['audit_id']}" for p in projections if p.get("audit_id")),
        )


# ---------------------------------------------------------------------------
# query_audit
# ---------------------------------------------------------------------------


class QueryAuditTool:
    """Structured audit search.

    Arguments (all optional; at least one MUST be supplied):

    - ``event_id`` (str)
    - ``actor`` (str, substring match)
    - ``decision`` (str, exact match)
    - ``action_kind`` (str, exact match; e.g.
      ``control_loop.abstain`` / ``risk_gate.shadow_authority``)
    - ``since`` (RFC 3339 timestamp, ISO 8601)
    - ``limit`` (int, default 20, capped 200)
    """

    name = "query_audit"
    description = (
        "Filter the audit log by any of event_id / actor / decision / "
        "action_kind / since. Paginated (limit)."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, audit_reader: AuditReader) -> None:
        self._audit = audit_reader

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002
    ) -> ToolResult:
        limit = _optional_int(arguments, "limit", default=20, minimum=1, maximum=200)
        filters = {
            "event_id": _optional_str(arguments, "event_id", default="").strip(),
            "actor": _optional_str(arguments, "actor", default="").strip(),
            "decision": _optional_str(arguments, "decision", default="").strip(),
            "action_kind": _optional_str(arguments, "action_kind", default="").strip(),
            "since": _optional_str(arguments, "since", default="").strip(),
        }
        if not any(filters.values()):
            return ToolResult(
                status="error",
                preview=(
                    "query_audit requires at least one filter "
                    "(event_id / actor / decision / action_kind / since)"
                ),
            )

        since_dt: datetime | None = None
        if filters["since"]:
            try:
                since_dt = datetime.fromisoformat(filters["since"].replace("Z", "+00:00"))
            except ValueError:
                return ToolResult(
                    status="error",
                    preview=f"query_audit 'since' MUST be RFC 3339; got {filters['since']!r}",
                )

        entries = _select_audit(
            self._audit,
            event_id=filters["event_id"] or None,
            actor_substring=filters["actor"] or None,
            decision=filters["decision"] or None,
            action_kind=filters["action_kind"] or None,
            since=since_dt,
        )
        limited = entries[:limit]
        projections = [_project_audit_entry(e) for e in limited]
        preview = (
            f"query_audit: {len(projections)} of {len(entries)} entry(ies) "
            f"(filters={_filter_summary(filters)})"
        )
        return ToolResult(
            status="ok" if projections else "abstain",
            data={
                "filters": filters,
                "total_matched": len(entries),
                "entries": projections,
            },
            preview=preview,
            evidence_refs=tuple(f"audit:{p['audit_id']}" for p in projections if p.get("audit_id")),
        )


# ---------------------------------------------------------------------------
# query_inventory
# ---------------------------------------------------------------------------


class QueryInventoryTool:
    """Read the inventory graph by resource type and optional filter.

    Arguments:

    - ``resource_type`` (str, required) - CSP-neutral vocabulary
      matching ``rule-catalog/vocabulary/resource-types.yaml``.
    - ``id_substring`` (str, optional) - case-insensitive filter over
      resource id.
    - ``limit`` (int, optional; default 20, capped 200).

    Result: list of ``{id, resource_type, properties}`` projections.

    The tool is async-friendly - it consumes ``full_snapshot`` which is
    an async iterator - but exposes a sync ``call`` because the
    Day-1 coordinator is sync. It uses ``asyncio.run`` internally,
    which is safe because the coordinator is not itself inside an
    event loop.
    """

    name = "query_inventory"
    description = (
        "Return the inventory records for a given resource_type, optionally "
        "filtered by id substring. Read-only."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, inventory: InventoryProvider) -> None:
        self._inventory = inventory

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002
    ) -> ToolResult:
        import asyncio

        resource_type = _require_str(arguments, "resource_type").strip()
        if not resource_type:
            return ToolResult(
                status="error",
                preview="query_inventory requires a non-empty 'resource_type'",
            )
        id_substring = _optional_str(arguments, "id_substring", default="").lower()
        limit = _optional_int(arguments, "limit", default=20, minimum=1, maximum=200)

        try:
            projections = asyncio.run(
                _drain_inventory(
                    self._inventory,
                    resource_type=resource_type,
                    id_substring=id_substring,
                    limit=limit,
                )
            )
        except RuntimeError as exc:
            # Nested-loop scenarios (should not happen from the CLI) fall
            # through as an error so the caller can retry.
            return ToolResult(
                status="error",
                preview=f"query_inventory event-loop reuse: {exc}",
            )

        preview = f"query_inventory[{resource_type}]: {len(projections)} record(s)"
        return ToolResult(
            status="ok" if projections else "abstain",
            data={
                "resource_type": resource_type,
                "id_substring": id_substring,
                "records": projections,
            },
            preview=preview,
            evidence_refs=tuple(f"inventory:{p['id']}" for p in projections),
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _unwrap_audit_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the inner entry dict regardless of storage shape.

    :class:`InMemoryStateStore` wraps every entry in a hash-chain
    envelope ``{"entry": <original>, "previous_hash": ..., "entry_hash":
    ...}`` for tamper-evidence; the flat shape (real Postgres backend
    row projected through a view) has the domain keys at the top
    level. This helper normalises both so ``_select_audit`` doesn't
    have to know which is which.

    The wrapper is only detected when the outer record has an ``entry``
    key whose value is a mapping AND either a ``previous_hash`` or
    ``entry_hash`` companion field - so a legitimate flat entry that
    happens to carry an ``entry`` key is not misinterpreted.
    """

    if not isinstance(record, Mapping):
        return {}
    inner = record.get("entry")
    if isinstance(inner, Mapping) and ("previous_hash" in record or "entry_hash" in record):
        return inner
    return record


def _select_audit(
    audit_reader: AuditReader,
    *,
    event_id: str | None = None,
    actor_substring: str | None = None,
    decision: str | None = None,
    action_kind: str | None = None,
    since: datetime | None = None,
) -> list[Mapping[str, Any]]:
    """Filter and sort audit entries deterministically.

    Sort order is ``recorded_at`` ascending; entries without a
    ``recorded_at`` land last so a filter never silently drops them.
    """

    matched: list[tuple[datetime | None, Mapping[str, Any]]] = []
    for record in audit_reader.audit_entries:
        entry = _unwrap_audit_record(record)
        if event_id and entry.get("event_id") != event_id:
            continue
        if actor_substring and actor_substring not in str(entry.get("actor", "")):
            continue
        if decision and entry.get("decision") != decision:
            continue
        if action_kind and entry.get("action_kind") != action_kind:
            continue
        recorded_raw = entry.get("recorded_at")
        recorded_dt: datetime | None = None
        if isinstance(recorded_raw, str):
            try:
                recorded_dt = datetime.fromisoformat(recorded_raw.replace("Z", "+00:00"))
            except ValueError:
                recorded_dt = None
        if since is not None and recorded_dt is not None and recorded_dt < since:
            continue
        matched.append((recorded_dt, entry))
    matched.sort(key=lambda pair: (pair[0] is None, pair[0] or datetime.min.replace(tzinfo=UTC)))
    return [entry for _, entry in matched]


def _project_audit_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce a raw audit entry to a stable, CLI-friendly projection.

    Includes only fields the audit-vocab in
    :mod:`fdai.core.control_loop` and
    :mod:`fdai.core.risk_gate.authority` document; anything else
    stays under ``extra`` for opt-in inspection.
    """

    stable = {
        "audit_id": entry.get("audit_id") or entry.get("id"),
        "event_id": entry.get("event_id"),
        "action_kind": entry.get("action_kind"),
        "actor": entry.get("actor"),
        "decision": entry.get("decision"),
        "mode": entry.get("mode"),
        "stage": entry.get("stage"),
        "recorded_at": entry.get("recorded_at"),
        "citing_rule_ids": list(
            entry.get("candidate_rule_ids") or entry.get("citing_rule_ids") or []
        ),
        "reason": _summary(str(entry.get("reason", ""))) or None,
    }
    known_keys = set(stable) | {"idempotency_key", "resource_type"}
    extra = {k: v for k, v in entry.items() if k not in known_keys}
    if extra:
        stable["extra"] = extra
    return {k: v for k, v in stable.items() if v is not None}


def _filter_summary(filters: Mapping[str, str]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in filters.items() if v)


async def _drain_inventory(
    inventory: InventoryProvider,
    *,
    resource_type: str,
    id_substring: str,
    limit: int,
) -> list[dict[str, Any]]:
    projections: list[dict[str, Any]] = []
    async for batch in inventory.full_snapshot():
        resources = getattr(batch, "resources", ()) or ()
        for record in resources:
            rec_type = getattr(record, "type", None) or getattr(record, "resource_type", None)
            if rec_type != resource_type:
                continue
            rec_id = str(getattr(record, "id", "") or getattr(record, "resource_id", ""))
            if id_substring and id_substring not in rec_id.lower():
                continue
            props = dict(getattr(record, "properties", {}) or {})
            projections.append(
                {
                    "id": rec_id,
                    "resource_type": rec_type,
                    "properties": props,
                }
            )
            if len(projections) >= limit:
                return projections
    return projections


# ---------------------------------------------------------------------------
# query_operator_memory  (Wave W1.6)
# ---------------------------------------------------------------------------


class QueryOperatorMemoryTool:
    """Return active operator-memory entries visible to the caller's scope.

    A Reader-floor read of the ``OperatorMemoryStore``. Operator memory is
    the append-only ledger the HIL reject pipeline and other governance
    workflows write into (see
    :mod:`fdai.core.operator_memory`). Exposing it as a console
    read tool lets an operator inspect "what have we already decided
    about this scope" before proposing a change - the narrator never
    reads memory directly, matching R6 in
    [implementation-plan.md](../../../../docs/roadmap/fork-and-sequencing/implementation-plan.md).

    Arguments (``arguments`` mapping):

    - ``scope_kind`` (str, required) - ``resource-group`` or
      ``resource`` (the only two shipped scopes; broader scopes are
      catalog-level retirements, not memory entries).
    - ``scope_ref`` (str, required) - opaque scope handle
      (resource-group name, resource id).
    - ``limit`` (int, optional; default 20, capped 100).

    Returns a :class:`ToolResult` with a projected list of active
    entries (superseded / expired rows are filtered by the store). No
    audit entry, no mutation - RBAC (Reader floor) plus the store's
    active-only filter is the entire policy surface.
    """

    name = "query_operator_memory"
    description = (
        "Return active operator-memory entries for a (scope_kind, scope_ref). "
        "Read-only; superseded / expired rows are filtered."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, store: OperatorMemoryStore) -> None:
        self._store = store

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002 - RBAC applied by coordinator
    ) -> ToolResult:
        import asyncio

        raw_scope_kind = _require_str(arguments, "scope_kind").strip()
        raw_scope_ref = _require_str(arguments, "scope_ref").strip()
        if not raw_scope_kind:
            return ToolResult(
                status="error",
                preview="query_operator_memory requires a non-empty 'scope_kind'",
            )
        if not raw_scope_ref:
            return ToolResult(
                status="error",
                preview="query_operator_memory requires a non-empty 'scope_ref'",
            )
        try:
            scope_kind = ScopeKind(raw_scope_kind)
        except ValueError:
            allowed = ", ".join(sorted(k.value for k in ScopeKind))
            return ToolResult(
                status="error",
                preview=(f"query_operator_memory 'scope_kind' MUST be one of: {allowed}"),
            )
        limit = _optional_int(arguments, "limit", default=20, minimum=1, maximum=100)

        try:
            entries = asyncio.run(
                self._store.list_active_for_scope(scope_kind=scope_kind, scope_ref=raw_scope_ref)
            )
        except RuntimeError as exc:
            return ToolResult(
                status="error",
                preview=f"query_operator_memory event-loop reuse: {exc}",
            )

        projected = [_project_memory_entry(e) for e in entries[:limit]]
        preview = (
            f"query_operator_memory[{scope_kind.value}={raw_scope_ref}]: "
            f"{len(projected)} active entry(ies)"
        )
        return ToolResult(
            status="ok" if projected else "abstain",
            data={
                "scope_kind": scope_kind.value,
                "scope_ref": raw_scope_ref,
                "limit": limit,
                "total_active": len(entries),
                "entries": projected,
            },
            preview=preview,
            evidence_refs=tuple(f"operator-memory:{p['id']}" for p in projected),
        )


def _project_memory_entry(entry: Any) -> dict[str, Any]:
    """Project one :class:`OperatorMemoryEntry` into a JSON-friendly dict.

    Passed as ``Any`` to keep the module import graph flat; the shape
    is documented in :mod:`fdai.core.operator_memory.types`.
    """

    ttl = getattr(entry, "ttl_seconds", None)
    return {
        "id": str(entry.id),
        "scope_kind": _enum_value(entry.scope_kind),
        "scope_ref": entry.scope_ref,
        "category": _enum_value(entry.category),
        "body": entry.body,
        "source_event": _enum_value(entry.source_event),
        "source_ref": entry.source_ref,
        "author": entry.author,
        "approved_by": entry.approved_by,
        "created_at": entry.created_at.isoformat(),
        "ttl_seconds": ttl,
    }


# ---------------------------------------------------------------------------
# Observation-depth tools  (Wave M1.5)
# ---------------------------------------------------------------------------
#
# Four Reader-floor read tools that consume the observation-depth
# Protocols shipped in ``shared/providers/observation.py``. Every tool:
#
# - is read-only (``side_effect_class == 'read'``);
# - never writes an audit entry (the coordinator writes ``console.turn``
#   on its own);
# - catches :class:`ObservationError` and returns an ``abstain`` result
#   with a preview describing the abstain cause - the caller (narrator
#   or CLI) never sees a raw traceback.
#
# The Protocols themselves are CSP-neutral; real adapters (Azure Monitor,
# deployment-history join) live in ``delivery/`` and are fork-authored.


class QueryLogTool:
    """Run a bounded log query and return the raw rows.

    Arguments (``arguments`` mapping):

    - ``query`` (str, required) - opaque KQL / adapter-defined query.
    - ``window`` (str, required) - opaque time window
      (``PT1H``, ``P1D``, or the adapter's own shape).
    - ``max_rows`` (int, optional; default 100, capped 500).
    """

    name = "query_log"
    description = (
        "Run a bounded log query and return the rows. Read-only; abstains when the provider raises."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, provider: LogQueryProvider) -> None:
        self._provider = provider

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002 - RBAC applied by coordinator
    ) -> ToolResult:
        import asyncio

        query = _require_str(arguments, "query").strip()
        window = _require_str(arguments, "window").strip()
        if not query:
            return ToolResult(status="error", preview="query_log requires a non-empty 'query'")
        if not window:
            return ToolResult(status="error", preview="query_log requires a non-empty 'window'")
        max_rows = _optional_int(arguments, "max_rows", default=100, minimum=1, maximum=500)

        try:
            result = asyncio.run(
                self._provider.query_log(query=query, window=window, max_rows=max_rows)
            )
        except ObservationError as exc:
            return ToolResult(
                status="abstain",
                preview=f"query_log abstains: {exc}",
                data={"query": query, "window": window},
            )
        except RuntimeError as exc:
            return ToolResult(status="error", preview=f"query_log event-loop reuse: {exc}")

        rows = [dict(r) for r in result.rows]
        preview = f"query_log[{window}]: {len(rows)} row(s)" + (
            " (truncated)" if result.truncated else ""
        )
        return ToolResult(
            status="ok" if rows else "abstain",
            data={
                "query": query,
                "window": window,
                "rows": rows,
                "truncated": result.truncated,
                "scanned_records": result.scanned_records,
            },
            preview=preview,
        )


class QueryMetricTool:
    """Return a metric aggregation over a bounded window.

    Arguments:

    - ``namespace`` (str, required) - e.g.
      ``Microsoft.Compute/virtualMachines``.
    - ``metric`` (str, required) - e.g. ``Percentage CPU``.
    - ``aggregation`` (str, required) - e.g. ``Average`` / ``Total``.
    - ``window`` (str, required) - opaque time window.
    """

    name = "query_metric"
    description = (
        "Return a metric aggregation timeseries. Read-only; abstains when the provider raises."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, provider: MetricQueryProvider) -> None:
        self._provider = provider

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002 - RBAC applied by coordinator
    ) -> ToolResult:
        import asyncio

        namespace = _require_str(arguments, "namespace").strip()
        metric = _require_str(arguments, "metric").strip()
        aggregation = _require_str(arguments, "aggregation").strip()
        window = _require_str(arguments, "window").strip()
        for name_, value in (
            ("namespace", namespace),
            ("metric", metric),
            ("aggregation", aggregation),
            ("window", window),
        ):
            if not value:
                return ToolResult(
                    status="error",
                    preview=f"query_metric requires a non-empty {name_!r}",
                )

        try:
            result = asyncio.run(
                self._provider.query_metric(
                    namespace=namespace,
                    metric=metric,
                    aggregation=aggregation,
                    window=window,
                )
            )
        except ObservationError as exc:
            return ToolResult(
                status="abstain",
                preview=f"query_metric abstains: {exc}",
                data={
                    "namespace": namespace,
                    "metric": metric,
                    "aggregation": aggregation,
                    "window": window,
                },
            )
        except RuntimeError as exc:
            return ToolResult(status="error", preview=f"query_metric event-loop reuse: {exc}")

        points = [{"timestamp": p.timestamp, "value": p.value} for p in result.points]
        preview = f"query_metric[{namespace}/{metric}]: {len(points)} point(s)"
        return ToolResult(
            status="ok" if points else "abstain",
            data={
                "namespace": namespace,
                "metric": metric,
                "aggregation": aggregation,
                "window": window,
                "points": points,
            },
            preview=preview,
        )


class QueryDeploymentsTool:
    """Return the deployment history for a window (optionally filtered).

    Arguments:

    - ``window`` (str, required) - opaque time window.
    - ``resource_ref`` (str, optional) - filter to deployments that
      touched this resource ref.
    """

    name = "query_deployments"
    description = (
        "Return deployment records over a time window, optionally filtered "
        "by resource_ref. Read-only; abstains when the provider raises."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, provider: DeploymentHistoryProvider) -> None:
        self._provider = provider

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002 - RBAC applied by coordinator
    ) -> ToolResult:
        import asyncio

        window = _require_str(arguments, "window").strip()
        if not window:
            return ToolResult(
                status="error", preview="query_deployments requires a non-empty 'window'"
            )
        resource_ref = _optional_str(arguments, "resource_ref", default="") or None
        if resource_ref is not None and not resource_ref.strip():
            resource_ref = None

        try:
            result = asyncio.run(
                self._provider.query_deployments(window=window, resource_ref=resource_ref)
            )
        except ObservationError as exc:
            return ToolResult(
                status="abstain",
                preview=f"query_deployments abstains: {exc}",
                data={"window": window, "resource_ref": resource_ref},
            )
        except RuntimeError as exc:
            return ToolResult(status="error", preview=f"query_deployments event-loop reuse: {exc}")

        records = [_project_deployment_record(r) for r in result.records]
        preview = f"query_deployments[{window}]: {len(records)} deployment(s)"
        return ToolResult(
            status="ok" if records else "abstain",
            data={
                "window": window,
                "resource_ref": resource_ref,
                "records": records,
            },
            preview=preview,
            evidence_refs=tuple(f"deployment:{r['deployment_ref']}" for r in records),
        )


class CorrelateIncidentTool:
    """Return the multi-signal correlation for one incident id.

    Arguments:

    - ``incident_id`` (str, required) - opaque incident id.
    """

    name = "correlate_incident"
    description = (
        "Return the multi-signal correlation (events, audit, logs, metrics, "
        "deployments) for one incident_id. Read-only; abstains when the "
        "correlator raises."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, correlator: IncidentCorrelator) -> None:
        self._correlator = correlator

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002 - RBAC applied by coordinator
    ) -> ToolResult:
        import asyncio

        incident_id = _require_str(arguments, "incident_id").strip()
        if not incident_id:
            return ToolResult(
                status="error",
                preview="correlate_incident requires a non-empty 'incident_id'",
            )

        try:
            corr = asyncio.run(self._correlator.correlate(incident_id=incident_id))
        except ObservationError as exc:
            return ToolResult(
                status="abstain",
                preview=f"correlate_incident abstains: {exc}",
                data={"incident_id": incident_id},
            )
        except RuntimeError as exc:
            return ToolResult(
                status="error",
                preview=f"correlate_incident event-loop reuse: {exc}",
            )

        preview = (
            f"correlate_incident[{incident_id}]: "
            f"{len(corr.events)} evt / {len(corr.audit_entries)} audit / "
            f"{len(corr.log_hits)} log / {len(corr.metric_points)} metric / "
            f"{len(corr.deployments)} deploy"
        )
        return ToolResult(
            status="ok",
            data={
                "incident_id": corr.incident_id,
                "events": [dict(e) for e in corr.events],
                "audit_entries": [dict(e) for e in corr.audit_entries],
                "log_hits": [dict(e) for e in corr.log_hits],
                "metric_points": [
                    {"timestamp": p.timestamp, "value": p.value} for p in corr.metric_points
                ],
                "deployments": [_project_deployment_record(d) for d in corr.deployments],
            },
            preview=preview,
            evidence_refs=(f"incident:{corr.incident_id}",),
        )


def _project_deployment_record(record: Any) -> dict[str, Any]:
    """Project one :class:`DeploymentRecord` into a JSON-friendly dict."""

    return {
        "deployment_ref": record.deployment_ref,
        "timestamp": record.timestamp,
        "author": record.author,
        "resource_refs": list(record.resource_refs),
        "status": record.status,
    }


__all__ = [
    "AuditReader",
    "CorrelateIncidentTool",
    "DescribeEventTool",
    "ExplainVerdictTool",
    "InventoryProvider",
    "QueryAuditTool",
    "QueryDeploymentsTool",
    "QueryInventoryTool",
    "QueryLogTool",
    "QueryMetricTool",
    "QueryOperatorMemoryTool",
]
