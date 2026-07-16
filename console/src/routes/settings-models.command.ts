import type { AuthContext } from "../auth";
import { decodeModelSettings, type ModelSettingsView } from "./settings-models.model";

export class ModelSettingsCommandError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ModelSettingsCommandError";
  }
}

export async function saveNarratorPreference(
  auth: AuthContext,
  readApiBaseUrl: string,
  preferredNarratorModel: string,
): Promise<ModelSettingsView> {
  return putModelSettings(auth, readApiBaseUrl, "/me/model-preferences", {
    preferred_narrator_model: preferredNarratorModel,
  });
}

export async function saveWebSearchSettings(
  auth: AuthContext,
  readApiBaseUrl: string,
  input: {
    readonly enabled: boolean;
    readonly allowedDomains: readonly string[];
    readonly expectedRevision: number;
  },
): Promise<ModelSettingsView> {
  return putModelSettings(auth, readApiBaseUrl, "/models/web-search-settings", {
    enabled: input.enabled,
    allowed_domains: [...input.allowedDomains],
    expected_revision: input.expectedRevision,
  });
}

async function putModelSettings(
  auth: AuthContext,
  readApiBaseUrl: string,
  path: string,
  body: Record<string, unknown>,
): Promise<ModelSettingsView> {
  const authorization = await auth.getAuthorizationHeader();
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
  };
  if (authorization !== null) headers.authorization = authorization;
  const response = await fetch(`${readApiBaseUrl.replace(/\/$/, "")}${path}`, {
    method: "PUT",
    headers,
    credentials: "omit",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errorBody = await response.json() as {
        readonly detail?: unknown;
        readonly error?: { readonly message?: unknown };
      };
      if (typeof errorBody.detail === "string") detail = errorBody.detail;
      else if (typeof errorBody.error?.message === "string") detail = errorBody.error.message;
    } catch {
      // Keep the bounded status fallback.
    }
    throw new ModelSettingsCommandError(detail, response.status);
  }
  return decodeModelSettings(await response.json());
}
