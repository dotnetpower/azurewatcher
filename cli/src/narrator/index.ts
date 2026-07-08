/**
 * Narrator factory - picks the LLM narrator when configured, else deterministic.
 *
 * Natural language works with ZERO manual setup when the machine already has an
 * Azure OpenAI endpoint resolved (via the project's `resolved-models.json`) and
 * an `az login`: the narrator authenticates with an Azure AD token minted from
 * `az` - no API key, no `FDAI_NARRATOR_*` exports needed. Resolution order:
 *
 *   1. Explicit API-key config (highest priority, overrides everything):
 *        FDAI_NARRATOR_BASE_URL, FDAI_NARRATOR_API_KEY, FDAI_NARRATOR_MODEL
 *        (+ optional FDAI_NARRATOR_PROVIDER=openai|azure, FDAI_NARRATOR_API_VERSION)
 *   2. `resolved-models.json` (`LLM_RESOLVED_MODELS_PATH`, else searched upward
 *        from the cwd) carrying a `narrator` block:
 *        { "endpoint": "...", "deployment": "...", "api_version"?: "..." }
 *        -> Azure OpenAI via `az login` (keyless, zero config).
 *   3. FDAI_LLM_ENDPOINT (the pipeline's own endpoint var) -> Azure via az login.
 *
 * With none of these resolvable, the CLI uses the deterministic narrator.
 * `readLlmConfig` is pure (env only); disk resolution lives in `createNarrator`.
 */

import fs from "node:fs";
import path from "node:path";

import { DeterministicNarrator } from "./deterministic.js";
import { LlmNarrator, type LlmConfig } from "./llm.js";
import type { Narrator } from "./types.js";

export type { Narrator, NarratorContext } from "./types.js";

const DEFAULT_API_VERSION = "2024-08-01-preview";

export function readLlmConfig(
  env: NodeJS.ProcessEnv = process.env,
): LlmConfig | null {
  // 1. Explicit API-key config.
  const baseUrl = env.FDAI_NARRATOR_BASE_URL;
  const apiKey = env.FDAI_NARRATOR_API_KEY;
  const model = env.FDAI_NARRATOR_MODEL;
  if (baseUrl && apiKey && model) {
    const provider = env.FDAI_NARRATOR_PROVIDER === "azure" ? "azure" : "openai";
    return {
      provider,
      baseUrl,
      apiKey,
      model,
      apiVersion: env.FDAI_NARRATOR_API_VERSION ?? DEFAULT_API_VERSION,
      auth: "api-key",
    };
  }
  // 3. Pipeline endpoint var + az login (keyless). (2. is disk-based, in the
  // factory below.) Requires a deployment name via FDAI_NARRATOR_MODEL.
  const endpoint = env.FDAI_LLM_ENDPOINT;
  if (endpoint && model) {
    return {
      provider: "azure",
      baseUrl: endpoint,
      apiKey: "",
      model,
      apiVersion: env.FDAI_NARRATOR_API_VERSION ?? DEFAULT_API_VERSION,
      auth: "azure-ad",
    };
  }
  return null;
}

/** Locate `resolved-models.json`: an explicit `LLM_RESOLVED_MODELS_PATH` (no
 * fallback when set, so tests stay hermetic), else searched upward from cwd. */
function findResolvedModelsPath(env: NodeJS.ProcessEnv): string | null {
  const explicit = env.LLM_RESOLVED_MODELS_PATH;
  if (explicit !== undefined) return fs.existsSync(explicit) ? explicit : null;
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    const candidate = path.join(dir, "resolved-models.json");
    if (fs.existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

/** Resolve a keyless Azure narrator from a `resolved-models.json` `narrator`
 * block. Returns null when the file or block is absent/malformed. */
export function resolveDiskLlmConfig(
  env: NodeJS.ProcessEnv = process.env,
): LlmConfig | null {
  const file = findResolvedModelsPath(env);
  if (!file) return null;
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf8")) as {
      narrator?: { endpoint?: unknown; deployment?: unknown; api_version?: unknown };
    };
    const n = raw.narrator;
    if (n && typeof n.endpoint === "string" && typeof n.deployment === "string") {
      return {
        provider: "azure",
        baseUrl: n.endpoint,
        apiKey: "",
        model: n.deployment,
        apiVersion: typeof n.api_version === "string" ? n.api_version : DEFAULT_API_VERSION,
        auth: "azure-ad",
      };
    }
  } catch {
    /* unreadable or invalid JSON -> fall through to deterministic */
  }
  return null;
}

export function createNarrator(env: NodeJS.ProcessEnv = process.env): Narrator {
  const cfg = readLlmConfig(env) ?? resolveDiskLlmConfig(env);
  return cfg ? new LlmNarrator(cfg) : new DeterministicNarrator();
}
