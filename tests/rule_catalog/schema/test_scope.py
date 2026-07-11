"""Governance scope: coverage predicate, selectors, exclusions, specificity."""

from __future__ import annotations

import pytest

from fdai.rule_catalog.schema.scope import (
    ResourceContext,
    Scope,
    ScopeLevel,
    ScopeSelector,
    most_specific,
    scope_specificity,
)


def _ctx(
    *,
    org: str = "org-1",
    account: str = "sub-1",
    rg: str = "rg-a",
    resource: str = "vm-1",
    rtype: str = "compute",
    tags: dict[str, str] | None = None,
) -> ResourceContext:
    return ResourceContext(
        organization=org,
        account=account,
        resource_group=rg,
        resource_id=resource,
        resource_type=rtype,
        tags=tags or {},
    )


def test_specificity_ordering() -> None:
    assert scope_specificity(Scope(level=ScopeLevel.RESOURCE, id="vm-1")) > scope_specificity(
        Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")
    )
    assert scope_specificity(Scope(level=ScopeLevel.ACCOUNT, id="sub-1")) > scope_specificity(
        Scope(level=ScopeLevel.ORGANIZATION, id="org-1")
    )


def test_covers_at_each_level() -> None:
    ctx = _ctx()
    assert Scope(level=ScopeLevel.ORGANIZATION, id="org-1").covers(ctx)
    assert Scope(level=ScopeLevel.ACCOUNT, id="sub-1").covers(ctx)
    assert Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a").covers(ctx)
    assert Scope(level=ScopeLevel.RESOURCE, id="vm-1").covers(ctx)


def test_covers_rejects_non_matching_id() -> None:
    ctx = _ctx()
    assert not Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-other").covers(ctx)
    assert not Scope(level=ScopeLevel.ACCOUNT, id="sub-other").covers(ctx)


def test_selector_resource_type() -> None:
    ctx = _ctx(rtype="compute")
    covering = Scope(
        level=ScopeLevel.RESOURCE_GROUP,
        id="rg-a",
        selector=ScopeSelector(resource_types=frozenset({"compute"})),
    )
    assert covering.covers(ctx)
    non = Scope(
        level=ScopeLevel.RESOURCE_GROUP,
        id="rg-a",
        selector=ScopeSelector(resource_types=frozenset({"storage"})),
    )
    assert not non.covers(ctx)


def test_selector_tags_and_ids_are_anded() -> None:
    ctx = _ctx(tags={"env": "prod", "team": "a"})
    # all declared tags must match
    ok = Scope(
        level=ScopeLevel.ACCOUNT,
        id="sub-1",
        selector=ScopeSelector(tags={"env": "prod"}),
    )
    assert ok.covers(ctx)
    bad = Scope(
        level=ScopeLevel.ACCOUNT,
        id="sub-1",
        selector=ScopeSelector(tags={"env": "dev"}),
    )
    assert not bad.covers(ctx)
    # resource-id allowlist
    id_ok = Scope(
        level=ScopeLevel.RESOURCE_GROUP,
        id="rg-a",
        selector=ScopeSelector(resource_ids=frozenset({"vm-1"})),
    )
    assert id_ok.covers(ctx)
    id_bad = Scope(
        level=ScopeLevel.RESOURCE_GROUP,
        id="rg-a",
        selector=ScopeSelector(resource_ids=frozenset({"vm-2"})),
    )
    assert not id_bad.covers(ctx)


def test_empty_selector_matches_everything_in_scope() -> None:
    ctx = _ctx()
    assert Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a", selector=ScopeSelector()).covers(ctx)


def test_exclusion_of_child_scope() -> None:
    ctx = _ctx(rg="rg-sandbox")
    # org-wide but exclude a sandbox resource group
    scope = Scope(
        level=ScopeLevel.ORGANIZATION,
        id="org-1",
        excludes=frozenset({"rg-sandbox"}),
    )
    assert not scope.covers(ctx)
    # a resource NOT in the excluded rg is still covered
    assert scope.covers(_ctx(rg="rg-a"))


def test_exclusion_of_specific_resource() -> None:
    scope = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a", excludes=frozenset({"vm-1"}))
    assert not scope.covers(_ctx(resource="vm-1"))
    assert scope.covers(_ctx(resource="vm-2"))


def test_most_specific_unique_and_tie() -> None:
    org = Scope(level=ScopeLevel.ORGANIZATION, id="org-1")
    rg = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")
    res = Scope(level=ScopeLevel.RESOURCE, id="vm-1")
    winners = most_specific([org, rg, res])
    assert winners == (res,)  # unique most-specific
    # a genuine tie at the same level surfaces both
    rg2 = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a", selector=ScopeSelector())
    tie = most_specific([org, rg, rg2])
    assert len(tie) == 2 and rg in tie and rg2 in tie
    assert most_specific([]) == ()


def test_scope_id_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="Scope.id MUST be non-empty"):
        Scope(level=ScopeLevel.RESOURCE, id="  ")
