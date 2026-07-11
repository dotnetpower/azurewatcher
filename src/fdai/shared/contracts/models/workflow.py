"""Workflow contract - a declarative business process.

Ordered list of :class:`WorkflowStep`, each referencing one ontology
:class:`~fdai.shared.contracts.models.ontology.OntologyActionType`, plus a
trigger, a promotion gate, and a default mode. Structural invariants
(unique step ids; every ``on_failure`` target exists and appears later in
the list, so a fallback never re-runs an already-applied step) are
enforced here; cross-references to the ActionType and rule catalogs are
enforced by the loader in :mod:`fdai.rule_catalog.schema.workflow`.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from ._base import SemVer, _Base
from .enums import Mode, WorkflowTriggerKind
from .ontology import PromotionGate


class WorkflowTrigger(_Base):
    """The event or schedule that starts a Workflow run."""

    kind: WorkflowTriggerKind
    signal_type: str | None = None
    schedule: str | None = None

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> WorkflowTrigger:
        if self.kind is WorkflowTriggerKind.SIGNAL and not self.signal_type:
            raise ValueError("trigger.kind=signal requires a non-empty signal_type")
        if self.kind is WorkflowTriggerKind.SCHEDULE and not self.schedule:
            raise ValueError("trigger.kind=schedule requires a non-empty schedule")
        return self


class WorkflowStep(_Base):
    """One step in a Workflow: an ActionType invocation plus optional
    guard, saga-compensation, and on-failure branch. A step never carries
    its own mutation logic - it delegates to ``action_type_ref`` so it
    inherits that ActionType's four safety invariants."""

    id: Annotated[str, Field(min_length=1)]
    action_type_ref: Annotated[str, Field(min_length=1)]
    guard_rule_ref: str | None = None
    compensated_by: str | None = None
    on_failure: str | None = None
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class Workflow(_Base):
    """A declarative business process (process-automation.md 2)."""

    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]
    version: SemVer
    trigger: WorkflowTrigger
    default_mode: Mode = Mode.SHADOW
    promotion_gate: PromotionGate
    steps: Annotated[list[WorkflowStep], Field(min_length=1)]
    description: Annotated[str, Field(max_length=200)] | None = None
    anti_scope: str | None = None

    @model_validator(mode="after")
    def _structural_invariants(self) -> Workflow:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"duplicate step id {step.id!r}")
            seen.add(step.id)
        index_by_id = {step.id: i for i, step in enumerate(self.steps)}
        for i, step in enumerate(self.steps):
            if step.on_failure is None:
                continue
            if step.on_failure == step.id:
                raise ValueError(
                    f"step {step.id!r} on_failure points at itself; "
                    "a step cannot be its own failure fallback"
                )
            if step.on_failure not in seen:
                raise ValueError(f"step {step.id!r} on_failure -> unknown step {step.on_failure!r}")
            if index_by_id[step.on_failure] <= i:
                raise ValueError(
                    f"step {step.id!r} on_failure -> {step.on_failure!r} must appear "
                    "later in the workflow; a backward fallback would re-run an "
                    "already-applied step"
                )
        return self


__all__ = ["Workflow", "WorkflowStep", "WorkflowTrigger"]
