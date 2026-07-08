/**
 * Read-only Azure inventory via Azure Resource Graph (ARG).
 *
 * This surfaces FDAI's Inventory seam to the operator console for questions the
 * live event stream cannot answer - "list the resource groups", "which VMs are
 * running" - by running a read-only Kusto query against ARG. It authenticates
 * with an Azure AD token minted from the operator's existing `az login`
 * (`az account get-access-token`), so it needs zero secrets in the environment.
 *
 * Strictly read-only: ARG is a query surface and cannot mutate anything. Results
 * are bounded (row cap + response-size cap) so a large subscription cannot
 * flood the cockpit. Generic: no subscription, tenant, or resource name is ever
 * hard-coded - the query sees whatever the operator's token is scoped to.
 */

import { azToken, MGMT_RESOURCE } from "./azure-token.js";

// ARG REST endpoint (ARM audience token from az login).
const ARG_URL = `${MGMT_RESOURCE}/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01`;

const MAX_ROWS = 40;
const MAX_CHARS = 1600;

interface ArgResponse {
  count?: number;
  data?: Array<Record<string, unknown>>;
  error?: { message?: string };
}

/** Run a read-only Kusto query against Azure Resource Graph and return a
 * compact, bounded, human-readable result. Throws on auth/transport errors so
 * the caller can surface a clear message. */
export async function queryInventory(kql: string): Promise<string> {
  const token = await azToken();
  const res = await fetch(ARG_URL, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ query: kql, options: { $top: MAX_ROWS } }),
  });
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 200);
    throw new Error(`Resource Graph ${res.status} ${res.statusText}: ${detail}`);
  }
  const data = (await res.json()) as ArgResponse;
  if (data.error) throw new Error(data.error.message ?? "Resource Graph error");
  const rows = (data.data ?? []).slice(0, MAX_ROWS);
  if (rows.length === 0) return "no matching resources";
  const total = data.count ?? rows.length;
  const lines = rows.map((r) =>
    Object.entries(r)
      .map(([k, v]) => `${k}=${v ?? ""}`)
      .join(" "),
  );
  let out = lines.join("\n");
  if (out.length > MAX_CHARS) out = out.slice(0, MAX_CHARS) + " ...";
  const shown = rows.length;
  return total > shown ? `${out}\n(${shown} of ${total} shown)` : out;
}
