/**
 * Read-only Azure compute quota / capacity headroom via the Compute usages API,
 * so the narrator can answer "is there quota left", "vCPU headroom", "am I near
 * a limit" with real current-vs-limit numbers. Authenticates with the operator's
 * `az login`. The region is derived from the subscription's own resources when
 * not given, so nothing is hard-coded. Bounded. Strictly read-only.
 */

import { azSubscriptionId, azToken, MGMT_RESOURCE } from "./azure-token.js";

const ARG_URL = `${MGMT_RESOURCE}/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01`;
const TOP_N = 6;

interface Usage {
  name?: { localizedValue?: string; value?: string };
  currentValue?: number;
  limit?: number;
}

/** The region hosting the most resources (so quota defaults somewhere useful). */
async function busiestRegion(token: string): Promise<string> {
  const res = await fetch(ARG_URL, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({
      query: "Resources | where isnotempty(location) | summarize c=count() by location | top 1 by c",
    }),
  });
  if (!res.ok) return "";
  const data = (await res.json()) as { data?: Array<{ location?: string }> };
  return data.data?.[0]?.location ?? "";
}

/** Compute quota utilization for a region, highest-utilization first. */
export async function getQuota(location = ""): Promise<string> {
  const token = await azToken();
  const sub = await azSubscriptionId();
  const loc = location.trim() || (await busiestRegion(token));
  if (!loc) return "get_quota: could not determine a region - specify a location (an Azure region)";
  const url =
    `${MGMT_RESOURCE}/subscriptions/${sub}/providers/Microsoft.Compute/locations/` +
    `${encodeURIComponent(loc)}/usages?api-version=2023-07-01`;
  const res = await fetch(url, { headers: { authorization: `Bearer ${token}` } });
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 200);
    throw new Error(`Compute usages ${res.status} ${res.statusText}: ${detail}`);
  }
  const data = (await res.json()) as { value?: Usage[] };
  const rows = (data.value ?? [])
    .filter((v) => (v.limit ?? 0) > 0)
    .map((v) => ({
      name: v.name?.localizedValue ?? v.name?.value ?? "quota",
      cur: v.currentValue ?? 0,
      lim: v.limit ?? 0,
    }));
  if (rows.length === 0) return `no compute quota data for ${loc}`;
  rows.sort((a, b) => b.cur / b.lim - a.cur / a.lim);
  const top = rows.slice(0, TOP_N).map((r) => `${r.name}: ${r.cur}/${r.lim} (${Math.round((r.cur / r.lim) * 100)}%)`);
  return `${loc} compute quota (highest utilization first) - ${top.join("; ")}`;
}
