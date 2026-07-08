/**
 * Shared Azure AD token minted from the operator's `az login`
 * (`az account get-access-token`). Read-only surfaces (Resource Graph
 * inventory, Azure Monitor metrics) use this so natural-language ops work with
 * zero secrets in the environment. Cached until shortly before expiry.
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

// Public Azure ARM audience - identical for every tenant, not a customer value.
export const MGMT_RESOURCE = "https://management.azure.com";

const cache = new Map<string, { token: string; expiresAt: number }>();

/** Mint (and cache) an Azure AD bearer token for the given resource audience. */
export async function azToken(resource: string = MGMT_RESOURCE): Promise<string> {
  const now = Date.now();
  const hit = cache.get(resource);
  if (hit && hit.expiresAt - 60_000 > now) return hit.token;
  let stdout: string;
  try {
    ({ stdout } = await execFileAsync(
      "az",
      ["account", "get-access-token", "--resource", resource, "--query", "accessToken", "-o", "tsv"],
      { timeout: 20_000 },
    ));
  } catch (err) {
    throw new Error(`could not get an Azure token via 'az' (run 'az login'): ${(err as Error).message}`);
  }
  const token = stdout.trim();
  if (!token) throw new Error("'az account get-access-token' returned no token (run 'az login')");
  cache.set(resource, { token, expiresAt: now + 50 * 60_000 });
  return token;
}

let subCache: string | null = null;

/** The current subscription id from `az account show`, cached. Read-only. */
export async function azSubscriptionId(): Promise<string> {
  if (subCache) return subCache;
  let stdout: string;
  try {
    ({ stdout } = await execFileAsync("az", ["account", "show", "--query", "id", "-o", "tsv"], {
      timeout: 15_000,
    }));
  } catch (err) {
    throw new Error(`could not read the subscription via 'az' (run 'az login'): ${(err as Error).message}`);
  }
  const id = stdout.trim();
  if (!id) throw new Error("'az account show' returned no subscription id (run 'az login')");
  subCache = id;
  return id;
}
