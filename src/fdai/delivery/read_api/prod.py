"""Production ASGI app factory for the console read API.

The upstream dev factory lives at
``src/fdai/delivery/read_api/dev/local.py`` and boots
:class:`~fdai.delivery.read_api.auth.UnsafeClaimsExtractor` +
:class:`~fdai.delivery.read_api.read_model.InMemoryConsoleReadModel`. That
harness is never a production surface (its build-time tripwire refuses to
boot outside ``FDAI_READ_API_DEV_MODE=1``).

This module is the counterpart: the fork's composition root serves it
with any ASGI server (``uvicorn fdai.delivery.read_api.prod:app``).
It composes the real production wiring from environment only:

- :class:`~fdai.delivery.read_api.entra_verifier.EntraJwtVerifier` for
  bearer-token validation (JWKS + audience + issuer + expiry);
- :class:`~fdai.core.rbac.resolver.GroupMapping` +
  :class:`~fdai.core.rbac.resolver.RoleResolver` for the ``roles`` claim
  or ``groups`` fallback;
- :class:`~fdai.delivery.read_api.postgres_read_model.PostgresConsoleReadModel`
  for audit / KPI / HIL queue projection on the persisted state.

Nothing customer-specific is baked in. Every value arrives via env vars
that a fork's IaC populates from the Managed Identity's federated
credentials + Key Vault references (see
``docs/roadmap/deployment/deploy-and-onboard.md``).

Env contract
------------

Required (fail-fast startup):

- ``FDAI_DATABASE_URL`` - psycopg 3 URL,
  ``postgresql+psycopg://user:password@host:5432/db``.
- ``FDAI_ENTRA_TENANT_ID`` / ``FDAI_API_AUDIENCE`` - from
  :class:`~fdai.delivery.read_api.entra_verifier.EntraJwtVerifier`.
- ``FDAI_RBAC_{READERS,CONTRIBUTORS,APPROVERS,OWNERS,BREAK_GLASS}_GROUP_ID``.

Optional (respect defaults):

- ``FDAI_ENTRA_ISSUER`` / ``FDAI_ENTRA_JWKS_URI`` - override tenant defaults.
- ``FDAI_READ_API_CORS_ALLOW_ORIGINS`` - comma-separated origin list.
  MUST NOT contain ``*`` outside dev; ``build_app`` fails fast if it does.
- ``FDAI_READ_API_STATEMENT_TIMEOUT_MS`` (default ``20000``).
- ``FDAI_READ_API_CONNECT_TIMEOUT_S`` (default ``10``).
- ``LLM_RESOLVED_MODELS_PATH`` - enables the Command Deck narrator from the
    resolver output using the Container App's managed identity.
- ``FDAI_INCIDENT_SLA_POLICY_JSON`` - enables the periodic incident SLA
    monitor. The JSON object defines positive integer ``acknowledge_seconds``
    and ``resolve_seconds`` values for every key from ``sev1`` through ``sev5``.
- ``FDAI_INCIDENT_SLA_INTERVAL_SECONDS`` (default ``60`` when the SLA policy
    is present) - positive scan interval. Ignored without the policy.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

import httpx
from starlette.applications import Starlette

from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.onboarding import ResourceProbe
from fdai.core.rbac.access_request import AccessRequestService
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.report_feed import ReportFeed
from fdai.core.reporting.composition import default_reporting_engine
from fdai.core.reporting.datasources import AuditReader
from fdai.core.views import ViewEngine, load_view_catalog
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.delivery.identity import EntraHumanIdentityDirectory
from fdai.delivery.persistence import (
    PostgresHilApprovalRegistry,
    PostgresIncidentNotificationDeliveryStore,
    PostgresIncidentProposalStore,
    PostgresMeteringStore,
    PostgresMeteringStoreConfig,
    PostgresReportSignalStore,
    PostgresReportSignalStoreConfig,
    PostgresStateStore,
)
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventoryGraphProvider,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_process_runtime import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)
from fdai.delivery.persistence.postgres_vm_task import (
    PostgresPythonTaskArtifactStore,
    PostgresVmTaskConfig,
    PostgresVmTaskTargetResolver,
)
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.entra_verifier import EntraJwtVerifier
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.postgres_read_model import (
    PostgresConsoleReadModel,
    PostgresConsoleReadModelConfig,
)
from fdai.delivery.read_api.routes.chat import backend_from_env
from fdai.delivery.read_api.routes.chat_web_search import chat_web_search_from_env
from fdai.delivery.read_api.routes.hil_callback import HilCallbackConfig
from fdai.delivery.read_api.routes.llm_cost import LlmCostPanel
from fdai.delivery.read_api.routes.onboarding import OnboardingPanel
from fdai.delivery.read_api.routes.panels import CapabilityCatalogPanel
from fdai.delivery.read_api.routes.process_views import ProcessViewsConfig
from fdai.delivery.read_api.routes.python_tasks import (
    PythonTaskRoutesConfig,
    PythonTaskRunSubmitter,
)
from fdai.delivery.read_api.routes.reporting import ReportingConfig
from fdai.delivery.read_api.routes.workflow_authoring import WorkflowAuthoringConfig
from fdai.delivery.read_api.routes.workflow_execution import WorkflowExecutionConfig
from fdai.delivery.reporting import install_pdf_format_if_available
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
    Workflow,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_DATABASE_URL_ENV: Final[str] = "FDAI_DATABASE_URL"
_CORS_ORIGINS_ENV: Final[str] = "FDAI_READ_API_CORS_ALLOW_ORIGINS"
_STATEMENT_TIMEOUT_ENV: Final[str] = "FDAI_READ_API_STATEMENT_TIMEOUT_MS"
_CONNECT_TIMEOUT_ENV: Final[str] = "FDAI_READ_API_CONNECT_TIMEOUT_S"
_ONBOARDING_ENV: Final[tuple[str, ...]] = (
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "FDAI_EXECUTOR_PRINCIPAL_ID",
    "FDAI_EXECUTOR_EVENT_ROLE_DEFINITION_ID",
    "FDAI_EXECUTOR_SECRET_ROLE_DEFINITION_ID",
)
_INVENTORY_FRESHNESS_ENV: Final[str] = "FDAI_INVENTORY_FRESHNESS_SECONDS"
_TENANT_ENV: Final[str] = "FDAI_ENTRA_TENANT_ID"
_AUDIENCE_ENV: Final[str] = "FDAI_API_AUDIENCE"
_HIL_SECRET_ENV: Final[str] = "FDAI_CHATOPS_WEBHOOK_SECRET"  # noqa: S105 - env name
_HIL_TOPIC_ENV: Final[str] = "FDAI_HIL_DECISION_TOPIC"
_STAGE_TOPIC_ENV: Final[str] = "FDAI_STAGE_TOPIC"
_EVENT_TOPIC_ENV: Final[str] = "KAFKA_TOPIC_EVENTS"
_INCIDENT_SLA_POLICY_ENV: Final[str] = "FDAI_INCIDENT_SLA_POLICY_JSON"
_INCIDENT_SLA_INTERVAL_ENV: Final[str] = "FDAI_INCIDENT_SLA_INTERVAL_SECONDS"
_PYTHON_TASK_AUTHOR_ENDPOINT_ENV: Final[str] = "FDAI_PYTHON_TASK_AUTHOR_ENDPOINT"
_PYTHON_TASK_AUTHOR_DEPLOYMENT_ENV: Final[str] = "FDAI_PYTHON_TASK_AUTHOR_DEPLOYMENT"
_RESOLVED_MODELS_ENV: Final[str] = "LLM_RESOLVED_MODELS_PATH"
_IAM_DIRECTORY_PROVIDER_ENV: Final[str] = "FDAI_IAM_DIRECTORY_PROVIDER"
_IAM_ENTRA_BASE_URL_ENV: Final[str] = "FDAI_IAM_ENTRA_GRAPH_BASE_URL"

_DEFAULT_STATEMENT_TIMEOUT_MS: Final[int] = 20_000
_DEFAULT_CONNECT_TIMEOUT_S: Final[int] = 10
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]

# psycopg 3 (the driver this repo ships) accepts either the bare
# ``postgresql://`` scheme or the SQLAlchemy-style ``postgresql+psycopg://``
# alias. Any other ``+<driver>`` suffix (e.g. ``+asyncpg``, ``+psycopg2``)
# is a caller mistake - the connection would fail with a cryptic driver
# error deep inside psycopg. Reject explicitly at boot with a clear
# ProdReadApiConfigError instead.
_ACCEPTED_DSN_SCHEMES: Final[tuple[str, ...]] = (
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)

_RBAC_ENV: Final[Mapping[str, str]] = {
    "readers": "FDAI_RBAC_READERS_GROUP_ID",
    "contributors": "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
    "approvers": "FDAI_RBAC_APPROVERS_GROUP_ID",
    "owners": "FDAI_RBAC_OWNERS_GROUP_ID",
    "break_glass": "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
}


class ProdReadApiConfigError(ValueError):
    """Raised at startup when required prod-factory env vars are missing."""


def _require_env(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise ProdReadApiConfigError(
            f"{key} is required to build the production read API; set it in "
            "the fork's environment or secret store."
        )
    return value


def _check_required_env(environ: Mapping[str, str], keys: Sequence[str]) -> None:
    """Fail fast with EVERY missing/empty required env var listed at once.

    Cold-boot UX: an operator whose env is entirely unpopulated should see
    one error listing all eight required slots, not eight sequential boot
    failures. Individual :func:`_require_env` calls still exist so callers
    that resolve one value at a time keep their focused messages.
    """
    missing = [key for key in keys if not environ.get(key, "").strip()]
    if missing:
        raise ProdReadApiConfigError(
            "the following env vars are required to build the production "
            f"read API and are missing or empty: {', '.join(missing)}"
        )


def _plain_dsn(database_url: str) -> str:
    """Return a psycopg-compatible DSN, rejecting foreign driver suffixes.

    The alembic + SQLAlchemy world writes URLs as
    ``postgresql+psycopg://...`` (see
    ``tests/persistence/test_postgres_state_store.py``). psycopg 3's raw
    ``connect()`` wants the plain ``postgresql://...`` form. Anything
    else with a ``+<driver>`` suffix (``+asyncpg``, ``+psycopg2``, ...)
    is a caller mistake - reject at boot with a clear error instead of
    letting psycopg fail deep in the driver.
    """
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url[len("postgresql+psycopg://") :]
    # A ``postgresql+<other>://`` scheme is caller error - psycopg 3 does
    # not implement any of the other SQLAlchemy dialect drivers.
    if database_url.startswith("postgresql+") or database_url.startswith("postgres+"):
        _, _, tail = database_url.partition("+")
        driver, _, _ = tail.partition("://")
        raise ProdReadApiConfigError(
            f"{_DATABASE_URL_ENV} carries an unsupported driver suffix "
            f"'+{driver}' - this repo ships psycopg 3; use one of "
            f"{list(_ACCEPTED_DSN_SCHEMES)}."
        )
    if not any(database_url.startswith(scheme) for scheme in _ACCEPTED_DSN_SCHEMES):
        raise ProdReadApiConfigError(
            f"{_DATABASE_URL_ENV} MUST start with one of "
            f"{list(_ACCEPTED_DSN_SCHEMES)}; got a URL with a different scheme."
        )
    return database_url


def _parse_cors_origins(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated origin list, ignoring blanks.

    Rejects a bare ``*`` element unconditionally - a production factory
    MUST never emit a wildcard CORS policy, regardless of ``RUNTIME_ENV``.
    The shared :func:`~fdai.delivery.read_api.main.build_app` only refuses
    ``*`` under ``RUNTIME_ENV in ('staging','prod')``, which leaves an
    unset-``RUNTIME_ENV`` deploy exposed; this factory closes that hole.
    """
    if not raw:
        return ()
    parts = tuple(part.strip() for part in raw.split(",") if part.strip())
    if "*" in parts:
        raise ProdReadApiConfigError(
            f"{_CORS_ORIGINS_ENV}='*' is refused by the production factory - "
            "a same-origin deployment leaves this env unset; a cross-origin "
            "deployment lists the specific console origin(s) explicitly."
        )
    return parts


