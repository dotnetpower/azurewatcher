from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from fdai.delivery.channels.document_evidence import ChannelDocumentProcessingError
from fdai.delivery.channels.production_attachments import (
    MetadataDocumentTerminalResolver,
    ProductionAttachmentConfig,
    ProductionAttachmentConfigError,
)
from fdai.shared.contracts import DocumentState


def test_attachment_config_is_disabled_by_default() -> None:
    assert ProductionAttachmentConfig.from_env({}) is None


def test_attachment_config_rejects_invalid_enable_flag() -> None:
    with pytest.raises(ProductionAttachmentConfigError, match="boolean"):
        ProductionAttachmentConfig.from_env({"FDAI_CHANNEL_ATTACHMENTS_ENABLED": "tru"})


def test_attachment_config_requires_governed_collection_fields() -> None:
    with pytest.raises(ProductionAttachmentConfigError, match="COLLECTION"):
        ProductionAttachmentConfig.from_env({"FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1"})


def test_attachment_config_parses_bounded_channel_policy() -> None:
    config = ProductionAttachmentConfig.from_env(
        {
            "FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1",
            "FDAI_CHANNEL_ATTACHMENT_COLLECTION": "channel-evidence",
            "FDAI_CHANNEL_ATTACHMENT_ACCESS_REF": "acl-channel-evidence",
            "FDAI_CHANNEL_ATTACHMENT_READER_GROUPS": "group-a,group-b,group-a",
            "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY": "retention-v1",
            "FDAI_SLACK_FILE_HOSTS": "files.slack.com",
            "FDAI_TEAMS_ATTACHMENT_HOSTS": "attachments.example.com",
            "FDAI_TEAMS_ATTACHMENT_AUDIENCES": "api://attachments.example.com",
        }
    )

    assert config is not None
    assert config.reader_groups == ("group-a", "group-b")
    assert config.slack_allowed_hosts == ("files.slack.com",)
    assert config.teams_allowed_hosts == ("attachments.example.com",)
    assert config.teams_allowed_audiences == ("api://attachments.example.com",)
    assert config.processing_timeout_seconds == 120.0
    assert config.processing_poll_interval_seconds == 0.25


@pytest.mark.parametrize("timeout", ("nan", "inf"))
def test_attachment_config_rejects_nonfinite_timeout(timeout: str) -> None:
    with pytest.raises(ProductionAttachmentConfigError, match="positive"):
        ProductionAttachmentConfig.from_env(
            {
                "FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1",
                "FDAI_CHANNEL_ATTACHMENT_COLLECTION": "channel-evidence",
                "FDAI_CHANNEL_ATTACHMENT_ACCESS_REF": "acl-channel-evidence",
                "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY": "retention-v1",
                "FDAI_CHANNEL_ATTACHMENT_TIMEOUT_SECONDS": timeout,
            }
        )


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("FDAI_CHANNEL_ATTACHMENT_TIMEOUT_SECONDS", "301"),
        ("FDAI_CHANNEL_ATTACHMENT_PROCESSING_TIMEOUT_SECONDS", "601"),
        ("FDAI_CHANNEL_ATTACHMENT_PROCESSING_POLL_SECONDS", "0.01"),
        ("FDAI_CHANNEL_ATTACHMENT_PROCESSING_POLL_SECONDS", "11"),
    ),
)
def test_attachment_config_rejects_unbounded_timing(key: str, value: str) -> None:
    with pytest.raises(ProductionAttachmentConfigError, match="required"):
        ProductionAttachmentConfig.from_env(
            {
                "FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1",
                "FDAI_CHANNEL_ATTACHMENT_COLLECTION": "channel-evidence",
                "FDAI_CHANNEL_ATTACHMENT_ACCESS_REF": "acl-channel-evidence",
                "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY": "retention-v1",
                key: value,
            }
        )


async def test_terminal_resolver_returns_only_agent_processed_terminal_version() -> None:
    upload_id = UUID(int=1)
    document_id = UUID(int=2)
    version_id = UUID(int=3)
    terminal = SimpleNamespace(state=DocumentState.READY, available=True)
    metadata = SimpleNamespace(
        get_upload=AsyncMock(
            return_value=SimpleNamespace(document_id=document_id, version_id=version_id)
        ),
        get_version=AsyncMock(return_value=terminal),
    )
    resolver = MetadataDocumentTerminalResolver(
        metadata=metadata,
        timeout_seconds=1.0,
        poll_interval_seconds=0.01,
    )

    assert await resolver.wait(upload_id) is terminal
    metadata.get_upload.assert_awaited_once_with(upload_id)
    metadata.get_version.assert_awaited_once_with(document_id, version_id)


async def test_terminal_resolver_fails_closed_at_bounded_timeout() -> None:
    metadata = SimpleNamespace(
        get_upload=AsyncMock(
            return_value=SimpleNamespace(document_id=UUID(int=2), version_id=UUID(int=3))
        ),
        get_version=AsyncMock(
            return_value=SimpleNamespace(state=DocumentState.RECEIVED, available=False)
        ),
    )
    resolver = MetadataDocumentTerminalResolver(
        metadata=metadata,
        timeout_seconds=0.01,
        poll_interval_seconds=0.005,
    )

    with pytest.raises(ChannelDocumentProcessingError, match="wait limit"):
        await resolver.wait(UUID(int=1))


async def test_terminal_resolver_normalizes_metadata_provider_failure() -> None:
    metadata = SimpleNamespace(
        get_upload=AsyncMock(side_effect=ConnectionError("database unavailable")),
        get_version=AsyncMock(),
    )
    resolver = MetadataDocumentTerminalResolver(
        metadata=metadata,
        timeout_seconds=1.0,
        poll_interval_seconds=0.01,
    )

    with pytest.raises(ChannelDocumentProcessingError, match="state is unavailable"):
        await resolver.wait(UUID(int=1))
