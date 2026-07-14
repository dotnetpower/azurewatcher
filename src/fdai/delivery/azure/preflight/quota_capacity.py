"""Live Azure quota / capacity probe (QUOTA_CAPACITY, shadow-first).

Realizes the :class:`~fdai.shared.providers.feasibility_probe.FeasibilityProbe`
Protocol against the **real Compute usages** endpoint for a subscription +
location. For each configured quota check, it reads the current usage and limit
and emits a grounded blocking finding when the deployment's required headroom
would exceed the limit.

There is no autofix toggle for a quota block (you cannot terraform your way past
a subscription limit), so findings resolve to ``MANUAL`` guidance and route to
``hil`` - matching the ``quota_capacity`` row proven in the OPA-emulated matrix.

Shadow-first, read-only, fail-closed: a raised :class:`AzurePreflightError`
propagates so the pass never reports a false ``clear``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fdai.delivery.azure.preflight._client import AzureArmClient
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    PreflightTarget,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)

_DEFAULT_USAGES_API = "2023-07-01"


@dataclass(frozen=True, slots=True)
class QuotaCheck:
    """One quota to verify: the usage name and the headroom the deploy needs.

    ``quota_name`` is the Azure usage ``name.value`` (e.g.
    ``standardDSv3Family`` or ``cores``). ``required`` is how many units the
    deployment will consume; a finding fires when ``current + required > limit``.
    """

    quota_name: str
    required: int = 1

    def __post_init__(self) -> None:
        if not self.quota_name.strip():
            raise ValueError("quota_name MUST NOT be empty")
        if self.required < 1:
            raise ValueError("required MUST be >= 1")


@dataclass(frozen=True, slots=True)
class AzureQuotaProbeConfig:
    """Subscription + location + the set of quota checks to run."""

    subscription_id: str
    location: str
    checks: tuple[QuotaCheck, ...]
    usages_api_version: str = _DEFAULT_USAGES_API

    def __post_init__(self) -> None:
        if not self.subscription_id.strip():
            raise ValueError("subscription_id MUST NOT be empty")
        if not self.location.strip():
            raise ValueError("location MUST NOT be empty")
        if not self.checks:
            raise ValueError("checks MUST NOT be empty")


class AzureQuotaProbe:
    """Read real Compute usages and report quota blockers for the deploy."""

    def __init__(self, *, client: AzureArmClient, config: AzureQuotaProbeConfig) -> None:
        self._client = client
        self._config = config

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.QUOTA_CAPACITY

    async def evaluate(self, target: PreflightTarget) -> Sequence[ProbeFinding]:
        del target  # quota checks are scope+location config, not per-target-type
        usages = await self._client.get_values(
            f"/subscriptions/{self._config.subscription_id}/providers/Microsoft.Compute"
            f"/locations/{self._config.location}/usages",
            api_version=self._config.usages_api_version,
        )
        by_name = _index_by_name(usages)
        findings: list[ProbeFinding] = []
        for check in self._config.checks:
            usage = by_name.get(check.quota_name.casefold())
            if usage is None:
                continue
            current, limit = usage
            if current + check.required > limit:
                findings.append(self._finding(check, current, limit))
        return tuple(sorted(findings, key=lambda f: f.id))

    def _finding(self, check: QuotaCheck, current: int, limit: int) -> ProbeFinding:
        location = self._config.location
        return ProbeFinding(
            id=f"quota:{check.quota_name}@{location}",
            category=ProbeCategory.QUOTA_CAPACITY,
            severity=FindingSeverity.BLOCKING,
            title=f"quota {check.quota_name} exhausted in {location}",
            evidence=ProbeEvidence(
                source=f"quota:{check.quota_name}@{location}",
                detail=(
                    f"usage {current}/{limit}; deploy needs {check.required} more, "
                    "which exceeds the limit"
                ),
            ),
            resolution=ProbeResolution(
                kind=ResolutionKind.MANUAL,
                guidance=(
                    f"request a quota increase for {check.quota_name!r} in {location}, "
                    "or deploy to a region/SKU with headroom"
                ),
            ),
        )


def _index_by_name(usages: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Map a lowercased usage name to ``(current, limit)``, skipping malformed rows."""
    index: dict[str, tuple[int, int]] = {}
    for usage in usages:
        name = usage.get("name")
        value = name.get("value") if isinstance(name, dict) else None
        current = usage.get("currentValue")
        limit = usage.get("limit")
        if (
            isinstance(value, str)
            and isinstance(current, (int, float))
            and not isinstance(current, bool)
            and isinstance(limit, (int, float))
            and not isinstance(limit, bool)
        ):
            index[value.casefold()] = (int(current), int(limit))
    return index


__all__ = ["AzureQuotaProbe", "AzureQuotaProbeConfig", "QuotaCheck"]
