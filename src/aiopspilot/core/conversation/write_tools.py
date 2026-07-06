"""Write-class console tools (Wave W1.1 - operator-console.md 3.2).

Distinct from :mod:`aiopspilot.core.conversation.system_tools` (read-only
Day-1 tools) so the ``side_effect_class == 'read'`` invariant on that
module stays a compile-time property: a tool that lands here MUST NOT
sneak into the read-only surface by import order accident.

Wave scope

- **This module (W1.1 partial)** - :class:`SimulateChangeTool`. Runs one
  hypothetical event through the deterministic pipeline in memory, builds
  the resulting :class:`Action` per finding, renders the shadow PR
  patch, and returns everything **without publishing**. The tool writes
  exactly one ``console.simulate_change`` audit entry so an operator can
  find the simulation later via ``query_audit``.
- **Next slices** - ``approve_hil`` / ``list_hil`` land alongside the
  HIL queue read model, in a separate follow-up commit so the write set
  stays small and each slice is separately reviewable.

Design invariants (each tool has a matching test):

- ``side_effect_class == 'simulate'`` - the caller's real PR publisher,
  ShadowExecutor, and StateStore are NEVER invoked by this tool.
- Verifier re-check is preserved: T0Engine runs the shipped policy
  evaluators exactly as the production loop does.
- Safety invariants (stop_condition, rollback, blast_radius) MUST be
  present on every produced Action; ActionBuilder raises otherwise and
  the tool degrades to :attr:`ToolResult.status = 'error'`.
- No mutation of the caller's audit store beyond a single
  ``console.simulate_change`` record.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from aiopspilot.core.conversation.session import Principal, Role
from aiopspilot.core.conversation.tools import (
    SideEffectClass,
    ToolResult,
    _optional_str,
)
from aiopspilot.core.executor.action_builder import ActionBuilder, ActionBuildError
from aiopspilot.core.executor.renderer import (
    RenderError,
    RenderRequest,
    TemplateRenderer,
)
from aiopspilot.core.tiers.t0_deterministic import T0Engine
from aiopspilot.core.trust_router import RoutingTier, TrustRouter
from aiopspilot.shared.contracts.models import Event, Mode, Rule


class SimulateChangeTool:
    """Simulate one event end-to-end without publishing.

    The tool runs the deterministic pipeline in memory, builds one
    :class:`Action` per finding, and renders the shadow PR patch. It
    NEVER opens a PR and never touches the ShadowExecutor. A single
    ``console.simulate_change`` audit entry is appended to the caller's
    audit store so the simulation is discoverable via
    :class:`~aiopspilot.core.conversation.system_tools.QueryAuditTool`.

    Arguments (``arguments`` mapping):

    - ``scenario`` (Mapping, required) - the event payload the operator
      wants to simulate. MUST carry at minimum
      ``resource_type`` and ``resource_id``; ``resource_props`` is
      optional (defaults to empty mapping). Any additional keys land
      under the Event's ``payload`` block verbatim.
    - ``signal_type`` (str, optional) - event type marker (default
      ``synthetic.chat.simulate_change``).
    """

    name = "simulate_change"
    description = (
        "Run one hypothetical event through EventIngest -> TrustRouter -> T0 -> "
        "ActionBuilder -> TemplateRenderer in memory; return the outcome and "
        "the generated PR intent(s) without publishing. Writes exactly one "
        "'console.simulate_change' audit entry."
    )
    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "simulate"

    def __init__(
        self,
        *,
        trust_router: TrustRouter,
        t0_engine: T0Engine,
        action_builder: ActionBuilder,
        template_renderer: TemplateRenderer,
        rules_by_id: Mapping[str, Rule],
        audit_writer: AuditWriter,
    ) -> None:
        self._trust_router = trust_router
        self._t0_engine = t0_engine
        self._action_builder = action_builder
        self._template_renderer = template_renderer
        self._rules_by_id = dict(rules_by_id)
        self._audit_writer = audit_writer

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult:
        scenario = arguments.get("scenario")
        if not isinstance(scenario, Mapping) or not scenario:
            return ToolResult(
                status="error",
                preview="simulate_change requires a non-empty 'scenario' mapping",
            )
        resource_type = str(scenario.get("resource_type", "")).strip()
        resource_id = str(scenario.get("resource_id", "")).strip()
        if not resource_type or not resource_id:
            return ToolResult(
                status="error",
                preview=(
                    "simulate_change 'scenario' MUST carry non-empty "
                    "'resource_type' and 'resource_id'"
                ),
            )
        raw_props = scenario.get("resource_props", {})
        if not isinstance(raw_props, Mapping):
            return ToolResult(
                status="error",
                preview="simulate_change 'scenario.resource_props' MUST be a mapping",
            )
        signal_type = _optional_str(
            arguments, "signal_type", default="synthetic.chat.simulate_change"
        )

        event = _build_synthetic_event(
            resource_type=resource_type,
            resource_id=resource_id,
            resource_props=raw_props,
            signal_type=signal_type,
            extra_payload={
                k: v
                for k, v in scenario.items()
                if k not in ("resource_type", "resource_id", "resource_props")
            },
        )

        routing = self._trust_router.route(event)
        result: dict[str, Any] = {
            "tier": routing.tier.value,
            "resource_type": routing.resource_type,
            "candidate_rule_ids": list(routing.candidate_rule_ids),
            "routing_reason": routing.reason,
            "findings": [],
            "actions": [],
            "pr_intents": [],
        }
        evidence: list[str] = []

        # Non-T0 -> the deterministic layer has no answer; abstain.
        if routing.tier != RoutingTier.T0 or not routing.resource_type:
            outcome: Literal["abstained_routing", "abstained_t0", "simulated"] = "abstained_routing"
            preview = (
                f"simulate_change[{resource_type}/{resource_id}]: "
                f"routing abstain (tier={routing.tier.value})"
            )
            audit_id = self._audit_writer.write_simulation_entry(
                event=event,
                principal=principal,
                outcome=outcome,
                reason=routing.reason,
                citing_rule_ids=tuple(routing.candidate_rule_ids),
                pr_intents=(),
                findings_summary=(),
            )
            return ToolResult(
                status="abstain",
                data={**result, "outcome": outcome, "audit_id": audit_id},
                preview=preview,
                evidence_refs=(f"audit:{audit_id}",),
            )

        verdict = self._t0_engine.evaluate(
            event_id=str(event.event_id),
            signal_id=str(event.event_id),
            resource_id=resource_id,
            resource_type=routing.resource_type,
            resource_props=dict(raw_props),
            signal_type=signal_type,
        )

        findings_summary: list[dict[str, Any]] = []
        pr_intents: list[dict[str, Any]] = []
        errors: list[str] = []
        for finding in verdict.findings:
            summary = {
                "rule_id": finding.rule_id,
                "resource_id": finding.resource_id,
                "severity": _enum_value(finding.severity),
            }
            findings_summary.append(summary)
            evidence.append(f"rule:{finding.rule_id}")
            rule = self._rules_by_id.get(finding.rule_id)
            if rule is None:
                errors.append(
                    f"rule {finding.rule_id!r} not in rules_by_id; cannot render a PR intent"
                )
                continue
            try:
                action = self._action_builder.build_from_finding(
                    event=event, finding=finding, rule=rule
                )
            except ActionBuildError as exc:
                errors.append(f"ActionBuild failed for rule {finding.rule_id!r}: {exc}")
                continue
            try:
                patch = self._template_renderer.render(
                    RenderRequest(
                        rule=rule,
                        resource_id=finding.resource_id,
                        params=dict(action.params),
                    )
                )
            except RenderError as exc:
                errors.append(f"Template render failed for rule {finding.rule_id!r}: {exc}")
                continue
            pr_intents.append(
                {
                    "action_id": str(action.action_id),
                    "action_type": action.action_type,
                    "target_resource_ref": action.target_resource_ref,
                    "citing_rule_ids": list(action.citing_rules),
                    "idempotency_key": action.idempotency_key,
                    "stop_condition": action.stop_condition,
                    "rollback_kind": _enum_value(action.rollback_ref.kind),
                    "patch_preview": _preview(patch),
                    "template_ref": rule.remediation.template_ref,
                }
            )

        result["findings"] = findings_summary
        result["pr_intents"] = pr_intents
        result["errors"] = errors

        if not verdict.findings:
            outcome = "abstained_t0"
            preview = (
                f"simulate_change[{resource_type}/{resource_id}]: T0 abstain "
                f"({len(routing.candidate_rule_ids)} candidate rule(s))"
            )
            status: Literal["ok", "error", "abstain"] = "abstain"
        elif errors and not pr_intents:
            # Every finding failed to build or render - fail-close as error.
            outcome = "abstained_t0"
            preview = (
                f"simulate_change[{resource_type}/{resource_id}]: "
                f"{len(errors)} error(s) building/rendering; no PR intent"
            )
            status = "error"
        else:
            outcome = "simulated"
            preview = (
                f"simulate_change[{resource_type}/{resource_id}]: "
                f"{len(pr_intents)} PR intent(s) captured, "
                f"{len(errors)} error(s)"
            )
            status = "ok"

        audit_id = self._audit_writer.write_simulation_entry(
            event=event,
            principal=principal,
            outcome=outcome,
            reason=verdict.audit_hint.reason if verdict.audit_hint else None,
            citing_rule_ids=tuple(verdict.audit_hint.citing_rule_ids if verdict.audit_hint else ()),
            pr_intents=tuple(pr_intents),
            findings_summary=tuple(findings_summary),
        )
        result["outcome"] = outcome
        result["audit_id"] = audit_id

        return ToolResult(
            status=status,
            data=result,
            preview=preview,
            evidence_refs=tuple(evidence) + (f"audit:{audit_id}",),
        )


# ---------------------------------------------------------------------------
# audit writer seam
# ---------------------------------------------------------------------------


class AuditWriter:
    """Sync facade over an async :class:`StateStore` for the console.

    The console runs sync at Day 1 (see
    :class:`~aiopspilot.core.conversation.tools.SystemConsoleTool`); the
    audit store is async by contract. This adapter marshals one write
    per call via ``asyncio.run`` - safe because the console coordinator
    is never itself inside an event loop, matching the pattern
    :class:`~aiopspilot.core.conversation.system_tools.QueryInventoryTool`
    already uses.

    A fork that runs the console inside an event loop (Teams / Slack
    bot) can override the adapter to write directly via ``await``; the
    Protocol shape is one method.
    """

    def __init__(self, *, audit_store: Any) -> None:
        # Typed as Any to keep the tool module free of a compile-time
        # dependency on the StateStore Protocol path; the runtime object
        # is a StateStore. This mirrors the pattern used by the read-only
        # audit tools.
        self._audit_store = audit_store

    def write_simulation_entry(
        self,
        *,
        event: Event,
        principal: Principal,
        outcome: str,
        reason: str | None,
        citing_rule_ids: tuple[str, ...],
        pr_intents: tuple[Mapping[str, Any], ...],
        findings_summary: tuple[Mapping[str, Any], ...],
    ) -> str:
        import asyncio

        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "event_id": str(event.event_id),
            "action_kind": "console.simulate_change",
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": outcome,
            "mode": Mode.SHADOW.value,
            "stage": "simulate",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "resource_type": _extract_resource_type(event),
            "citing_rule_ids": list(citing_rule_ids),
            "reason": reason or "",
            "pr_intents": [dict(p) for p in pr_intents],
            "findings": [dict(f) for f in findings_summary],
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_synthetic_event(
    *,
    resource_type: str,
    resource_id: str,
    resource_props: Mapping[str, Any],
    signal_type: str,
    extra_payload: Mapping[str, Any],
) -> Event:
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "resource": {"type": resource_type, "id": resource_id},
        "properties": dict(resource_props),
    }
    for key, value in extra_payload.items():
        if key not in payload:
            payload[key] = value
    return Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key=f"chat.simulate_change.{uuid4().hex[:16]}",
        source="operator-console",
        event_type=signal_type,
        resource_ref=resource_id,
        payload=payload,
        detected_at=now,
        ingested_at=now,
        mode=Mode.SHADOW,
    )


def _extract_resource_type(event: Event) -> str:
    resource = event.payload.get("resource")
    if isinstance(resource, Mapping):
        maybe_type = resource.get("type")
        if isinstance(maybe_type, str):
            return maybe_type
    return ""


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _preview(patch: str, *, max_bytes: int = 512) -> str:
    """Short, safe preview of a rendered template.

    Never returns more than ``max_bytes`` characters; a longer patch is
    trimmed to keep audit entries bounded.
    """
    trimmed = patch.strip()
    if len(trimmed) <= max_bytes:
        return trimmed
    return trimmed[:max_bytes] + "..."


# Re-export UUID for symmetry with ``system_tools``.
_ = UUID


__all__ = [
    "AuditWriter",
    "SimulateChangeTool",
]
