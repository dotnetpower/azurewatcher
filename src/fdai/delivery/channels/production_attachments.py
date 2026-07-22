"""Production composition for protected Slack and Teams attachments."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from uuid import UUID

import httpx

from fdai.core.document_ingestion import DocumentIngestionService
from fdai.delivery.channels.attachment_fetchers import (
    SlackAttachmentFetcherConfig,
    SlackPrivateFileFetcher,
    TeamsAttachmentEndpointResolver,
    TeamsAttachmentFetcherConfig,
    TeamsServerAttachmentFetcher,
)
from fdai.delivery.channels.document_evidence import (
    ChannelAttachmentFetcher,
    ChannelDocumentEvidenceConfig,
    ChannelDocumentProcessingError,
    ProtectedChannelAttachmentIngestor,
)
from fdai.shared.contracts import DocumentState, DocumentVersion
from fdai.shared.providers.document_ingestion import (
    DocumentIngestionError,
    DocumentMetadataStore,
)
from fdai.shared.providers.secret_provider import SecretProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity


class ProductionAttachmentConfigError(ValueError):
    """Raised when protected channel attachments are partially configured."""


_TERMINAL_STATES = frozenset(
    {
        DocumentState.READY,
        DocumentState.READY_WITH_WARNINGS,
        DocumentState.HELD,
        DocumentState.FAILED,
        DocumentState.DELETED,
    }
)


class MetadataDocumentTerminalResolver:
    """Wait for the event-driven ingestion worker without running it inline."""

    def __init__(
        self,
        *,
        metadata: DocumentMetadataStore,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> None:
        if (
            not isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or not isfinite(poll_interval_seconds)
            or poll_interval_seconds <= 0
        ):
            raise ValueError("document terminal wait limits MUST be positive finite numbers")
        self._metadata = metadata
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    async def wait(self, upload_id: UUID) -> DocumentVersion:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                while True:
                    session = await self._metadata.get_upload(upload_id)
                    version = await self._metadata.get_version(
                        session.document_id,
                        session.version_id,
                    )
                    if version.state in _TERMINAL_STATES:
                        return version
                    await asyncio.sleep(self._poll_interval_seconds)
        except TimeoutError as exc:
            raise ChannelDocumentProcessingError(
                "document processing exceeded the terminal wait limit"
            ) from exc
        except DocumentIngestionError as exc:
            raise ChannelDocumentProcessingError(
                "document processing state is unavailable"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - provider details stay behind the boundary
            raise ChannelDocumentProcessingError(
                "document processing state is unavailable"
            ) from exc


@dataclass(frozen=True, slots=True)
class ProductionAttachmentConfig:
    collection_id: str
    access_descriptor_ref: str
    reader_groups: tuple[str, ...]
    retention_policy_version: str
    slack_bot_token_ref: str = "slack-bot-token"  # noqa: S105 - reference name
    slack_allowed_hosts: tuple[str, ...] = ("files.slack.com",)
    teams_allowed_hosts: tuple[str, ...] = ()
    teams_allowed_audiences: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    processing_timeout_seconds: float = 120.0
    processing_poll_interval_seconds: float = 0.25

    def __post_init__(self) -> None:
        if (
            not self.collection_id
            or not self.access_descriptor_ref
            or not self.retention_policy_version
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or self.timeout_seconds > 300
            or not isfinite(self.processing_timeout_seconds)
            or self.processing_timeout_seconds <= 0
            or self.processing_timeout_seconds > 600
            or not isfinite(self.processing_poll_interval_seconds)
            or not 0.1 <= self.processing_poll_interval_seconds <= 10
        ):
            raise ProductionAttachmentConfigError(
                "channel attachment collection, access, retention, and timeout are required"
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
    ) -> ProductionAttachmentConfig | None:
        enabled = environ.get("FDAI_CHANNEL_ATTACHMENTS_ENABLED", "").strip().casefold()
        if enabled in {"", "0", "false", "no", "off"}:
            return None
        if enabled not in {"1", "true", "yes", "on"}:
            raise ProductionAttachmentConfigError(
                "FDAI_CHANNEL_ATTACHMENTS_ENABLED MUST be a boolean value"
            )
        return cls(
            collection_id=_required(environ, "FDAI_CHANNEL_ATTACHMENT_COLLECTION"),
            access_descriptor_ref=_required(
                environ,
                "FDAI_CHANNEL_ATTACHMENT_ACCESS_REF",
            ),
            reader_groups=_csv(environ.get("FDAI_CHANNEL_ATTACHMENT_READER_GROUPS", "")),
            retention_policy_version=_required(
                environ,
                "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY",
            ),
            slack_bot_token_ref=(
                environ.get("FDAI_SLACK_BOT_TOKEN_REF", "").strip() or "slack-bot-token"
            ),
            slack_allowed_hosts=_csv(environ.get("FDAI_SLACK_FILE_HOSTS", "files.slack.com")),
            teams_allowed_hosts=_csv(environ.get("FDAI_TEAMS_ATTACHMENT_HOSTS", "")),
            teams_allowed_audiences=_csv(environ.get("FDAI_TEAMS_ATTACHMENT_AUDIENCES", "")),
            timeout_seconds=_positive_float(
                environ.get("FDAI_CHANNEL_ATTACHMENT_TIMEOUT_SECONDS", ""),
                30.0,
            ),
            processing_timeout_seconds=_positive_float(
                environ.get("FDAI_CHANNEL_ATTACHMENT_PROCESSING_TIMEOUT_SECONDS", ""),
                120.0,
            ),
            processing_poll_interval_seconds=_positive_float(
                environ.get("FDAI_CHANNEL_ATTACHMENT_PROCESSING_POLL_SECONDS", ""),
                0.25,
            ),
        )


def build_production_attachment_ingestor(
    *,
    config: ProductionAttachmentConfig,
    service: DocumentIngestionService,
    metadata: DocumentMetadataStore,
    secrets: SecretProvider,
    http_client: httpx.AsyncClient,
    slack_enabled: bool,
    teams_enabled: bool,
    teams_identity: WorkloadIdentity | None = None,
    teams_resolver: TeamsAttachmentEndpointResolver | None = None,
) -> ProtectedChannelAttachmentIngestor:
    fetchers: dict[str, ChannelAttachmentFetcher] = {}
    if slack_enabled:
        fetchers["slack"] = SlackPrivateFileFetcher(
            config=SlackAttachmentFetcherConfig(
                bot_token_ref=config.slack_bot_token_ref,
                allowed_download_hosts=config.slack_allowed_hosts,
                timeout_seconds=config.timeout_seconds,
            ),
            secrets=secrets,
            http_client=http_client,
        )
    if teams_enabled:
        if (
            teams_identity is None
            or teams_resolver is None
            or not config.teams_allowed_hosts
            or not config.teams_allowed_audiences
        ):
            raise ProductionAttachmentConfigError(
                "Teams attachments require identity, resolver, hosts, and audiences"
            )
        fetchers["teams"] = TeamsServerAttachmentFetcher(
            config=TeamsAttachmentFetcherConfig(
                allowed_download_hosts=config.teams_allowed_hosts,
                allowed_audiences=config.teams_allowed_audiences,
                timeout_seconds=config.timeout_seconds,
            ),
            resolver=teams_resolver,
            identity=teams_identity,
            http_client=http_client,
        )
    if not fetchers:
        raise ProductionAttachmentConfigError(
            "channel attachments require at least one enabled channel"
        )
    return ProtectedChannelAttachmentIngestor(
        service=service,
        terminal_resolver=MetadataDocumentTerminalResolver(
            metadata=metadata,
            timeout_seconds=config.processing_timeout_seconds,
            poll_interval_seconds=config.processing_poll_interval_seconds,
        ),
        fetchers=fetchers,
        config=ChannelDocumentEvidenceConfig(
            collection_id=config.collection_id,
            access_descriptor_ref=config.access_descriptor_ref,
            reader_groups=config.reader_groups,
            retention_policy_version=config.retention_policy_version,
        ),
    )


def _required(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise ProductionAttachmentConfigError(f"{key} MUST be configured")
    return value


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def _positive_float(raw: str, default: float) -> float:
    try:
        value = float(raw) if raw.strip() else default
    except ValueError as exc:
        raise ProductionAttachmentConfigError(
            "channel attachment timeout MUST be a number"
        ) from exc
    if not isfinite(value) or value <= 0:
        raise ProductionAttachmentConfigError("channel attachment timeout MUST be positive")
    return value


__all__ = [
    "MetadataDocumentTerminalResolver",
    "ProductionAttachmentConfig",
    "ProductionAttachmentConfigError",
    "build_production_attachment_ingestor",
]
