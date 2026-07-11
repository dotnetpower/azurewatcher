"""Governance scope - which resources an assignment covers, CSP-neutrally.

An assignment binds a rule/rule-set to a **scope** with an **effect**
(rule-governance.md "Scope"). This module is the pure selection layer: the scope
hierarchy, the selectors, exclusions, and the specificity used for precedence
(most-specific scope wins for parameters; the strictest effect - see
:mod:`fdai.rule_catalog.schema.effect` - wins for conflicting effects; a genuine
tie escalates to HIL).

Pure and I/O-free: ``Scope.covers`` is a deterministic predicate over a
:class:`ResourceContext` (the target's hierarchy + type + tags), so the loader,
the CI gate, and a what-if evaluation share one source of truth. Scope is data;
a broad scope never widens the executor's least-privilege identity
(security-and-identity.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum


class ScopeLevel(IntEnum):
    """The CSP-neutral scope hierarchy, ordered least to most specific.

    Higher value = more specific, so ``max`` over the levels yields the
    most-specific scope for precedence.
    """

    ORGANIZATION = 0
    ACCOUNT = 1  # account / subscription
    RESOURCE_GROUP = 2
    RESOURCE = 3


@dataclass(frozen=True, slots=True)
class ScopeSelector:
    """Narrows a scope within its level (rule-governance.md "Selectors").

    A selector matches a resource when **every declared** criterion matches
    (declared = non-empty); an empty criterion imposes no constraint. An empty
    selector matches every resource in the scope.
    """

    resource_types: frozenset[str] = frozenset()
    tags: Mapping[str, str] = field(default_factory=dict)
    resource_ids: frozenset[str] = frozenset()

    def matches(self, ctx: ResourceContext) -> bool:
        if self.resource_types and ctx.resource_type not in self.resource_types:
            return False
        if self.resource_ids and ctx.resource_id not in self.resource_ids:
            return False
        for key, value in self.tags.items():
            if ctx.tags.get(key) != value:
                return False
        return True


@dataclass(frozen=True, slots=True)
class ResourceContext:
    """The target resource evaluated against a scope - its full hierarchy path
    plus type and tags. CSP-neutral: the ids are neutral scope ids and the
    ``resource_type`` is the vocabulary label."""

    organization: str
    account: str
    resource_group: str
    resource_id: str
    resource_type: str
    tags: Mapping[str, str] = field(default_factory=dict)

    def id_at(self, level: ScopeLevel) -> str:
        """Return this resource's id at the given hierarchy level."""
        return {
            ScopeLevel.ORGANIZATION: self.organization,
            ScopeLevel.ACCOUNT: self.account,
            ScopeLevel.RESOURCE_GROUP: self.resource_group,
            ScopeLevel.RESOURCE: self.resource_id,
        }[level]


@dataclass(frozen=True, slots=True)
class Scope:
    """A CSP-neutral scope: a hierarchy level + id, optional selector, and
    optional excluded child scope ids."""

    level: ScopeLevel
    id: str
    selector: ScopeSelector | None = None
    excludes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Scope.id MUST be non-empty")

    def covers(self, ctx: ResourceContext) -> bool:
        """True when this scope covers the resource.

        The scope's level id must equal the resource's id at that level
        (ancestor-or-self); the resource must not fall under an excluded child
        scope (any of its at-or-below hierarchy ids in ``excludes``); and the
        selector, if any, must match.
        """
        if ctx.id_at(self.level) != self.id:
            return False
        if self.excludes:
            for level in ScopeLevel:
                if level >= self.level and ctx.id_at(level) in self.excludes:
                    return False
        if self.selector is not None and not self.selector.matches(ctx):
            return False
        return True


def scope_specificity(scope: Scope) -> int:
    """Higher = more specific (resource > resource-group > account > org)."""
    return int(scope.level)


def most_specific(scopes: Iterable[Scope]) -> tuple[Scope, ...]:
    """Return every scope tied at the highest specificity.

    ``len == 1`` -> a unique most-specific scope wins for parameters. ``len > 1``
    -> a genuine specificity tie: the caller escalates parameter conflicts to HIL
    while :func:`fdai.rule_catalog.schema.effect.strictest_effect` resolves the
    effect. Empty input -> empty tuple.
    """
    ordered = list(scopes)
    if not ordered:
        return ()
    top = max(scope_specificity(s) for s in ordered)
    return tuple(s for s in ordered if scope_specificity(s) == top)


__all__ = [
    "ResourceContext",
    "Scope",
    "ScopeLevel",
    "ScopeSelector",
    "most_specific",
    "scope_specificity",
]
