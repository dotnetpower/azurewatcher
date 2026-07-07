"""Bootstrap resolver - deployer-scoped LLM capability resolution.

Pure-function core; SDK bindings sit at the edges. Given a
:class:`~fdai.rule_catalog.schema.llm_registry.LlmRegistry` and three
:class:`Protocol`-shaped query surfaces (catalog / permission / quota),
:func:`resolve` picks one deployment per capability, enforces the five
deployer-permission gates from
[dev-and-deploy-parity.md § Deployer-Scoped LLM Provisioning](
../../../../docs/roadmap/dev-and-deploy-parity.md#deployer-scoped-llm-provisioning),
and returns a deterministic :class:`ResolvedModels` record ready for
serialization to ``resolved-models.json``.

Rules the resolver enforces (MUST):

- **Missing deployer principal or missing `Cognitive Services Contributor`
  role** on the target subscription: every capability degrades to
  ``hil-only``; the resolver DOES NOT raise (fork can grant the role
  later and re-run). No LLM deployment is proposed.
- **Region missing every preferred family** for a capability: that
  capability degrades to ``hil-only``; others keep going.
- **Insufficient quota**: reduce to the largest available capacity that
  is at least 20% of the requested ``capacity_tpm``; below that floor,
  refuse and mark ``hil-only``.
- **Mixed-model invariant** (`t2.reasoner.primary.publisher !=
  t2.reasoner.secondary.publisher`) after resolution: raise
  :class:`ResolverError` - do NOT partially deploy a T2 tier that would
  fail the quality gate.

The output is deterministic: same registry + region + subscription +
catalog snapshot → identical :class:`ResolvedModels`. That is what makes
the CI idempotency gate meaningful.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.rule_catalog.schema.llm_registry import (
    LlmRegistry,
    MixedModelMode,
)

_MIN_QUOTA_RATIO = 0.2
"""Floor: challenger capacity must be at least this share of requested."""


class ResolverError(RuntimeError):
    """Raised when a hard invariant fails (e.g. mixed-model publishers)."""


class CapabilityStatus(StrEnum):
    RESOLVED = "resolved"
    """A deployment is provisioned for this capability."""

    HIL_ONLY = "hil-only"
    """No deployment; the tier's traffic MUST route to HIL."""

    CAPACITY_REDUCED = "capacity-reduced"
    """A deployment is provisioned with reduced capacity_tpm."""


# ---------------------------------------------------------------------------
# DI seams - three tiny Protocols so tests never need Azure SDKs.
# ---------------------------------------------------------------------------


@runtime_checkable
class CatalogQuery(Protocol):
    """Which model families are available in the target region."""

    def families_in_region(self, region: str) -> set[str]: ...


@runtime_checkable
class PermissionQuery(Protocol):
    """Whether the deployer holds provisioning permission on the subscription."""

    def principal_has_cognitive_services_contributor(
        self, *, subscription_id: str, principal_object_id: str
    ) -> bool: ...


@runtime_checkable
class QuotaQuery(Protocol):
    """Available capacity_tpm for (region, publisher, family) - 0 = none."""

    def available_capacity_tpm(self, *, region: str, publisher: str, family: str) -> int: ...


