# -----------------------------------------------------------------------
# Deterministic name suffixes.
# -----------------------------------------------------------------------
data "azurerm_client_config" "current" {}

locals {
  env_suffix    = var.env == "" ? "" : "-${var.env}"
  region_suffix = var.region_short == "" ? "" : "-${var.region_short}"
  full_suffix   = "${local.env_suffix}${local.region_suffix}"

  # ACR names cannot contain hyphens (5-50, alphanumeric only).
  # Strip hyphens from the composed suffix.
  acr_suffix = replace(local.full_suffix, "-", "")

  base_tags = {
    workload        = var.workload
    env             = var.env == "" ? "day-zero" : var.env
    managed_by      = "terraform"
    source_of_truth = "fdai"
  }
  tags = merge(local.base_tags, var.additional_tags)

  # Kafka topics served by Event Hubs (see docs/roadmap/deploy-and-onboard.md § Event Source Subscription).
  event_topics = [
    "aw.change.events",
    "aw.dr.events",
    "aw.finops.events",
  ]
}

# -----------------------------------------------------------------------
# Resource Group - the single container per deploy-and-onboard.md.
# -----------------------------------------------------------------------
module "resource_group" {
  source   = "./modules/resource-group"
  name     = "rg-${var.workload}${local.full_suffix}"
  location = var.region
  tags     = local.tags
}

# -----------------------------------------------------------------------
# Observability - Log Analytics first because Container Apps depend on it.
# -----------------------------------------------------------------------
module "log_analytics" {
  source              = "./modules/observability/log-analytics"
  name                = "log-${var.workload}${local.full_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  retention_days      = var.log_retention_days
  tags                = local.tags
}

# -----------------------------------------------------------------------
# Container Registry - pin-by-digest images live here.
# -----------------------------------------------------------------------
module "container_registry" {
  source              = "./modules/container-registry"
  name                = "cr${var.workload}${local.acr_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  tags                = local.tags
}

# Grant the executor MI `AcrPull` so the Container App can pull an image
# a fork pushes to this ACR. Upstream's default `core_image` points at
# `mcr.microsoft.com/...` (anonymous pull, no role needed), but the
# role assignment is idempotent and lets a fork override `core_image`
# with an ACR-hosted digest without extra IAM work.
resource "azurerm_role_assignment" "executor_acr_pull" {
  scope                = module.container_registry.id
  role_definition_name = "AcrPull"
  principal_id         = module.identity.principal_id
}

# -----------------------------------------------------------------------
# Executor Managed Identity - RG-scoped, action-whitelisted (Phase 1 = Change).
# -----------------------------------------------------------------------
module "identity" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-executor"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = local.tags
}

# -----------------------------------------------------------------------
# Per-vertical Managed Identities - phase-3 § Unified Control Loop.
# Each vertical (Change / Resilience / FinOps) executes under its own MI
# so blast radius is bounded by vertical (no vertical can assume
# another's identity). The executor MI above stays as the aggregate
# "action-router" identity; individual verticals attach these MIs when
# invoking their delivery adapters. Role assignments (per-vertical
# action whitelists) land in fork-specific policy modules — this
# module only guarantees the MI resources exist.
# -----------------------------------------------------------------------
module "identity_change" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-change"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { vertical = "change" })
}

module "identity_resilience" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-resilience"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { vertical = "resilience" })
}

module "identity_finops" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-finops"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { vertical = "finops" })
}

