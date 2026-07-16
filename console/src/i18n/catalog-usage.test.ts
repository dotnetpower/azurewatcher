import { readdirSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { describe, expect, test } from "vitest";
import mainCatalog from "./messages.en.json";
import liveCatalog from "../routes/i18n/live.messages.en.json";

const SOURCE_ROOT = join(process.cwd(), "src");
const STATIC_TRANSLATION = /\bt\(\s*["']([^"']+)["']/g;
const HARDCODED_JSX_TEXT = />\s*([A-Z][^<{]*?)\s*</g;

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (!entry.isFile() || ![".ts", ".tsx"].includes(extname(entry.name))) return [];
    if (entry.name.endsWith(".test.ts") || entry.name.endsWith(".test.tsx")) return [];
    return [path];
  });
}

function catalogKeys(value: unknown, prefix = ""): Set<string> {
  const keys = new Set<string>();
  if (typeof value === "string") {
    keys.add(prefix);
    return keys;
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) return keys;
  for (const [key, child] of Object.entries(value)) {
    const childPrefix = prefix ? `${prefix}.${key}` : key;
    for (const nested of catalogKeys(child, childPrefix)) keys.add(nested);
  }
  return keys;
}

function staticKeys(source: string): string[] {
  return [...source.matchAll(STATIC_TRANSLATION)].map((match) => match[1]!);
}

describe("console static translation keys", () => {
  test("all literal t() calls resolve in their English source catalog", () => {
    const mainKeys = catalogKeys(mainCatalog);
    const liveKeys = catalogKeys({ live: liveCatalog });
    const missing: string[] = [];

    for (const file of sourceFiles(SOURCE_ROOT)) {
      const source = readFileSync(file, "utf8");
      const expected = source.includes('from "./i18n/live"') ? liveKeys : mainKeys;
      for (const key of staticKeys(source)) {
        if (!expected.has(key)) missing.push(`${relative(SOURCE_ROOT, file)}: ${key}`);
      }
    }

    expect(missing).toEqual([]);
  });

  test("account-scoped General Settings has no hardcoded English JSX", () => {
    const source = readFileSync(join(SOURCE_ROOT, "routes/settings.tsx"), "utf8");
    const accountSections = source.slice(source.indexOf('aria-labelledby="settings-user-context"'));
    const hardcoded = [...accountSections.matchAll(HARDCODED_JSX_TEXT)]
      .map((match) => match[1]!.trim())
      .filter(Boolean);
    expect(hardcoded).toEqual([]);
  });
});
