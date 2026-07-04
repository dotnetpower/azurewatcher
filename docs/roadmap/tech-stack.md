# Technology Stack

Choices favor **CSP-neutral, OSS-first** components so the control plane stays portable and
free of vendor lock-in. **Azure is the only implemented target** in this stack; any non-Azure
managed service listed as an alternative is **TBD** (see
[Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must)).
Where a specific managed service is named, it is a **recommendation to confirm at adoption
time** (managed offerings and preview features change), not a hard dependency. This stack
realizes the topology in
[app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md) and must
satisfy the safety and code rules in
[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md)
and the threat model in [security-and-identity.md](security-and-identity.md).

## How to Read This Document

- **Bold** entries are named managed services offered as recommendations; each is paired with a
  CSP-neutral or OSS fallback in the Alternatives column, and every one is subject to the
  confirm-at-adoption caveat above.
- Non-bold entries are OSS or language-level choices intended to be portable as-is.
- Anything Azure-specific sits **behind a provider adapter** so the core engine never imports a
  vendor SDK directly (see
  [project-structure.md](project-structure.md) for module boundaries).

## Selection Principles

- **CSP-neutral core**: policy in OPA/Rego, IaC in Terraform/OpenTofu, provider access behind
  adapters. Vendor SDK calls never appear in the core engine.
- **OSS-first**: prefer open, permissively licensed components (OPA, Checkov/tfsec/KICS/Trivy,
  kube-bench, OpenCost, Chaos Mesh) over vendor-locked equivalents.
- **Event-driven, scale-to-zero**: no always-on polling daemons.
- **Correctness over novelty**: the deterministic engine and audit store optimize for
  predictable behavior, testability, and observability rather than adopting new technology.
- **Two implementations behind one interface**: for every proprietary choice, keep a documented
  neutral substitute so a future non-Azure adapter is additive. Azure is the only implemented
  target today; other CSPs are TBD (see
  [Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must)).

## Recommended Stack

