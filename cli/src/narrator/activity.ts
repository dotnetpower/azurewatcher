/**
 * Read-only Azure Activity Log (management operations) so the narrator can
 * answer "why did the deploy fail", "who changed/did something", "recent
 * errors" from real control-plane events. Authenticates with the operator's
 * `az login`. Bounded window and row cap. Strictly read-only.
 */

import { azSubscriptionId, azToken, MGMT_RESOURCE } from "./azure-token.js";

const MAX_ROWS = 12;

interface ActivityEvent {
  eventTimestamp?: string;
  caller?: string;
  status?: { value?: string };
  operationName?: { localizedValue?: string; value?: string };
  resourceGroupName?: string;
}

/** Recent Azure Activity Log events. `hours` is the look-back window; `filter`
 * narrows results ('failed'/'error' -> only failures, else a text match on the
 * operation/resource-group). */
export async function getActivityLog(hours = 24, filter = ""): Promise<string> {
  const sub = await azSubscriptionId();
  const window = Math.min(168, Math.max(1, Math.round(hours)));
  const from = new Date(Date.now() - window * 3_600_000).toISOString();
  const url =
    `${MGMT_RESOURCE}/subscriptions/${sub}/providers/microsoft.insights/eventtypes/management/values` +
    `?api-version=2015-04-01&$filter=${encodeURIComponent(`eventTimestamp ge '${from}'`)}`;
  const token = await azToken();
  const res = await fetch(url, { headers: { authorization: `Bearer ${token}` } });
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 200);
    throw new Error(`Activity Log ${res.status} ${res.statusText}: ${detail}`);
  }
  const data = (await res.json()) as { value?: ActivityEvent[] };
  let rows = data.value ?? [];
  const f = filter.toLowerCase().trim();
  const wantFail = /fail|error|\uc5d0\ub7ec|\uc2e4\ud328/.test(f);
  if (wantFail) {
    rows = rows.filter((r) => (r.status?.value ?? "") === "Failed");
  } else if (f) {
    rows = rows.filter((r) =>
      `${r.operationName?.localizedValue ?? ""} ${r.resourceGroupName ?? ""}`.toLowerCase().includes(f),
    );
  }
  rows.sort((a, b) => (b.eventTimestamp ?? "").localeCompare(a.eventTimestamp ?? ""));
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of rows) {
    const op = r.operationName?.localizedValue ?? r.operationName?.value ?? "operation";
    const st = r.status?.value ?? "";
    const key = `${op}|${st}|${r.resourceGroupName ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const t = (r.eventTimestamp ?? "").slice(0, 19);
    const rg = r.resourceGroupName ? ` [${r.resourceGroupName}]` : "";
    out.push(`${t} ${st}: ${op}${rg}`);
    if (out.length >= MAX_ROWS) break;
  }
  return out.length
    ? `over the last ${window}h -\n${out.join("\n")}`
    : `no matching Activity Log events in the last ${window}h${wantFail ? " (no failures)" : ""}`;
}