# -----------------------------------------------------------------------
# Key Vault - secret store. Executor MI has 'Secrets User' via role assignment.
# -----------------------------------------------------------------------
module "key_vault" {
  source                = "./modules/secret-store/key-vault"
  name                  = "kv-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  tenant_id             = var.tenant_id
  executor_principal_id = module.identity.principal_id
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Event Bus - Event Hubs (Kafka wire on :9093).
# -----------------------------------------------------------------------
module "event_bus" {
  source              = "./modules/event-bus/event-hubs-kafka"
  name                = "evhns-${var.workload}${local.full_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  topics              = local.event_topics
  tags                = local.tags
}

# Executor MI needs both send and receive on the namespace: the control
# loop consumes ingress topics via the Kafka wire on :9093 AND publishes
# DLQ / derived events. `Azure Event Hubs Data Owner` covers both without
# splitting into two role assignments; the namespace has
# `local_authentication_enabled = false` so this is the only path in.
resource "azurerm_role_assignment" "executor_eventhubs_data_owner" {
  scope                = module.event_bus.namespace_id
  role_definition_name = "Azure Event Hubs Data Owner"
  principal_id         = module.identity.principal_id
}

# -----------------------------------------------------------------------
# State Store - PostgreSQL Flexible with pgvector.
# -----------------------------------------------------------------------
module "state_store" {
  source                 = "./modules/state-store/postgres-flex"
  name                   = "psql-${var.workload}${local.full_suffix}"
  location               = var.region
  resource_group_name    = module.resource_group.name
  tenant_id              = var.tenant_id
  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password
  database_name          = var.workload
  tags                   = local.tags
}

# -----------------------------------------------------------------------
# Persistence DSNs - Key Vault-backed secrets consumed by the core app.
#
# Provisioning the secrets from the same apply requires the caller to hold
# `Key Vault Secrets Officer` on the vault. `kv_officer_self` grants it to
# the apply principal (the executing Entra identity) so the secret create
# does not race against a manual out-of-band RBAC step. This role is scoped
# to the vault only and never granted to the executor MI - executor keeps
# read-only `Secrets User` from the KV module.
#
# Day-zero the three DSNs point at the same database (deploy-and-onboard.md
# § PostgreSQL Flexible Server "single store"); a fork MAY split them
# without touching the core, because each is a separate env var.
# -----------------------------------------------------------------------
resource "azurerm_role_assignment" "kv_officer_self" {
  scope                = module.key_vault.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "state_store_dsn" {
  name         = "fdai-state-store-dsn"
  value        = module.state_store.application_dsn
  key_vault_id = module.key_vault.id
  content_type = "postgres-dsn"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self]
}

resource "azurerm_key_vault_secret" "operator_memory_dsn" {
  name         = "fdai-operator-memory-dsn"
  value        = module.state_store.application_dsn
  key_vault_id = module.key_vault.id
  content_type = "postgres-dsn"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self]
}

resource "azurerm_key_vault_secret" "pattern_library_dsn" {
  name         = "fdai-pattern-library-dsn"
  value        = module.state_store.application_dsn
  key_vault_id = module.key_vault.id
  content_type = "postgres-dsn"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self]
}

# -----------------------------------------------------------------------
# Compute - Container Apps env + core app + out-of-band job.
# -----------------------------------------------------------------------
module "compute" {
  source                = "./modules/compute/container-apps"
  env_name              = "cae-${var.workload}${local.full_suffix}"
  core_app_name         = "ca-${var.workload}${local.full_suffix}-core"
  oob_job_name          = "caj-${var.workload}${local.full_suffix}-oob"
  rule_watcher_job_name = "caj-${var.workload}${local.full_suffix}-watcher"
  location              = var.region
  resource_group_name   = module.resource_group.name
  log_workspace_id      = module.log_analytics.workspace_id
  executor_identity_id  = module.identity.resource_id
  image                 = var.core_image
  max_replicas          = var.max_replicas

  # Wire the private ACR so image pulls authenticate via the executor MI
  # (which already holds `AcrPull` on this ACR). If the fork points
  # `core_image` at a public registry (mcr.microsoft.com / Docker Hub)
  # the Container App simply ignores this block - the pull is anonymous.
  acr_login_server = module.container_registry.login_server