| Concern | Recommendation | Rationale | Alternatives (neutral / OSS) |
|---------|----------------|-----------|------------------------------|
| Core engine runtime | TypeScript (Node) or Python | strong ecosystem for adapters, LLM SDKs, and rule tooling | Go or .NET if perf/typing demands grow |
| Policy engine | **OPA / Rego** | CSP-neutral policy-as-code; reused by T0 and the T2 verifier | Gatekeeper (K8s), Cloud Custodian |
| IaC | **Terraform** / **OpenTofu** (Bicep optional for Azure-only infra) | portable across clouds; large module ecosystem | Pulumi; OpenTofu is the OSS (MPL-2.0) fork of Terraform |
| Event bus | **Service Bus** (ordered, DLQ-capable queues/topics) + **Event Grid** (resource/activity subscriptions) | reliable ordering and dead-lettering plus a native cloud event source | Kafka (durable log/replay) or NATS JetStream (lightweight pub/sub) — non-Azure options are TBD |
| Event/message schema | JSON Schema (or CloudEvents envelope) in a versioned registry | typed, versioned event contracts; enables safe evolution and validation at ingress | Avro/Protobuf + Confluent-compatible registry |
| Dead-letter handling | native SB dead-letter queue + a replay/redrive worker | no event is silently dropped; poison messages are quarantined and re-processable | Kafka DLQ topic + redrive |
| Compute | **Azure Container Apps** (Consumption, KEDA + scale-to-zero) — **one app with sidecar containers** for core subsystems | event scaling without always-on cost; sidecars keep deployment count minimal while preserving code-level SRP (see [deploy-and-onboard.md](deploy-and-onboard.md#compute-shape-sidecar-containers)) | Knative or Cloud Run for portability; AKS when custom networking/DaemonSets/GPU are needed |
| Light triggers | **Container Apps Jobs** (same environment as Compute) | out-of-band change detection, cost-anomaly hooks, scheduled probes — avoids provisioning a separate Functions plan | Azure Functions if a native binding is required; Knative eventing |
| State / audit / KPI | **PostgreSQL** (default) or **Cosmos DB** | append-only audit log, pattern library, KPI store; also hosts the runtime ontology instance state ([llm-strategy.md § Ontology Storage Layout](llm-strategy.md#ontology-storage-layout)) | see [Data Store Selection](#data-store-selection-criteria) |
| Vector search (T1) | pgvector (co-located with PostgreSQL) | keep embeddings next to audit/state; one datastore to operate | dedicated vector DB (Qdrant/Milvus) at higher scale — see [Vector Search Rationale](#vector-search-rationale) |
| Secret store | **Key Vault** (or HashiCorp Vault) via injected provider | secrets never in source/logs; runtime injection only | SOPS + age for GitOps-managed secrets |
| Feature flags / shadow toggles | OSS flag service (OpenFeature + flagd) | gate shadow-vs-enforce promotion per action without redeploy | config-driven flags in the state store |
| DB migrations | versioned migrations (Flyway / Alembic / Prisma Migrate) | schema changes are reviewed, ordered, and reversible | — |
| CI/CD | GitHub Actions or Azure Pipelines | runs lint, tests, coverage gate, secret scan (gitleaks), dependency/SBOM audit | GitLab CI |
| PR gate | **GitHub App** (Checks API) or Azure DevOps service hooks | audit/rollback/approval already live in git | remediation delivered as PRs regardless of host |
| HIL channel | **Bot Framework / Teams** Adaptive Cards | reach operators where they are | Slack adapter; email/webhook fallback behind a notifier interface — see [channels-and-notifications.md](channels-and-notifications.md) |
| LLM access (T2) | provider-agnostic gateway/router over 2+ distinct models | mixed-model cross-check per [llm-strategy.md](llm-strategy.md); models auto-provisioned at bootstrap from a capability-preferences registry and reconciled weekly — [llm-strategy.md § Model Provisioning and Lifecycle](llm-strategy.md#model-provisioning-and-lifecycle) | LiteLLM/OpenRouter-style router |
| Observability | OpenTelemetry (traces/metrics/logs) → collector → backend (**Log Analytics** with App Insights bound to it — no separate APM resource) | measurement-first requires first-class telemetry; retention defaults to 30 days and is UI-configurable ([deploy-and-onboard.md](deploy-and-onboard.md#azure-resource-inventory-minimum-set)) | Prometheus + Grafana + Tempo/Loki (OSS); vendor APM |

## Data Store Selection Criteria

The default is **PostgreSQL**; choose per these criteria rather than by preference:

- **Relational + audit integrity**: append-only audit log, foreign keys, and transactional
  writes favor PostgreSQL.
- **Co-located vectors**: pgvector keeps T1 embeddings in the same store — simpler ops, one
  backup/restore path.
- **Global distribution / multi-region write / elastic partitioned scale**: favor Cosmos DB
  when write volume or geo-distribution outgrows a single primary.
- **Portability**: PostgreSQL runs identically across clouds and locally; Cosmos DB is
  Azure-specific and therefore must sit behind the state-store adapter.
- **Cost model**: PostgreSQL is provisioned/predictable; Cosmos DB is RU-metered — validate
  against expected audit-write throughput before committing.

## Vector Search Rationale

- **Start with pgvector**: one datastore, transactional consistency with audit/state, adequate
  for T1 similarity reuse at low-to-moderate corpus sizes.
- **Graduate to a dedicated vector DB** when any hold: corpus exceeds roughly 10^6–10^7 vectors,
  p95 recall/latency targets fail with HNSW/IVFFlat tuning, or embedding refresh contends with
  transactional load.
- **Embedding model** is a separate decision (local/self-hosted vs hosted API) driven by cost
  and privacy; keep it behind the same LLM-gateway interface and versioned as config.
- Index type, dimension count, and distance metric are configuration, not hard-coded.

## OSS License Posture

- Prefer permissive/weak-copyleft licenses (Apache-2.0, MIT, MPL-2.0) for anything compiled or
  linked into the core; document each new dependency's license in the PR per
  [coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md).
- **Terraform note**: Terraform moved to the BUSL-1.1 license; use **OpenTofu** (MPL-2.0) if a
  strictly OSS IaC toolchain is required. The `.tf` module ecosystem remains compatible.
- Avoid AGPL for redistributed components unless the compliance impact is reviewed and accepted.

## IaC Scanners and Rule Sources (OSS)

- **Checkov, tfsec, KICS, Trivy** — IaC/misconfig scanning.
- **kube-bench** — CIS Kubernetes benchmark checks.
- **OPA/Gatekeeper** libraries — reusable policy bundles.
- **OpenCost** — cost/unit-economics signals for FinOps.
- **Chaos Mesh** (or Azure Chaos Studio) — DR/Chaos experiments.

These feed the rule catalog ([phase-1-rule-catalog-t0.md](phases/phase-1-rule-catalog-t0.md)).

## Supply-Chain and Quality Tooling

- **Lockfiles** pin every dependency; CI installs from the lockfile only.
- **Secret scanning** (gitleaks) and **dependency/vulnerability audit** run in CI and block on
  high-severity findings.
- **Linters/formatters** (e.g., ESLint/Prettier or Ruff/Black) and the test framework are part
  of the required CI gate, matching the testing rules in
  [coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md).
- Generate an **SBOM** for released artifacts to support downstream fork audits.

## Local Development

- Docker Compose brings up **PostgreSQL with pgvector** so local schema and vector behavior
  match production (SQLite is avoided for integration paths because it lacks pgvector).
- **Event-bus fidelity gap**: Service Bus has no first-party local emulator, so local runs use
  an abstraction-compatible substitute (e.g., an in-memory bus or NATS) behind the same event
  interface. Ordering, DLQ, and idempotency behavior are therefore also covered by a
  cloud-integration test stage, not local runs alone.
- Deterministic engine and risk gate run fully offline (no cloud calls) for fast unit tests.
- Fixtures for rule-catalog entries and event payloads are English and secret-free.

## Open Decisions

Tracked as lightweight decision records; each stays open until Status is Decided. Full ADRs
land under the project structure defined in
[project-structure.md](project-structure.md).

### OD-1: Core runtime language

- **Context**: adapters, LLM SDKs, and rule tooling drive the choice.
- **Options**: TypeScript (Node) · Python · Go.
- **Criteria**: adapter/SDK maturity, team familiarity, typing/perf headroom.
- **Status**: Open — target decision in Phase 0.

### OD-2: Primary state store

- **Context**: audit log, pattern library, and T1 embeddings.
- **Options**: PostgreSQL + pgvector · Cosmos DB.
- **Criteria**: see [Data Store Selection](#data-store-selection-criteria) (portability, scale,
  cost model).
- **Status**: Open — PostgreSQL is the leaning default.

### OD-3: Multi-cloud event bus (Phase 4 — TBD)

- **Context**: portability beyond Azure's event services. Non-Azure targets are TBD (see
  [Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must));
  revisit only when a non-Azure adapter is scoped.
- **Options**: stay on Service Bus + Event Grid · Kafka · NATS JetStream.
- **Criteria**: ordering + DLQ guarantees, replay needs, operational cost, CSP neutrality.
- **Status**: Deferred (TBD) — Azure remains the only implemented target.
