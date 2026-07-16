"""Human identity directory composition for the local read API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from fdai.core.rbac.resolver import GroupMapping
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.identity import EntraHumanIdentityDirectory
from fdai.shared.providers.human_identity import (
    HumanIdentity,
    HumanIdentityDirectory,
    IdentityRosterEntry,
    StaticHumanIdentityDirectory,
)


@dataclass(frozen=True, slots=True)
class LocalIamDirectory:
    directory: HumanIdentityDirectory
    role_group_ids: dict[str, str]
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()


def build_local_iam_directory(
    group_mapping: GroupMapping,
    *,
    use_graph: bool,
) -> LocalIamDirectory:
    role_group_ids = {
        "Reader": group_mapping.reader_group_id,
        "Contributor": group_mapping.contributor_group_id,
        "Approver": group_mapping.approver_group_id,
        "Owner": group_mapping.owner_group_id,
        "BreakGlass": group_mapping.break_glass_group_id,
    }
    if not use_graph:
        return LocalIamDirectory(
            directory=_static_iam_directory(),
            role_group_ids=role_group_ids,
        )

    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0))
    directory = EntraHumanIdentityDirectory(
        client=client,
        identity=AsyncAzureCliWorkloadIdentity(),
    )

    async def close() -> None:
        await client.aclose()

    return LocalIamDirectory(
        directory=directory,
        role_group_ids=role_group_ids,
        shutdown_callbacks=(close,),
    )


def _static_iam_directory() -> StaticHumanIdentityDirectory:
    return StaticHumanIdentityDirectory(
        (
            HumanIdentity(
                provider="entra",
                subject_id="00000000-0000-0000-0000-000000000001",
                username="alex@example.com",
                display_name="Alex Kim",
            ),
            HumanIdentity(
                provider="entra",
                subject_id="00000000-0000-0000-0000-000000000002",
                username="casey@example.com",
                display_name="Casey Park",
                user_type="guest",
            ),
        ),
        roster=(
            IdentityRosterEntry(
                provider="entra",
                subject_id="00000000-0000-0000-0000-000000000101",
                display_name="fdai-readers",
                principal_type="group",
                roles=("Reader",),
            ),
            IdentityRosterEntry(
                provider="entra",
                subject_id="00000000-0000-0000-0000-000000000102",
                display_name="fdai-owners",
                principal_type="group",
                roles=("Owner",),
            ),
            IdentityRosterEntry(
                provider="entra",
                subject_id="00000000-0000-0000-0000-000000000001",
                display_name="Alex Kim",
                principal_type="person",
                roles=("Reader",),
                username="alex@example.com",
            ),
            IdentityRosterEntry(
                provider="entra",
                subject_id="00000000-0000-0000-0000-000000000002",
                display_name="Casey Park",
                principal_type="person",
                roles=("Contributor",),
                username="casey@example.com",
            ),
        ),
    )


__all__ = ["LocalIamDirectory", "build_local_iam_directory"]
