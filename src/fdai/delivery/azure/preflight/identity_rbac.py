"""Resource Graph-backed executor role checks for deployment preflight."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from fdai.core.onboarding import ObservedRoleAssignment, OnboardingResourceKind
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    PreflightTarget,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)


class RoleAssignmentReader(Protocol):
    async def observed_role_assignments(self) -> tuple[ObservedRoleAssignment, ...]: ...


_REQUIRED_ROLES = (
    ("event_bus_data_owner", OnboardingResourceKind.EVENT_BUS),
    ("secret_reader", OnboardingResourceKind.SECRET_STORE),
)


@dataclass(frozen=True, slots=True)
class AzureIdentityRbacProbe:
    """Report missing executor roles without exposing Azure identifiers."""

    reader: RoleAssignmentReader

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.IDENTITY_RBAC

    async def evaluate(self, target: PreflightTarget) -> Sequence[ProbeFinding]:
        del target
        observed = {
            (assignment.role, assignment.scope_kind)
            for assignment in await self.reader.observed_role_assignments()
        }
        findings = [
            self._finding(role, scope_kind)
            for role, scope_kind in _REQUIRED_ROLES
            if (role, scope_kind) not in observed
        ]
        return tuple(sorted(findings, key=lambda finding: finding.id))

    @staticmethod
    def _finding(role: str, scope_kind: OnboardingResourceKind) -> ProbeFinding:
        return ProbeFinding(
            id=f"missing-executor-role:{role}",
            category=ProbeCategory.IDENTITY_RBAC,
            severity=FindingSeverity.BLOCKING,
            title=f"executor is missing required {role} access",
            evidence=ProbeEvidence(
                source="azure-resource-graph:role-assignments",
                detail=f"no {role} assignment was observed on the {scope_kind.value} scope",
            ),
            resolution=ProbeResolution(
                kind=ResolutionKind.MANUAL,
                guidance=(
                    f"grant the approved {role} role to the executor on the "
                    f"{scope_kind.value} scope and rerun preflight"
                ),
            ),
        )


__all__ = ["AzureIdentityRbacProbe", "RoleAssignmentReader"]
