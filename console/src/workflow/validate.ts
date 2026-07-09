/**
 * Workflow authoring client - the one non-GET call the console makes,
 * kept OUT of the GET-only `ReadApiClient` exactly like the chat backend
 * (`deck/backend.ts`).
 *
 * `POST /workflows/validate` is a pure, read-only validation: it runs the
 * server-side workflow loader against a draft and returns the aggregated
 * issues plus a canonical YAML preview. It writes no state and never
 * creates a PR - the operator copies the previewed YAML into a
 * remediation PR through the git-native path (app-shape.instructions.md
 * § Operator console). The `ActionType` palette itself is a plain GET and
 * is fetched through `ReadApiClient.panel`.
 *
 * Auth: the signed-in operator's bearer token is threaded here through a
 * module singleton set once at app init (mirroring `deck/deck-user.ts`),
 * so the Reader-gated route authenticates in production while dev mode
 * (no token) still works.
 */

import type { AuthContext } from "../auth";
import { loadConfig } from "../config";

/** One ActionType the builder maps a step onto. */
export interface ActionTypePaletteEntry {
  readonly name: string;
  readonly operation: string;
  readonly category: string | null;
  readonly rollback_contract: string;
  readonly irreversible: boolean;
  readonly default_mode: string;
  readonly execution_path: string | null;
  readonly env_scope: string;
  /** Tiers (T0/T1/T2) whose ceiling escalates this action to HIL. */
  readonly hil_tiers: readonly string[];
  readonly description: string | null;
}

export interface ActionTypePaletteResponse {
  readonly action_types: readonly ActionTypePaletteEntry[];
  readonly count: number;
}

/** One validation issue keyed to a draft path. */
export interface WorkflowIssue {
  readonly key: string;
  readonly message: string;
}

export interface ValidateResponse {
  readonly valid: boolean;
  readonly issues: readonly WorkflowIssue[];
  readonly yaml_preview: string | null;
}

let authContext: AuthContext | null = null;

/** Set once at app init so the validate POST can attach the bearer token. */
export function setWorkflowAuth(auth: AuthContext | null): void {
  authContext = auth;
}

function validateUrl(): string {
  const cfg = loadConfig();
  const base =
    cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
  return `${base.replace(/\/$/, "")}/workflows/validate`;
}

/**
 * Validate a draft Workflow mapping server-side. Returns the structured
 * validation result. Throws only on a transport / non-validation error
 * (e.g. 404 when the route is not wired, network failure); a well-formed
 * draft that fails validation resolves with `valid: false`.
 */
export async function validateWorkflowDraft(
  draft: Record<string, unknown>,
): Promise<ValidateResponse> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json",
  };
  const authHeader = authContext ? await authContext.getAuthorizationHeader() : null;
  if (authHeader !== null) headers["authorization"] = authHeader;

  const response = await fetch(validateUrl(), {
    method: "POST",
    headers,
    body: JSON.stringify(draft),
    credentials: "omit",
  });
  if (response.status === 404) {
    throw new Error(
      "The workflow authoring route is not wired on this deployment. " +
        "Set ReadApiConfig.workflow_authoring in the composition root to enable it.",
    );
  }
  if (response.status === 400) {
    // Malformed request body (not the same as a failed validation).
    let detail = "invalid request body";
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) detail = body.error;
    } catch {
      /* non-JSON body - keep the generic message */
    }
    throw new Error(detail);
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as ValidateResponse;
}
