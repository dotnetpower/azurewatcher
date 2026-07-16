import type { AuthContext } from "../auth";
import { GovernedCommandError, putGovernedJson } from "../governed-command";
import { decodeModelSettings, type ModelSettingsView } from "./settings-models.model";

export { GovernedCommandError as ModelSettingsCommandError };

export async function saveNarratorPreference(
  auth: AuthContext,
  readApiBaseUrl: string,
  preferredNarratorModel: string,
  expectedRevision: number,
): Promise<ModelSettingsView> {
  return putModelSettings(auth, readApiBaseUrl, "/me/model-preferences", {
    preferred_narrator_model: preferredNarratorModel,
    expected_revision: expectedRevision,
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
  return decodeModelSettings(await putGovernedJson(auth, readApiBaseUrl, path, body));
}
