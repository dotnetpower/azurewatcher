/**
 * Loads the operator-console narrator prompt from the shared ontology prompt
 * store (`rule-catalog/prompts/`), so the prompt is authored once as
 * catalog-as-code and reused by every surface (this CLI cockpit, a web console,
 * ChatOps) instead of being hard-coded per implementation. The Python read-API
 * chat backend loads the same files via `core/prompts/registry.py`.
 *
 * Composition: the UI-agnostic base (`base/operator-console-narrator.v1.yaml`)
 * plus an optional surface overlay (the CLI cockpit's
 * `packs/operator-console-cli.v1.yaml`). A different surface supplies its own
 * pack or none and reuses the base unchanged.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import yaml from "js-yaml";

const BASE_REL = "rule-catalog/prompts/base/operator-console-narrator.v1.yaml";
const CLI_PACK_REL = "rule-catalog/prompts/packs/operator-console-cli.v1.yaml";

// Minimal fallback used only if the ontology files cannot be found (e.g. the CLI
// is run outside the repo tree). Keeps the core contract - translator, read-only,
// grounded - so the narrator still behaves safely.
const FALLBACK =
  "You are the FDAI operator-console narrator. Translate the operator's question " +
  "into read-only tool calls and answer ONLY from the tool results; never invent " +
  "facts. The console is read-only - never perform or simulate an action; refuse " +
  "change/fix/delete/approve requests plainly (remediation is a pull request). " +
  "Reply in the operator's language, concisely.";

/** Search upward from this module for the repo root that holds `relPath`. */
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

function readBody(relPath: string): string | null {
  const file = resolveFromRepo(relPath);
  if (!file) return null;
  try {
    const doc = yaml.load(fs.readFileSync(file, "utf8")) as { body?: unknown };
    return typeof doc?.body === "string" ? doc.body.trim() : null;
  } catch {
    return null;
  }
}

let cached: string | null = null;
let cachedBase: string | null = null;

/** The UI-agnostic base narrator prompt (no surface overlay), for non-cockpit
 * surfaces that supply their own or none. */
export function loadBaseNarratorPrompt(): string {
  if (cachedBase !== null) return cachedBase;
  cachedBase = readBody(BASE_REL) ?? FALLBACK;
  return cachedBase;
}

/** The composed narrator system prompt for the CLI cockpit surface (base + CLI
 * pack), loaded from the ontology prompt store and cached. */
export function loadCliNarratorPrompt(): string {
  if (cached !== null) return cached;
  const base = readBody(BASE_REL);
  const pack = readBody(CLI_PACK_REL);
  if (!base) {
    process.stderr.write(
      "[narrator] prompt store not found; using the built-in fallback prompt\n",
    );
    cached = FALLBACK;
    return cached;
  }
  cached = pack ? `${base}\n\n${pack}` : base;
  return cached;
}
