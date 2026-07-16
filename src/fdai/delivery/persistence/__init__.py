"""Persistence adapters - CSP-neutral wire-level backends.

These modules realize the persistence-facing Protocols
(:class:`~fdai.shared.providers.state_store.StateStore`,
:class:`~fdai.core.tiers.t1_lightweight.tier.PatternLibrary`)
against real databases (currently PostgreSQL + pgvector). Postgres is
not Azure-specific - the same adapters bind to Cloud SQL, RDS, or a
self-hosted server - so they live here rather than under
``delivery/azure/``.
"""

from __future__ import annotations

from fdai.delivery.persistence.pgvector_pattern_library import (
    PgVectorPatternLibrary,
    PgVectorPatternLibraryConfig,
)
from fdai.delivery.persistence.postgres import (
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.delivery.persistence.postgres_briefing import (
    PostgresBriefingRunStore,
    PostgresBriefingStoreConfig,
    PostgresBriefingSubscriptionStore,
    PostgresConversationPolicyStore,
)
from fdai.delivery.persistence.postgres_idempotency import (
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
)
from fdai.delivery.persistence.postgres_incident_notification import (
    PostgresIncidentNotificationDeliveryStore,
)
from fdai.delivery.persistence.postgres_incident_proposal import (
    PostgresIncidentProposalStore,
)
from fdai.delivery.persistence.postgres_jira_ledger import PostgresJiraLedger
from fdai.delivery.persistence.postgres_metering import (
    PostgresMeteringStore,
    PostgresMeteringStoreConfig,
)
from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_operator_memory import (
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
)
from fdai.delivery.persistence.postgres_outbox import (
    PostgresOutboxStore,
    PostgresOutboxStoreConfig,
)
from fdai.delivery.persistence.postgres_process_runtime import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.delivery.persistence.postgres_report_signal import (
    PostgresReportSignalStore,
    PostgresReportSignalStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)
from fdai.delivery.persistence.postgres_user_context import (
    PostgresConversationHistoryStore,
    PostgresUserContextStoreConfig,
    PostgresUserMemoryStore,
    PostgresUserPreferenceStore,
)
from fdai.delivery.persistence.postgres_user_context_retention import (
    PostgresUserContextRetention,
    ProjectionDeleteJob,
    UserContextRetentionReport,
)
from fdai.delivery.persistence.postgres_workflow_definition import (
    PostgresWorkflowBindingStore,
    PostgresWorkflowDefinitionStore,
    PostgresWorkflowDefinitionStoreConfig,
)
from fdai.delivery.persistence.state_store_action_promotion import (
    StateStoreActionPromotionRegistry,
)
from fdai.delivery.persistence.state_store_hil_registry import (
    PostgresHilApprovalRegistry,
    StateStoreHilApprovalRegistry,
    add_pending_approval,
)

__all__ = [
    "PgVectorPatternLibrary",
    "PgVectorPatternLibraryConfig",
    "PostgresAdvisoryResourceLock",
    "PostgresAdvisoryResourceLockConfig",
    "PostgresBriefingRunStore",
    "PostgresBriefingStoreConfig",
    "PostgresBriefingSubscriptionStore",
    "PostgresConversationHistoryStore",
    "PostgresConversationPolicyStore",
    "PostgresIdempotencyStore",
    "PostgresIdempotencyStoreConfig",
    "PostgresIncidentProposalStore",
    "PostgresJiraLedger",
    "PostgresMeteringStore",
    "PostgresMeteringStoreConfig",
    "PostgresIncidentNotificationDeliveryStore",
    "PostgresOperatorMemoryStore",
    "PostgresOperatorMemoryStoreConfig",
    "PostgresOntologyInstanceStore",
    "PostgresOntologyInstanceStoreConfig",
    "PostgresOutboxStore",
    "PostgresOutboxStoreConfig",
    "PostgresProcessRuntimeStore",
    "PostgresProcessRuntimeStoreConfig",
    "PostgresReportSignalStore",
    "PostgresReportSignalStoreConfig",
    "PostgresScheduleStore",
    "PostgresScheduleStoreConfig",
    "PostgresStateStore",
    "PostgresStateStoreConfig",
    "PostgresUserContextStoreConfig",
    "PostgresUserMemoryStore",
    "PostgresUserPreferenceStore",
    "PostgresUserContextRetention",
    "ProjectionDeleteJob",
    "UserContextRetentionReport",
    "PostgresWorkflowBindingStore",
    "PostgresWorkflowDefinitionStore",
    "PostgresWorkflowDefinitionStoreConfig",
    "PostgresHilApprovalRegistry",
    "StateStoreHilApprovalRegistry",
    "StateStoreActionPromotionRegistry",
    "add_pending_approval",
]
