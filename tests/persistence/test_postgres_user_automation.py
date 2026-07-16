from __future__ import annotations

import pytest

from fdai.delivery.persistence.postgres_briefing import PostgresBriefingStoreConfig
from fdai.delivery.persistence.postgres_user_context import PostgresUserContextStoreConfig
from fdai.delivery.persistence.postgres_workflow_definition import (
    PostgresWorkflowDefinitionStoreConfig,
)


@pytest.mark.parametrize(
    "config_type",
    [
        PostgresUserContextStoreConfig,
        PostgresBriefingStoreConfig,
        PostgresWorkflowDefinitionStoreConfig,
    ],
)
def test_postgres_user_automation_configs_reject_empty_dsn(config_type: type) -> None:
    with pytest.raises(ValueError, match="dsn"):
        config_type(dsn="")


@pytest.mark.parametrize(
    "config_type",
    [
        PostgresUserContextStoreConfig,
        PostgresBriefingStoreConfig,
        PostgresWorkflowDefinitionStoreConfig,
    ],
)
def test_postgres_user_automation_configs_reject_bad_timeout(config_type: type) -> None:
    with pytest.raises(ValueError, match="timeouts"):
        config_type(dsn="postgresql://example", statement_timeout_ms=0)