  # Required config env vars - `EnvVarConfigProvider` fails-fast if any is
  # unset, so wire them all from the surrounding infra outputs.
  azure_tenant_id         = var.tenant_id
  azure_subscription_id   = data.azurerm_client_config.current.subscription_id
  azure_resource_group    = module.resource_group.name
  azure_region            = var.region
  kafka_bootstrap_servers = module.event_bus.kafka_bootstrap
  kafka_topic_events      = local.event_topics[0]
  postgres_host           = module.state_store.fqdn
  postgres_database       = module.state_store.database_name
  runtime_env             = var.env == "" ? "dev" : var.env
  autonomy_mode_default   = "shadow"

  # Persistence DSNs (KV-backed; executor MI reads at runtime).
  state_store_dsn_secret_id     = azurerm_key_vault_secret.state_store_dsn.id
  operator_memory_dsn_secret_id = azurerm_key_vault_secret.operator_memory_dsn.id
  pattern_library_dsn_secret_id = azurerm_key_vault_secret.pattern_library_dsn.id

  # DB-DR drill (opt-in; the fork toggles dr_drill_enabled + supplies the
  # source server ARM id once the runbook in docs/runbooks/db-dr-drill.md
  # is signed off. Upstream keeps it disabled.).
  dr_drill_enabled              = var.dr_drill_enabled
  dr_drill_job_name             = "caj-${var.workload}${local.full_suffix}-drill"
  dr_drill_source_server_arm_id = var.dr_drill_source_server_arm_id
  dr_drill_dry_run              = var.dr_drill_dry_run

  tags = local.tags

  # Wait for every runtime prerequisite:
  #   - KV secrets present and the executor MI has Secrets User on them.
  #   - Postgres firewall lets the Container App outbound IPs in
  #     (`module.state_store` is a superset that also covers the DB + the
  #     server itself; using the module handle keeps this correct if the
  #     firewall resource gets renamed).
  #   - Event Hubs Data Owner effective for Kafka OAUTHBEARER.
  #   - AcrPull effective on the ACR (matters once the fork's image is
  #     pushed there; upstream default pulls from MCR which needs no role).
  # Without these `depends_on` edges Terraform can create the Container
  # App revision first, watch it crash-loop on missing IAM, and only
  # then finish the role assignments a minute or two later.
  depends_on = [
    module.state_store,
    azurerm_key_vault_secret.state_store_dsn,
    azurerm_key_vault_secret.operator_memory_dsn,
    azurerm_key_vault_secret.pattern_library_dsn,
    azurerm_role_assignment.executor_eventhubs_data_owner,
    azurerm_role_assignment.executor_acr_pull,
  ]
}


# -----------------------------------------------------------------------
# LLM - Azure OpenAI (opt-in, docs/roadmap/dev-and-deploy-parity.md § W-D).
# Skipped by default so a Reader-only deployer can plan/apply.
# -----------------------------------------------------------------------
module "llm_azure_openai" {
  count  = var.enable_llm ? 1 : 0
  source = "./modules/llm/azure-openai"

  name                  = "oai-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  executor_principal_id = module.identity.principal_id
  resolved_capabilities = var.resolved_capabilities
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Phase-4 continuous measurement - two Container Apps Jobs that wire the
# regression detector + pattern-growth intake into scheduled runs.
# The jobs share the same Container Apps env + user-assigned MI as the
# core app + rule watcher (least privilege - no extra role assignments).
# -----------------------------------------------------------------------
module "measurement_runners" {
  source = "./modules/measurement-runners"

  baseline_job_name            = "caj-${var.workload}${local.full_suffix}-baseline"
  growth_job_name              = "caj-${var.workload}${local.full_suffix}-growth"
  container_app_environment_id = module.compute.environment_id
  location                     = var.region
  resource_group_name          = module.resource_group.name
  executor_identity_id         = module.identity.resource_id
  image                        = var.core_image
  scenario_set_version         = var.measurement_scenario_set_version
  tags                         = local.tags
}

