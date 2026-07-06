#!/usr/bin/env node
// inject-titles.mjs - one-shot migration that adds a YAML `title`
// frontmatter field to every docs/roadmap/**/*.md and refreshes the
// paired -ko.md's translation_source_sha to match.
//
// Why: Starlight's docsSchema() requires `title`, but the canonical docs
// were authored with the title as the first Markdown H1 only. Fixing this
// by editing 48 files by hand is toil and error-prone - this script does
// the same edit uniformly, then rehashes the -ko.md pointers so the
// existing check-translations.sh gate stays green after the migration.
//
// Idempotent: files that already have a title are skipped. Files that
// already have YAML frontmatter get a `title:` line inserted at the top
// of the frontmatter block; files without any frontmatter get a fresh
// block added at the very top.
//
// After this migration lands, new docs should be authored with `title`
// front-matter from the start; the script only exists to migrate the
// pre-existing set.

import { execFileSync } from "node:child_process";
import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");
const docsSource = resolve(repoRoot, "docs", "roadmap");

/** Recursively list every *.md under `dir`. */
async function* walkMarkdown(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walkMarkdown(abs);
      continue;
    }
    if (entry.name.endsWith(".md")) yield abs;
  }
}

/** Split a Markdown file into (frontmatter, body). Frontmatter is the
 *  content between two --- fences at the very top, exclusive of the fences.
 *  Returns { frontmatter: string|null, body: string, prefixLen: number }
 *  where prefixLen is the number of bytes before body starts.
 */
function splitFrontmatter(text) {
  if (!text.startsWith("---\n")) {
    return { frontmatter: null, body: text };
  }
  const closeIdx = text.indexOf("\n---\n", 4);
  if (closeIdx === -1) return { frontmatter: null, body: text };
  const frontmatter = text.slice(4, closeIdx);
  const body = text.slice(closeIdx + 5);
  return { frontmatter, body };
}

/** Extract the first H1 (`# Heading`) text from `body`. Returns null if
 *  none is found. Strips trailing spaces, leading `#`, and inline code
 *  backticks but keeps other Markdown text intact.
 */
function firstH1(body) {
  const lines = body.split("\n");
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith("# ") && !line.startsWith("## ")) {
      return line.slice(2).trim();
    }
  }
  return null;
}

/** True if `frontmatter` already declares a title. */
function hasTitle(frontmatter) {
  if (frontmatter == null) return false;
  return /^title:\s*\S/m.test(frontmatter);
}

/** Serialise a YAML title value, quoting when it contains characters that
 *  would confuse YAML block scalars (colons, hashes, leading dashes, etc.).
 */
function yamlTitle(title) {
  const needsQuote = /[:#\[\]{}&*!|>'"%@`,]/.test(title) || /^[-?]/.test(title.trimStart());
  if (!needsQuote) return `title: ${title}`;
  const escaped = title.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return `title: "${escaped}"`;
}

/** Rewrite `filePath` to add a `title` field derived from its first H1.
 *  Returns true when the file was modified. Files that already declare a
 *  title, or that contain no H1, are left untouched.
 */
async function injectTitle(filePath) {
  const raw = await readFile(filePath, "utf8");
  const { frontmatter, body } = splitFrontmatter(raw);
  if (hasTitle(frontmatter)) return false;
  const title = firstH1(body);
  if (!title) return false;

  let updated;
  if (frontmatter == null) {
    updated = `---\n${yamlTitle(title)}\n---\n${raw}`;
  } else {
    // Insert the title as the first key of the existing frontmatter block.
    updated = `---\n${yamlTitle(title)}\n${frontmatter}\n---\n${body}`;
  }
  await writeFile(filePath, updated);
  return true;
}

/** Refresh `translation_source_sha` in `-ko.md` files so the existing
 *  check-translations.sh gate accepts the new content of their English
 *  sibling. Called after all title injections are complete.
 */
async function refreshKoSha(koPath) {
  const raw = await readFile(koPath, "utf8");
  const { frontmatter, body } = splitFrontmatter(raw);
  if (frontmatter == null) return false;
  const enPath = koPath.replace(/-ko\.md$/, ".md");
  const enStat = await stat(enPath).catch(() => null);
  if (!enStat || !enStat.isFile()) return false;
  const currentSha = execFileSync("git", ["hash-object", enPath], {
    cwd: repoRoot,
    encoding: "utf8",
  }).trim();
  const nextFrontmatter = frontmatter.replace(
    /^translation_source_sha:\s*[0-9a-f]+\s*$/m,
    `translation_source_sha: ${currentSha}`,
  );
  if (nextFrontmatter === frontmatter) return false;
  await writeFile(koPath, `---\n${nextFrontmatter}\n---\n${body}`);
  return true;
}

async function main() {
  const files = [];
  for await (const path of walkMarkdown(docsSource)) files.push(path);

  let injected = 0;
  for (const f of files) {
    if (await injectTitle(f)) injected += 1;
  }
  console.log(`inject-titles: title injected into ${injected} of ${files.length} files.`);

  let rehashed = 0;
  for (const f of files.filter((p) => p.endsWith("-ko.md"))) {
    if (await refreshKoSha(f)) rehashed += 1;
  }
  console.log(`inject-titles: refreshed translation_source_sha in ${rehashed} -ko.md files.`);
}

main().catch((err) => {
  console.error("inject-titles: failed -", err);
  process.exit(1);
});