# ---------------------------------------------------------------------------
# Frozen output records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedCapability:
    """One capability's resolution outcome."""

    name: str
    status: CapabilityStatus
    publisher: str | None
    family: str | None
    sku: str | None
    capacity_tpm: int
    invocation: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Human-readable breadcrumbs written into the audit entry."""


@dataclass(frozen=True, slots=True)
class ResolvedModels:
    """Deterministic serializable resolver output."""

    schema_version: str
    region: str
    subscription_id: str
    deployer_object_id: str
    mixed_model_mode: str
    capabilities: tuple[ResolvedCapability, ...]

    def to_json(self) -> str:
        """JSON with sorted keys - same input yields the same bytes."""
        payload = {
            "schema_version": self.schema_version,
            "region": self.region,
            "subscription_id": self.subscription_id,
            "deployer_object_id": self.deployer_object_id,
            "mixed_model_mode": self.mixed_model_mode,
            "capabilities": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "publisher": c.publisher,
                    "family": c.family,
                    "sku": c.sku,
                    "capacity_tpm": c.capacity_tpm,
                    "invocation": c.invocation,
                    "reasons": list(c.reasons),
                }
                for c in self.capabilities
            ],
        }
        return json.dumps(payload, sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> ResolvedModels:
        raw = json.loads(text)
        return cls(
            schema_version=str(raw["schema_version"]),
            region=str(raw["region"]),
            subscription_id=str(raw["subscription_id"]),
            deployer_object_id=str(raw["deployer_object_id"]),
            mixed_model_mode=str(raw["mixed_model_mode"]),
            capabilities=tuple(
                ResolvedCapability(
                    name=str(c["name"]),
                    status=CapabilityStatus(c["status"]),
                    publisher=c.get("publisher"),
                    family=c.get("family"),
                    sku=c.get("sku"),
                    capacity_tpm=int(c["capacity_tpm"]),
                    invocation=str(c["invocation"]),
                    reasons=tuple(str(r) for r in c.get("reasons", ())),
                )
                for c in raw["capabilities"]
            ),
        )


# ---------------------------------------------------------------------------
# Core resolver
# ---------------------------------------------------------------------------


def resolve(
    *,
    registry: LlmRegistry,
    region: str,
    subscription_id: str,
    deployer_object_id: str,
    catalog: CatalogQuery,
    permission: PermissionQuery,
    quota: QuotaQuery,
) -> ResolvedModels:
    """Produce a :class:`ResolvedModels` for the target deployment.

    Never raises for "environmental" failures (missing role, missing
    family, low quota) - those degrade the affected capability to
    ``hil-only`` and continue. Raises :class:`ResolverError` only when
    the mixed-model invariant cannot hold at deployment time.
    """
    has_perm = permission.principal_has_cognitive_services_contributor(
        subscription_id=subscription_id,
        principal_object_id=deployer_object_id,
    )
    catalog_families = catalog.families_in_region(region)

    entries: list[ResolvedCapability] = []
    # Sort capabilities by name so the output is deterministic regardless
    # of dict iteration order in the source YAML.
    for name in sorted(registry.models):
        spec = registry.models[name]
        if not has_perm:
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=None,
                    family=None,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(
                        f"deployer_lacks_cognitive_services_contributor:sub={subscription_id}",
                    ),
                )
            )
            continue

        chosen_pub: str | None = None
        chosen_family: str | None = None
        for pref in spec.preferences:
            if pref.family in catalog_families:
                chosen_pub = pref.publisher
                chosen_family = pref.family
                break
        if chosen_family is None:
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=None,
                    family=None,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(
                        f"no_preferred_family_in_region:region={region}:"
                        f"preferences={[p.family for p in spec.preferences]}",
                    ),
                )
            )
            continue

        available = quota.available_capacity_tpm(
            region=region, publisher=chosen_pub or "", family=chosen_family
        )
        floor = int(spec.capacity_tpm * _MIN_QUOTA_RATIO)
        if available <= 0:
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=chosen_pub,
                    family=chosen_family,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(f"zero_quota:family={chosen_family}:region={region}",),
                )
            )
            continue

        if available < floor:
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=chosen_pub,
                    family=chosen_family,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(
                        f"quota_below_min_ratio:available={available}<"
                        f"floor={floor}:requested={spec.capacity_tpm}",
                    ),
                )
            )
            continue

        effective = min(spec.capacity_tpm, available)
        status = (
            CapabilityStatus.RESOLVED
            if effective == spec.capacity_tpm
            else CapabilityStatus.CAPACITY_REDUCED
        )
        reasons: tuple[str, ...] = ()
        if status is CapabilityStatus.CAPACITY_REDUCED:
            reasons = (f"capacity_reduced:requested={spec.capacity_tpm}:effective={effective}",)
        entries.append(
            ResolvedCapability(
                name=name,
                status=status,
                publisher=chosen_pub,
                family=chosen_family,
                sku=spec.sku.value,
                capacity_tpm=effective,
                invocation=spec.invocation.value,
                reasons=reasons,
            )
        )

    # Mixed-model invariant: hard error unless mode is hil-only.
    if registry.mixed_model_mode is not MixedModelMode.HIL_ONLY:
        _enforce_mixed_model_invariant(entries)

    return ResolvedModels(
        schema_version="1.0.0",
        region=region,
        subscription_id=subscription_id,
        deployer_object_id=deployer_object_id,
        mixed_model_mode=registry.mixed_model_mode.value,
        capabilities=tuple(entries),
    )


def _enforce_mixed_model_invariant(entries: list[ResolvedCapability]) -> None:
    """Raise :class:`ResolverError` when both reasoners resolved to the same publisher."""
    by_name: Mapping[str, ResolvedCapability] = {e.name: e for e in entries}
    primary = by_name.get("t2.reasoner.primary")
    secondary = by_name.get("t2.reasoner.secondary")
    if primary is None or secondary is None:
        return
    # Only the two RESOLVED cases can violate the invariant. If either
    # is hil-only the invariant is not applicable - the T2 tier already
    # can't auto-execute for the affected capability.
    if (
        primary.status in (CapabilityStatus.RESOLVED, CapabilityStatus.CAPACITY_REDUCED)
        and secondary.status in (CapabilityStatus.RESOLVED, CapabilityStatus.CAPACITY_REDUCED)
        and primary.publisher is not None
        and primary.publisher == secondary.publisher
    ):
        raise ResolverError(
            "mixed_model_invariant_violated_after_resolve: "
            f"primary.publisher={primary.publisher!r} == "
            f"secondary.publisher={secondary.publisher!r}. Expand "
            "llm-registry.yaml preferences so a distinct publisher can be "
            "picked in this region, or set mixed_model_mode='hil-only'."
        )


__all__ = [
    "CapabilityStatus",
    "CatalogQuery",
    "PermissionQuery",
    "QuotaQuery",
    "ResolvedCapability",
    "ResolvedModels",
    "ResolverError",
    "resolve",
]
