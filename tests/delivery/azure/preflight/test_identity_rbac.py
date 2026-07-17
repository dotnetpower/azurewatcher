"""Identity RBAC preflight findings from Resource Graph observations."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from fdai.core.onboarding import ObservedRoleAssignment, OnboardingResourceKind
from fdai.delivery.azure.preflight.identity_rbac import AzureIdentityRbacProbe
from fdai.shared.providers.feasibility_probe import PreflightTarget, ProbeCategory


@dataclass
class _Reader:
    assignments: tuple[ObservedRoleAssignment, ...] = ()
    error: Exception | None = None

    async def observed_role_assignments(self) -> tuple[ObservedRoleAssignment, ...]:
        if self.error is not None:
            raise self.error
        return self.assignments


def _assignment(role: str, scope_kind: OnboardingResourceKind) -> ObservedRoleAssignment:
    return ObservedRoleAssignment(
        principal_ref="executor",
        role=role,
        scope_kind=scope_kind,
    )


async def test_missing_roles_are_grounded_without_principal_identifiers() -> None:
    probe = AzureIdentityRbacProbe(reader=_Reader())

    findings = await probe.evaluate(PreflightTarget(scope="example"))

    assert [finding.id for finding in findings] == [
        "missing-executor-role:event_bus_data_owner",
        "missing-executor-role:secret_reader",
    ]
    assert all(finding.category is ProbeCategory.IDENTITY_RBAC for finding in findings)
    assert all(
        finding.evidence.source == "azure-resource-graph:role-assignments" for finding in findings
    )
    assert "principal" not in " ".join(finding.title for finding in findings)


async def test_observed_roles_are_clear() -> None:
    probe = AzureIdentityRbacProbe(
        reader=_Reader(
            assignments=(
                _assignment("event_bus_data_owner", OnboardingResourceKind.EVENT_BUS),
                _assignment("secret_reader", OnboardingResourceKind.SECRET_STORE),
            )
        )
    )

    assert await probe.evaluate(PreflightTarget(scope="example")) == ()


async def test_reader_failure_propagates_fail_closed() -> None:
    probe = AzureIdentityRbacProbe(reader=_Reader(error=RuntimeError("unavailable")))

    with pytest.raises(RuntimeError, match="unavailable"):
        await probe.evaluate(PreflightTarget(scope="example"))
