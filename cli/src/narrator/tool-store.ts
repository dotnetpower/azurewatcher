/**
 * Loads the shared operator-console tool contracts (description + input_schema)
 * from the ontology manifest (`rule-catalog/operator-console/tools.v1.yaml`), so
 * the model-facing tool contract is authored once and reused by every surface.
 * Each surface keeps its own `run` implementation; only the description and JSON
 * schema are shared. The Python read-API chat backend loads the same manifest.
 *
 * The manifest lives outside `rule-catalog/prompts/` on purpose: that tree is
 * validated as prompt/T2-tool artifacts by their own registries, and a console
 * tool manifest is neither - keeping it here avoids polluting or breaking them.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import yaml from "js-yaml";

const MANIFEST_REL = "rule-catalog/operator-console/tools.v1.yaml";

export interface ToolSpec {
  description: string;
  parameters: Record<string, unknown>;
}

function resolveFromRepo(relPath: string): string | null {
  let dir = path.dirname(fileURLToPath(import.meta.url));
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, relPath);
    if (fs.existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

let cache: Record<string, ToolSpec> | null = null;

function load(): Record<string, ToolSpec> {
  if (cache) return cache;
  const specs: Record<string, ToolSpec> = {};
  const file = resolveFromRepo(MANIFEST_REL);
  if (file) {
    try {
      const doc = yaml.load(fs.readFileSync(file, "utf8")) as {
        tools?: Array<{ id?: unknown; description?: unknown; input_schema?: unknown }>;
      };
      for (const t of doc?.tools ?? []) {
        if (typeof t.id === "string" && typeof t.description === "string") {
          specs[t.id] = {
            description: t.description.trim(),
            parameters:
              t.input_schema && typeof t.input_schema === "object"
                ? (t.input_schema as Record<string, unknown>)
                : { type: "object", additionalProperties: false },
          };
        }
      }
    } catch {
      /* fall through to the minimal specs below */
    }
  }
  if (Object.keys(specs).length === 0) {
    process.stderr.write("[tools] shared tool manifest not found; using minimal specs\n");
  }
  cache = specs;
  return cache;
}

/** The shared contract (description + JSON-schema parameters) for a tool id.
 * Falls back to a minimal object so a tool still works if the manifest is
 * missing. */
export function toolSpec(id: string): ToolSpec {
  const found = load()[id];
  return found ?? { description: id, parameters: { type: "object", additionalProperties: false } };
}