def _parse_positive_int(environ: Mapping[str, str], key: str, default: int) -> int:
    raw = environ.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ProdReadApiConfigError(f"{key}={raw!r} MUST be an integer") from exc
    if value < 1:
        raise ProdReadApiConfigError(f"{key}={value} MUST be >= 1")
    return value


def _build_group_mapping(environ: Mapping[str, str]) -> GroupMapping:
    """Build a :class:`GroupMapping` from environment variables only.

    The upstream :meth:`GroupMapping.from_config` accepts an
    ``FDAI_RBAC_*_GROUP_ID`` env override on top of a yaml file. In a
    production deploy every value is a Key-Vault secret projected into
    the container's env - the yaml is redundant. This helper composes the
    mapping directly so a fork does not need to ship a placeholder yaml.
    """
    raw = {
        "rbac": {
            "entra": {
                "groups": {
                    slot: _require_env(environ, env_key) for slot, env_key in _RBAC_ENV.items()
                },
            },
        },
    }
    return GroupMapping.from_config(raw, environ=environ)


def build_prod_read_model(
    environ: Mapping[str, str] | None = None,
) -> PostgresConsoleReadModel:
    """Build the Postgres-backed read model from environment."""
    env = environ if environ is not None else os.environ
    dsn = _plain_dsn(_require_env(env, _DATABASE_URL_ENV))
    statement_timeout_ms = _parse_positive_int(
        env, _STATEMENT_TIMEOUT_ENV, _DEFAULT_STATEMENT_TIMEOUT_MS
    )
    connect_timeout_s = _parse_positive_int(env, _CONNECT_TIMEOUT_ENV, _DEFAULT_CONNECT_TIMEOUT_S)
    return PostgresConsoleReadModel(
        config=PostgresConsoleReadModelConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )


