/**
 * Narrator factory - picks the LLM narrator when configured, else deterministic.
 *
 * Enable the LLM narrator by setting these environment variables (no secret ever
 * lives in the repo - the key comes from the environment at runtime):
 *
 *   FDAI_NARRATOR_PROVIDER   openai | azure           (default: openai)
 *   FDAI_NARRATOR_BASE_URL   https://api.openai.com/v1
 *                            or https://<res>.openai.azure.com   (required)
 *   FDAI_NARRATOR_API_KEY    the API key                          (required)
 *   FDAI_NARRATOR_MODEL      model name / Azure deployment name   (required)
 *   FDAI_NARRATOR_API_VERSION  Azure api-version (default 2024-08-01-preview)
 *
 * With none set, the CLI uses the deterministic narrator and needs zero config.
 */

import { DeterministicNarrator } from "./deterministic.js";
import { LlmNarrator, type LlmConfig } from "./llm.js";
import type { Narrator } from "./types.js";

export type { Narrator, NarratorContext } from "./types.js";

export function readLlmConfig(
  env: NodeJS.ProcessEnv = process.env,
): LlmConfig | null {
  const baseUrl = env.FDAI_NARRATOR_BASE_URL;
  const apiKey = env.FDAI_NARRATOR_API_KEY;
  const model = env.FDAI_NARRATOR_MODEL;
  if (!baseUrl || !apiKey || !model) return null;
  const provider = env.FDAI_NARRATOR_PROVIDER === "azure" ? "azure" : "openai";
  return {
    provider,
    baseUrl,
    apiKey,
    model,
    apiVersion: env.FDAI_NARRATOR_API_VERSION ?? "2024-08-01-preview",
  };
}

export function createNarrator(env: NodeJS.ProcessEnv = process.env): Narrator {
  const cfg = readLlmConfig(env);
  return cfg ? new LlmNarrator(cfg) : new DeterministicNarrator();
}
