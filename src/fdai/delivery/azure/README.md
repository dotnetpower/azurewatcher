# `src/fdai/delivery/azure`

Azure-specific delivery adapters. Modules here MAY import `azure-*` SDKs;
`core/` never does. Every adapter registered here MUST implement one of the
CSP-neutral Protocols in
[`shared/providers/`](../../shared/providers/) so that a fork can swap it
out at the composition root without editing core.

Current adapters
----------------

- [`inventory.py`](inventory.py) - Azure Resource Graph (ARG) implementation
  of the `Inventory` Protocol
  ([contract](../../shared/providers/inventory.py),
  [design](../../../../docs/roadmap/csp-neutrality.md#5-inventory-contract--resource-graph)).
  Provides bounded-concurrency parallel-shard fan-out, the `final=True`
  atomic-promote fence, and the idempotent-upsert dedup precondition; the
  per-shard fetch behind it is a `ResourceQueryFn` bound at the composition
  root.
- [`arg_query.py`](arg_query.py) - `AzureArgQueryFactory`, the real
  Kusto-over-ARG REST implementation of `ResourceQueryFn`. Takes a
  `WorkloadIdentity` (OIDC token issuer) + a shared `httpx.AsyncClient` +
  the CSP-neutral resource-type vocabulary and returns an async callable
  the `Inventory` adapter fans out over. Handles `$skipToken` pagination
  under a bounded page cap, truncates untrusted vendor properties, and
  fail-closes on any HTTP / JSON / body-shape error via `ArgQueryError`.
  **Link extraction (`contains` / `attached_to` / `depends_on`) is
  reserved for P2** - this file returns `()` for links today.
- [`metric_logs.py`](metric_logs.py) - `AzureMonitorLogsMetricProvider`,
  the Azure Monitor Logs (Log Analytics KQL) implementation of the
  `MetricProvider` seam ([contract](../../shared/providers/metric.py)).
  A CSP-neutral `metric_name` maps to a trusted config-supplied KQL
  template; untrusted labels are filtered in memory (no KQL injection),
  the query is bounded server-side by `timespan` + `max_rows`, and any
  partial / malformed result fail-closes via `MetricProviderError`.
- [`deployment_history.py`](deployment_history.py) -
  `AzureResourceGraphDeploymentHistory`, the Azure Resource Graph
  (`resourcechanges`-shaped) implementation of the
  `DeploymentHistoryProvider` seam
  ([contract](../../shared/providers/observation.py)). Answers "what
  changed in the estate over the window" - the change/deployment signal
  T1 causal-chain RCA reasons over and the console `query_deployments`
  tool surfaces. A trusted config-supplied Kusto template carries a
  `{window_seconds}` token (the untrusted `window` is validated to a
  positive integer second-count from an ISO-8601 duration; the untrusted
  `resource_ref` is filtered in memory - no Kusto injection). Bounded by
  `$skipToken` page cap + `max_records`; any HTTP / JSON / shape error or
  missing column fail-closes via `DeploymentHistoryError`.
