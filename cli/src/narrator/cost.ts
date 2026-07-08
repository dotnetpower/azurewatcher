/**
 * Read-only Azure cost via the Cost Management query API, so the narrator can
 * answer "this month's cost", "most expensive resource group", "where is spend
 * going", and cost-spike questions with real numbers - the Cost Governance
 * vertical's live data. Authenticates with the operator's `az login`. Bounded.
 */

import { azSubscriptionId, azToken, MGMT_RESOURCE } from "./azure-token.js";

const TIMEFRAMES = ["MonthToDate", "BillingMonthToDate", "TheLastMonth", "WeekToDate"];
const DIMENSIONS = ["ResourceGroupName", "ServiceName", "ResourceType", "ResourceLocation"];
const TOP_N = 8;

interface CostResponse {
  error?: { message?: string };
  properties?: { columns?: Array<{ name?: string }>; rows?: unknown[][] };
}

/** Aggregate Azure cost grouped by a dimension over a timeframe (read-only). */
export async function getCost(
  timeframe = "MonthToDate",
  groupBy = "ResourceGroupName",
): Promise<string> {
  const tf = TIMEFRAMES.includes(timeframe) ? timeframe : "MonthToDate";
  const dim = DIMENSIONS.includes(groupBy) ? groupBy : "ResourceGroupName";
  const sub = await azSubscriptionId();
  const url = `${MGMT_RESOURCE}/subscriptions/${sub}/providers/Microsoft.CostManagement/query?api-version=2023-03-01`;
  const body = {
    type: "ActualCost",
    timeframe: tf,
    dataset: {
      granularity: "None",
      aggregation: { total: { name: "Cost", function: "Sum" } },
      grouping: [{ type: "Dimension", name: dim }],
    },
  };
  const token = await azToken();
  const res = await fetch(url, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 200);
    throw new Error(`Cost Management ${res.status} ${res.statusText}: ${detail}`);
  }
  const data = (await res.json()) as CostResponse;
  if (data.error) throw new Error(data.error.message ?? "Cost Management error");
  const cols = (data.properties?.columns ?? []).map((c) => c.name ?? "");
  const ci = cols.indexOf("Cost");
  const gi = cols.indexOf(dim);
  const curIdx = cols.indexOf("Currency");
  const rows = (data.properties?.rows ?? []).map((r) => ({
    cost: Number(r[ci] ?? 0),
    name: String(r[gi] ?? "(none)"),
    currency: curIdx >= 0 ? String(r[curIdx]) : "USD",
  }));
  if (rows.length === 0) return `no cost data for ${tf}`;
  const total = rows.reduce((s, r) => s + r.cost, 0);
  const currency = rows[0]?.currency ?? "USD";
  rows.sort((a, b) => b.cost - a.cost);
  const top = rows.slice(0, TOP_N).map((r) => `${r.name} ${r.cost.toFixed(2)}`);
  return `${tf} cost by ${dim}: total ${total.toFixed(2)} ${currency} - ${top.join("; ")}`;
}
