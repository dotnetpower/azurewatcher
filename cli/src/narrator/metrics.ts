/**
 * Read-only Azure Monitor metrics for a resource, so the narrator can diagnose
 * performance symptoms (a slow DB, a hot app) with real numbers instead of
 * guessing. Authenticates with the operator's `az login` (ARM token). Bounded:
 * a capped set of metrics over a capped window. Strictly read-only.
 */

import { azToken, MGMT_RESOURCE } from "./azure-token.js";

const MAX_METRICS = 6;

interface MetricValue {
  name?: { value?: string };
  unit?: string;
  timeseries?: Array<{ data?: Array<{ average?: number; maximum?: number }> }>;
}

/** Fetch recent Azure Monitor metrics for a resource ARM id. `metrics` is a
 * comma-separated list of metric names; `hours` is the look-back window. */
export async function getMetrics(resourceId: string, metrics: string, hours = 1): Promise<string> {
  const id = resourceId.trim();
  if (!id.startsWith("/subscriptions/")) {
    return "get_metrics: resourceId must be a full ARM id (get it from query_inventory by projecting id)";
  }
  const names = metrics
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, MAX_METRICS);
  if (names.length === 0) return "get_metrics: provide one or more metric names";
  const window = Math.min(24, Math.max(1, Math.round(hours)));
  const url =
    `${MGMT_RESOURCE}${id}/providers/microsoft.insights/metrics?api-version=2018-01-01` +
    `&metricnames=${encodeURIComponent(names.join(","))}` +
    `&timespan=PT${window}H&interval=PT15M&aggregation=Average,Maximum`;
  const token = await azToken();
  const res = await fetch(url, { headers: { authorization: `Bearer ${token}` } });
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 200);
    throw new Error(`Azure Monitor ${res.status} ${res.statusText}: ${detail}`);
  }
  const data = (await res.json()) as { value?: MetricValue[] };
  const lines: string[] = [];
  for (const m of data.value ?? []) {
    const pts = m.timeseries?.[0]?.data ?? [];
    const recent = pts.slice(-4);
    const avgs = recent.map((p) => p.average).filter((v): v is number => typeof v === "number");
    const maxs = recent.map((p) => p.maximum).filter((v): v is number => typeof v === "number");
    const lastAvg = avgs.length ? avgs[avgs.length - 1] : null;
    const peak = maxs.length ? Math.max(...maxs) : null;
    const unit = m.unit && m.unit !== "Count" ? ` ${m.unit}` : "";
    lines.push(`${m.name?.value ?? "metric"}: recent avg ${lastAvg ?? "n/a"}, peak ${peak ?? "n/a"}${unit}`);
  }
  return lines.length
    ? `over the last ${window}h - ${lines.join("; ")}`
    : "no metric data (the resource may be idle, stopped, or the metric name is wrong for this type)";
}
