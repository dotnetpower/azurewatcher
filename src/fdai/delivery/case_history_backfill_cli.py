"""Backfill legacy case-history state into the relational authority."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime

import httpx

from fdai.delivery.azure.case_history_artifacts import (
    AzureBlobCaseHistoryArtifactStore,
    AzureBlobCaseHistoryConfig,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.persistence.case_history_backfill import (
    CaseHistoryBackfillService,
    PostgresLegacyCaseReader,
    PostgresLegacyCaseReaderConfig,
)
from fdai.delivery.persistence.postgres_case_history import (
    PostgresCaseHistoryMetadataStore,
    PostgresCaseHistoryMetadataStoreConfig,
)

_LOGGER = logging.getLogger("fdai.delivery.case_history_backfill_cli")


async def _run() -> int:
    dsn = _required("FDAI_STATE_STORE_DSN")
    container_url = _required("FDAI_CASE_HISTORY_CONTAINER_URL")
    _required("FDAI_CASE_HISTORY_MI_CLIENT_ID")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    ) as http_client:
        identity = ManagedIdentityWorkloadIdentity.from_env(
            http_client=http_client,
            client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
        )
        report = await CaseHistoryBackfillService(
            source=PostgresLegacyCaseReader(config=PostgresLegacyCaseReaderConfig(dsn=dsn)),
            destination=PostgresCaseHistoryMetadataStore(
                config=PostgresCaseHistoryMetadataStoreConfig(dsn=dsn)
            ),
            artifacts=AzureBlobCaseHistoryArtifactStore(
                config=AzureBlobCaseHistoryConfig(container_url=container_url),
                identity=identity,
                http_client=http_client,
            ),
        ).run(now=datetime.now(UTC))
    _LOGGER.info(
        "case_history_backfill_completed",
        extra={
            "scanned": report.scanned,
            "migrated": report.migrated,
            "excluded": report.excluded,
            "mismatches": report.mismatches,
        },
    )
    return 0 if report.mismatches == 0 else 4


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} MUST be configured")
    return value


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(_run())
    except Exception:
        _LOGGER.exception("case_history_backfill_failed")
        return 3


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main"]