def _build_dynamic_views(
    *,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    read_model: PostgresConsoleReadModel,
    group_mapping: GroupMapping,
) -> tuple[
    ReportingConfig,
    ProcessViewsConfig,
    tuple[OntologyObjectType, ...],
    tuple[OntologyLinkType, ...],
    tuple[OntologyActionType, ...],
    tuple[Workflow, ...],
    WorkflowAuthoringConfig,
    WorkflowExecutionConfig,
]:
    schema_registry = PackageResourceSchemaRegistry()
    object_types = load_object_type_catalog(
        _REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types",
        schema_registry=schema_registry,
    )
    link_types = load_link_type_catalog(
        _REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types",
        schema_registry=schema_registry,
        object_types=object_types,
    )
    action_types = load_action_type_catalog(
        _REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=schema_registry,
        probes_root=None,
    )
    workflows = load_workflow_catalog(
        _REPO_ROOT / "rule-catalog" / "workflows",
        schema_registry=schema_registry,
        action_type_names={item.name for item in action_types},
    )
    process_store = PostgresProcessRuntimeStore(
        config=PostgresProcessRuntimeStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    ontology_store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        ),
        object_types=object_types,
        link_types=link_types,
    )
    report_signal_store = PostgresReportSignalStore(
        config=PostgresReportSignalStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    report_engine, formats = default_reporting_engine(
        reports_root=_REPO_ROOT / "rule-catalog" / "reports",
        audit_reader=cast(AuditReader, read_model),
        report_feed=ReportFeed((report_signal_store,)),
        ontology_store=ontology_store,
        process_store=process_store,
    )
    install_pdf_format_if_available(formats)
    view_specs = load_view_catalog(
        _REPO_ROOT / "rule-catalog" / "views",
        report_ids={spec.id for spec in report_engine.catalog().list()},
        workflow_names={workflow.name for workflow in workflows},
    )
    action_types_by_name = {action_type.name: action_type for action_type in action_types}
    workflow_execution = WorkflowExecutionConfig(
        workflows=tuple(workflows),
        orchestrator=WorkflowOrchestrator(
            planner=WorkflowApprovalPlanner(
                action_types=action_types_by_name,
                group_mapping=group_mapping,
                matrix=load_matrix_from_yaml(_REPO_ROOT / "config" / "notifications-matrix.yaml"),
            ),
            action_types=action_types_by_name,
            audit_store=PostgresStateStore(
                config=PostgresStateStoreConfig(
                    dsn=dsn,
                    statement_timeout_ms=statement_timeout_ms,
                    connect_timeout_s=connect_timeout_s,
                )
            ),
            process_store=process_store,
        ),
    )
    workflow_authoring = WorkflowAuthoringConfig(
        schema_registry=schema_registry,
        action_types=tuple(action_types),
        workflows=tuple(workflows),
    )
    return (
        ReportingConfig(engine=report_engine, formats=formats),
        ProcessViewsConfig(
            engine=ViewEngine(specs=view_specs, reports=report_engine, processes=process_store)
        ),
        tuple(object_types),
        tuple(link_types),
        tuple(action_types),
        tuple(workflows),
        workflow_authoring,
        workflow_execution,
    )


def build_prod_app(environ: Mapping[str, str] | None = None) -> Starlette:
    """Assemble the production ASGI app from environment only.

    - Refuses to boot when any required env var is missing
      (:class:`ProdReadApiConfigError`).
    - Wires the production :class:`EntraJwtVerifier` (JWKS + ``aud`` +
      ``iss`` + ``exp``) - never the dev-mode
      :class:`~fdai.delivery.read_api.auth.UnsafeClaimsExtractor`.
    - Binds :class:`PostgresConsoleReadModel` on the persisted schema.
    - ``dev_mode`` stays ``False``; ``build_app`` enforces the extra
      staging/prod guards.

    All required env vars are validated up-front so a cold-boot with an
    entirely unpopulated env produces ONE error listing every missing
    slot, instead of eight sequential boot failures.
    """
    env = environ if environ is not None else os.environ
    _check_required_env(
        env,
        (
            _DATABASE_URL_ENV,
            _TENANT_ENV,
            _AUDIENCE_ENV,
            *_RBAC_ENV.values(),
        ),
    )
    verifier = EntraJwtVerifier.from_env(env)
    group_mapping = _build_group_mapping(env)
    resolver = RoleResolver(group_mapping=group_mapping)
    authenticator = build_authenticator(verifier=verifier, resolver=resolver)
    read_model = build_prod_read_model(env)
    state_store_config = PostgresStateStoreConfig(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
    )
    state_store = PostgresStateStore(config=state_store_config)
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    iam_directory = None
    iam_provider = env.get(_IAM_DIRECTORY_PROVIDER_ENV, "").strip().casefold()
    if iam_provider:
        if iam_provider != "entra":
            raise ProdReadApiConfigError(
                f"{_IAM_DIRECTORY_PROVIDER_ENV}={iam_provider!r} is not implemented; "
                "supported value: 'entra'"
            )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

        iam_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
        )
        iam_directory = EntraHumanIdentityDirectory(
            client=iam_http,
            identity=ManagedIdentityWorkloadIdentity(http_client=iam_http),
            base_url=env.get(_IAM_ENTRA_BASE_URL_ENV, "").strip()
            or "https://graph.microsoft.com/v1.0",
        )

        async def _close_iam_http() -> None:
            await iam_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_iam_http)
    cors_origins = _parse_cors_origins(env.get(_CORS_ORIGINS_ENV))
    (
        reporting,
        process_views,
        object_types,
        link_types,
        action_types,
        workflows,
        workflow_authoring,
        workflow_execution,
    ) = _build_dynamic_views(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
        read_model=read_model,
        group_mapping=group_mapping,
    )
    hil_callback = None
    hil_registry = None
    hil_decision_publisher = None
    live_stream = None
    agent_activity = None
    console_action = None
    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    from fdai.core.briefing import BriefingCoordinator, OpeningBriefingService
    from fdai.core.user_context_projection import UserContextOntologyProjector
    from fdai.core.workflow.definition import build_workflow_definition
    from fdai.delivery.persistence import (
        PostgresBriefingRunStore,
        PostgresBriefingStoreConfig,
        PostgresBriefingSubscriptionStore,
        PostgresConversationHistoryStore,
        PostgresConversationPolicyStore,
        PostgresUserContextStoreConfig,
        PostgresUserMemoryStore,
        PostgresUserPreferenceStore,
        PostgresWorkflowBindingStore,
        PostgresWorkflowDefinitionStore,
        PostgresWorkflowDefinitionStoreConfig,
    )
    from fdai.delivery.read_api.routes.user_context import UserContextRoutesConfig
    from fdai.delivery.read_api.routes.workflow_definitions import (
        WorkflowDefinitionRoutesConfig,
    )
    from fdai.shared.providers.workflow_definition import (
        WorkflowLifecycle,
        WorkflowOrigin,
        WorkflowVisibility,
    )

    user_store_config = PostgresUserContextStoreConfig(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
    )
    briefing_store_config = PostgresBriefingStoreConfig(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
    )
    workflow_store_config = PostgresWorkflowDefinitionStoreConfig(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
    )
    conversation_history_store = PostgresConversationHistoryStore(config=user_store_config)
    user_context_ontology_store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(
            dsn=read_model._config.dsn,
            statement_timeout_ms=read_model._config.statement_timeout_ms,
            connect_timeout_s=read_model._config.connect_timeout_s,
        ),
        object_types=object_types,
        link_types=link_types,
    )
    user_context_ontology_projector = UserContextOntologyProjector(
        store=user_context_ontology_store
    )
    user_preference_store = PostgresUserPreferenceStore(config=user_store_config)
    user_memory_store = PostgresUserMemoryStore(config=user_store_config)
    conversation_policy_store = PostgresConversationPolicyStore(config=briefing_store_config)
    briefing_subscription_store = PostgresBriefingSubscriptionStore(config=briefing_store_config)
    briefing_run_store = PostgresBriefingRunStore(config=briefing_store_config)
    briefing_report_feed = ReportFeed(
        (
            PostgresReportSignalStore(
                config=PostgresReportSignalStoreConfig(
                    dsn=read_model._config.dsn,
                    statement_timeout_ms=read_model._config.statement_timeout_ms,
                    connect_timeout_s=read_model._config.connect_timeout_s,
                )
            ),
        )
    )
    user_context = UserContextRoutesConfig(
        conversations=conversation_history_store,
        preferences=user_preference_store,
        memories=user_memory_store,
        policies=conversation_policy_store,
        subscriptions=briefing_subscription_store,
        runs=briefing_run_store,
        opening_briefing=OpeningBriefingService(
            policies=conversation_policy_store,
            runs=briefing_run_store,
            coordinator=BriefingCoordinator(report_feed=briefing_report_feed),
        ),
        ontology_projector=user_context_ontology_projector,
    )
    workflow_definition_store = PostgresWorkflowDefinitionStore(config=workflow_store_config)
    workflow_binding_store = PostgresWorkflowBindingStore(config=workflow_store_config)
    action_types_by_name = {item.name: item for item in action_types}
    built_in_definitions = tuple(
        build_workflow_definition(
            workflow,
            action_types=action_types_by_name,
            origin=WorkflowOrigin.UPSTREAM,
            visibility=WorkflowVisibility.GLOBAL,
            lifecycle=WorkflowLifecycle.SHADOW,
            created_at=datetime.now(tz=UTC),
            source_ref=f"catalog:{workflow.name}@{workflow.version}",
        )
        for workflow in workflows
    )

    async def _seed_workflow_definitions() -> None:
        for definition in built_in_definitions:
            stored = await workflow_definition_store.put(definition)
            await user_context_ontology_projector.project_workflow_definition(stored)

    startup_callbacks = (
        *startup_callbacks,
        user_context_ontology_store.sync_catalog,
        _seed_workflow_definitions,
    )
    workflow_definitions = WorkflowDefinitionRoutesConfig(
        definitions=workflow_definition_store,
        bindings=workflow_binding_store,
        schema_registry=PackageResourceSchemaRegistry(),
        action_types=tuple(action_types),
        ontology_projector=user_context_ontology_projector,
    )
    incident_sla_stop: Callable[[], Awaitable[None]] | None = None
    event_bus = None
    http_client: httpx.AsyncClient | None = None
    event_topic = ""
    hil_secret = env.get(_HIL_SECRET_ENV, "").strip()
    kafka_bootstrap = env.get("FDAI_KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if hil_secret or kafka_bootstrap:
        from fdai.delivery.azure.event_bus import (
            EventHubsKafkaBus,
            EventHubsKafkaBusConfig,
        )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
        from fdai.delivery.chatops.hil_decision import (
            DEFAULT_HIL_DECISION_TOPIC,
            EventBusHilDecisionPublisher,
        )
        from fdai.delivery.read_api.streaming.agent_activity_broadcaster import (
            DEFAULT_STAGE_TOPIC,
            AgentActivityBroadcaster,
        )
        from fdai.delivery.read_api.streaming.agent_activity_stream import (
            AgentActivityStreamConfig,
        )
        from fdai.delivery.read_api.streaming.live_stage_broadcaster import (
            LiveStageBroadcaster,
        )
        from fdai.delivery.read_api.streaming.live_stream import LiveStreamConfig

        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)
        )
        identity = ManagedIdentityWorkloadIdentity(http_client=http_client)
        event_bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=kafka_bootstrap
                or _require_env(env, "FDAI_KAFKA_BOOTSTRAP_SERVERS")
            ),
        )
        if kafka_bootstrap:
            stage_topic = env.get(_STAGE_TOPIC_ENV, "").strip() or DEFAULT_STAGE_TOPIC
            live_stream = LiveStreamConfig(
                broadcaster_factory=lambda publisher: LiveStageBroadcaster(
                    event_bus=event_bus,
                    publisher=publisher,
                    stage_topic=stage_topic,
                )
            )
            agent_activity = AgentActivityStreamConfig(
                broadcaster_factory=lambda publisher: AgentActivityBroadcaster(
                    event_bus=event_bus,
                    publisher=publisher,
                    stage_topic=stage_topic,
                )
            )

        if hil_secret:
            hil_callback = HilCallbackConfig(secret=hil_secret)
            hil_registry = PostgresHilApprovalRegistry(
                store=state_store,
                dsn=read_model._config.dsn,
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
            hil_decision_publisher = EventBusHilDecisionPublisher(
                bus=event_bus,
                topic=env.get(_HIL_TOPIC_ENV, "").strip() or DEFAULT_HIL_DECISION_TOPIC,
            )

        event_topic = env.get(_EVENT_TOPIC_ENV, "").strip()
        if kafka_bootstrap and event_topic:
            from fdai.core.incident import (
                DurableIncidentLifecycleNotifier,
                IncidentLifecycleWorkflow,
                IncidentRegistry,
                RoutedIncidentLifecycleNotifier,
            )
            from fdai.core.incident.sla import IncidentSlaMonitor, IncidentSlaPolicy
            from fdai.core.notifications.matrix import load_matrix_from_yaml
            from fdai.core.notifications.router import ChannelRegistry, NotificationRouter
            from fdai.delivery.notifications import StateStoreHilEscalationSink
            from fdai.delivery.read_api.routes.console_action import ConsoleActionSubmitter

            incident_registry = IncidentRegistry(state_store=state_store)
            notification_router = NotificationRouter(
                matrix=load_matrix_from_yaml(_REPO_ROOT / "config" / "notifications-matrix.yaml"),
                registry=ChannelRegistry(),
                audit_store=state_store,
                hil_sink=StateStoreHilEscalationSink(state_store=state_store),
            )
            incident_notifier = DurableIncidentLifecycleNotifier(
                delegate=RoutedIncidentLifecycleNotifier(dispatcher=notification_router),
                delivery_store=PostgresIncidentNotificationDeliveryStore(config=state_store_config),
            )
            production_action_types = load_action_type_catalog(
                _REPO_ROOT / "rule-catalog" / "action-types",
                schema_registry=PackageResourceSchemaRegistry(),
                probes_root=_REPO_ROOT / "rule-catalog" / "probes",
            )
            console_action = ConsoleActionSubmitter(
                event_bus=event_bus,
                raw_event_topic=event_topic,
                action_type_names=frozenset(
                    action_type.name for action_type in production_action_types
                ),
                incident_workflow=IncidentLifecycleWorkflow(
                    registry=incident_registry,
                    notifier=incident_notifier,
                ),
                incident_proposals=PostgresIncidentProposalStore(config=state_store_config),
            )

            async def _rehydrate_incidents() -> None:
                entries = await state_store.read_incident_transitions()
                incident_registry.rehydrate(entries)
                await incident_notifier.replay(entries)

            startup_callbacks = (*startup_callbacks, _rehydrate_incidents)
            raw_sla_policy = env.get(_INCIDENT_SLA_POLICY_ENV, "").strip()
            if raw_sla_policy:
                try:
                    decoded_sla_policy = json.loads(raw_sla_policy)
                    if not isinstance(decoded_sla_policy, dict):
                        raise ValueError("policy MUST be a JSON object")
                    sla_policy = IncidentSlaPolicy.from_mapping(decoded_sla_policy)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ProdReadApiConfigError(
                        f"{_INCIDENT_SLA_POLICY_ENV} is invalid: {exc}"
                    ) from exc
                sla_monitor = IncidentSlaMonitor(
                    source=state_store,
                    notifier=incident_notifier,
                    policy=sla_policy,
                    interval_seconds=_parse_positive_int(
                        env,
                        _INCIDENT_SLA_INTERVAL_ENV,
                        60,
                    ),
                )
                startup_callbacks = (*startup_callbacks, sla_monitor.start)
                incident_sla_stop = sla_monitor.stop

        async def _close_event_transport() -> None:
            await event_bus.close()
            await http_client.aclose()

        shutdown_callbacks = (
            *((incident_sla_stop,) if incident_sla_stop is not None else ()),
            _close_event_transport,
        )
    from fdai.delivery.vm_task import PlanningVmTaskRunner

    vm_task_store_config = PostgresVmTaskConfig(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
    )
    task_author = None
    author_endpoint = env.get(_PYTHON_TASK_AUTHOR_ENDPOINT_ENV, "").strip()
    author_deployment = env.get(_PYTHON_TASK_AUTHOR_DEPLOYMENT_ENV, "").strip()
    if bool(author_endpoint) != bool(author_deployment):
        raise ProdReadApiConfigError(
            f"{_PYTHON_TASK_AUTHOR_ENDPOINT_ENV} and "
            f"{_PYTHON_TASK_AUTHOR_DEPLOYMENT_ENV} MUST be configured together"
        )
    if author_endpoint:
        from fdai.delivery.azure.llm.python_task_author import (
            AzureOpenAIPythonTaskAuthor,
            AzureOpenAIPythonTaskAuthorConfig,
        )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

        author_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0)
        )
        task_author = AzureOpenAIPythonTaskAuthor(
            identity=ManagedIdentityWorkloadIdentity(http_client=author_http),
            http_client=author_http,
            config=AzureOpenAIPythonTaskAuthorConfig(
                endpoint=author_endpoint,
                deployment=author_deployment,
            ),
        )

        async def _close_task_author_http() -> None:
            await author_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_task_author_http)
    python_tasks = PythonTaskRoutesConfig(
        artifacts=PostgresPythonTaskArtifactStore(config=vm_task_store_config),
        targets=PostgresVmTaskTargetResolver(config=vm_task_store_config),
        runner=PlanningVmTaskRunner(),
        submitter=(
            PythonTaskRunSubmitter(event_bus=event_bus, topic=event_topic)
            if event_bus is not None and event_topic
            else None
        ),
        schedule_store=PostgresScheduleStore(
            config=PostgresScheduleStoreConfig(
                dsn=read_model._config.dsn,
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
        ),
        workflows=workflows,
        author=task_author,
    )
    onboarding_values = {name: env.get(name, "").strip() for name in _ONBOARDING_ENV}
    configured_onboarding = {name for name, value in onboarding_values.items() if value}
    if configured_onboarding and len(configured_onboarding) != len(_ONBOARDING_ENV):
        missing = sorted(set(_ONBOARDING_ENV) - configured_onboarding)
        raise ProdReadApiConfigError(
            "Azure onboarding probe configuration is incomplete; missing: " + ", ".join(missing)
        )
    onboarding_probe: ResourceProbe
    if configured_onboarding:
        from fdai.delivery.azure.onboarding import (
            AzureOnboardingProbeConfig,
            AzureResourceProbe,
        )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

        onboarding_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)
        )
        onboarding_probe = AzureResourceProbe(
            config=AzureOnboardingProbeConfig(
                subscription_id=onboarding_values["AZURE_SUBSCRIPTION_ID"],
                resource_group=onboarding_values["AZURE_RESOURCE_GROUP"],
                executor_principal_id=onboarding_values["FDAI_EXECUTOR_PRINCIPAL_ID"],
                event_role_definition_id=onboarding_values[
                    "FDAI_EXECUTOR_EVENT_ROLE_DEFINITION_ID"
                ],
                secret_role_definition_id=onboarding_values[
                    "FDAI_EXECUTOR_SECRET_ROLE_DEFINITION_ID"
                ],
            ),
            identity=ManagedIdentityWorkloadIdentity(http_client=onboarding_http),
            http_client=onboarding_http,
        )

        async def _close_onboarding_http() -> None:
            await onboarding_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_onboarding_http)
    else:
        from fdai.core.onboarding import EmptyResourceProbe

        onboarding_probe = EmptyResourceProbe()
    chat = None
    chat_web_search = None
    resolved_models_path = env.get(_RESOLVED_MODELS_ENV, "").strip()
    narrator_api_key_configured = all(
        env.get(name, "").strip()
        for name in (
            "FDAI_NARRATOR_BASE_URL",
            "FDAI_NARRATOR_API_KEY",
            "FDAI_NARRATOR_MODEL",
        )
    )
    web_search_raw = env.get("FDAI_WEB_SEARCH_ENABLED", "").strip().casefold()
    web_search_configured = web_search_raw not in {"", "0", "false", "no", "off"}
    if resolved_models_path or narrator_api_key_configured or web_search_configured:
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

        chat_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=90.0, write=15.0, pool=5.0)
        )
        chat_identity = (
            ManagedIdentityWorkloadIdentity(http_client=chat_http) if resolved_models_path else None
        )
        chat = backend_from_env(
            dict(env),
            identity=chat_identity,
            http_client=chat_http,
        )
        chat_web_search = chat_web_search_from_env(
            env,
            identity=chat_identity,
            http_client=chat_http,
        )

        async def _close_chat_http() -> None:
            await chat_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_chat_http)
    model_settings = None
    if resolved_models_path:
        from fdai.delivery.read_api.routes.model_settings import ModelSettingsService

        model_settings = ModelSettingsService(
            resolved_models_path=Path(resolved_models_path),
            store=state_store,
            backend=chat,
            web_search_resolver=chat_web_search,
        )
    config = ReadApiConfig(
        dev_mode=False,
        cors_allow_origins=cors_origins,
        ontology_object_types=object_types,
        ontology_link_types=link_types,
        ontology_action_types=action_types,
        inventory_graph_provider=PostgresInventoryGraphProvider(
            config=PostgresInventorySnapshotStoreConfig(
                dsn=read_model._config.dsn,
                freshness_budget_seconds=_parse_positive_int(env, _INVENTORY_FRESHNESS_ENV, 86_400),
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
        ),
        reporting=reporting,
        process_views=process_views,
        workflow_authoring=workflow_authoring,
        workflow_execution=workflow_execution,
        workflow_definitions=workflow_definitions,
        user_context=user_context,
        model_settings=model_settings,
        python_tasks=python_tasks,
        chat=chat,
        chat_web_search=chat_web_search,
        chat_probe_interval_seconds=_parse_positive_int(
            env,
            "FDAI_NARRATOR_PROBE_INTERVAL_SECONDS",
            300,
        ),
        conversation_history_store=conversation_history_store,
        conversation_policy_store=conversation_policy_store,
        user_context_ontology_projector=user_context_ontology_projector,
        extra_panels=(
            CapabilityCatalogPanel(),
            OnboardingPanel(probe=onboarding_probe),
            LlmCostPanel(
                PostgresMeteringStore(
                    config=PostgresMeteringStoreConfig(
                        dsn=read_model._config.dsn,
                        statement_timeout_ms=read_model._config.statement_timeout_ms,
                        connect_timeout_s=read_model._config.connect_timeout_s,
                    )
                )
            ),
        ),
        hil_callback=hil_callback,
        hil_registry=hil_registry,
        hil_decision_publisher=hil_decision_publisher,
        console_action=console_action,
        iam_access=AccessRequestService(store=state_store),
        iam_directory=iam_directory,
        iam_identity_provider=iam_provider or "entra",
        iam_role_group_ids={
            "Reader": group_mapping.reader_group_id,
            "Contributor": group_mapping.contributor_group_id,
            "Approver": group_mapping.approver_group_id,
            "Owner": group_mapping.owner_group_id,
            "BreakGlass": group_mapping.break_glass_group_id,
        },
        live_stream=live_stream,
        agent_activity=agent_activity,
        startup_callbacks=startup_callbacks,
        shutdown_callbacks=shutdown_callbacks,
    )
    return build_app(authenticator=authenticator, read_model=read_model, config=config)


def app() -> Starlette:
    """Factory form for ``uvicorn ... --factory``.

    Usage::

        uvicorn fdai.delivery.read_api.prod:app --factory --host 0.0.0.0 --port 8000
    """
    return build_prod_app()


__all__ = [
    "ProdReadApiConfigError",
    "app",
    "build_prod_app",
    "build_prod_read_model",
]
