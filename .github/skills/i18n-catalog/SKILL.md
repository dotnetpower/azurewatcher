---
name: i18n-catalog
description: |
  FDAI i18n catalog workflow: L0 machine surfaces stay English forever,
  L1 developer docs ship `.md` + `-ko.md` pairs under a SHA gate, L2
  product surfaces (console, CLI, chatops, notifications, site)
  localize via English-source message catalogs with mandatory English
  fallback, L3 the Bragi narrator renders in the operator's locale
  over an English pipeline. Load this skill when adding, editing, or
  reviewing localized strings, message catalogs (`messages.{en,ko}.json`),
  bilingual doc pairs, or when a check-english-only / check-catalog-parity
  / check-translations gate fails.
version: 1.0.0
scope: repository
---

# i18n Catalog Workflow

The short-form contract is
[.github/instructions/language.instructions.md](../../instructions/language.instructions.md)
(always loaded). This skill is the runnable workflow that operationalizes
the four-layer policy across the code, docs, product catalogs, and CI
gates.

## The Four Layers (recap)

| Layer | Surface | Rule |
|-------|---------|------|
| **L0** | code, identifiers, logs, error codes, audit entries, event payloads, generated PR bodies, Rego, config keys | **English forever.** Never localized. |
| **L1** | root `README.md` + `docs/**/*.md` | English `.md` + `-ko.md` sibling with a SHA-parity gate. |
| **L2** | operator console, CLI, chatops cards, notifications, docs site | English-source message catalogs + `ko` overlay, mandatory English fallback. |
| **L3** | Bragi narrator | Renders in operator locale over an English pipeline. |

## L1: Doc Pair (`.md` + `-ko.md`)

Every user-facing markdown doc ships bilingual. Scope = root `README.md`
+ everything under `docs/**/*.md`. `.github/**` and `docs/internals/**`
stay English-only.

### File pair convention

- English is canonical: `foo.md`.
- Korean is a sibling: `foo-ko.md` (never Korean-only).
- The `-ko.md` file carries YAML front-matter:
  ```yaml
  ---
  translation_of: foo.md
  translation_source_sha: <git blob sha of foo.md at translation time>
  translation_revised: 2026-07-05
  ---
  ```
- Compute the SHA with `git hash-object foo.md`.

### Paired-update rule (MUST)

- **Any edit to `foo.md` MUST update `foo-ko.md` in the same PR**, and
  vice versa. Adding a new user-facing `foo.md` MUST add `foo-ko.md`.
- CI enforces this via [`scripts/check-translations.sh`](../../../scripts/check-translations.sh):
  compares `git hash-object foo.md` against the `translation_source_sha`
  recorded in `foo-ko.md`.
- After editing English docs, run
  [`scripts/refresh-translation-sha.py`](../../../scripts/refresh-translation-sha.py)
  to re-sync all pair SHAs at once (only files whose SHA changed are
  rewritten).

### Content rules

- Same information, structure, headings. Translation, not rewrite.
- Preserve unchanged: code blocks, tables of technical values, links,
  filenames, domain vocabulary in backticks (`T0`, `T1`, `T2`, `HIL`,
  `trust-router`, `deterministic-engine`, `rule-catalog`, `risk-gate`,
  `remediation-pr`, `shadow-mode`).
- Cross-references point language-consistently: `foo-ko.md` links to
  `bar-ko.md` (not `bar.md`), unless the target is English-only
  (`.github/**`).

## L2: Message Catalogs

Every L2 surface exposes one catalog pair. English is the source of
truth; Korean MAY lag.

### Where they live

- CLI: [`cli/src/i18n/messages.{en,ko}.json`](../../../cli/src/i18n/)
- Console: [`console/src/i18n/messages.{en,ko}.json`](../../../console/src/i18n/)
- Notifications core:
  [`src/fdai/core/notifications/messages.{en,ko}.json`](../../../src/fdai/core/notifications/)
- Site (Astro Starlight): built-in `locales: { root: {lang: en},
  ko: {lang: ko} }` in `astro.config.mjs` - no separate JSON pair.

### Runtime contract

- **Source strings are English.** Every user-visible string starts as
  an English key in the catalog, never a hard-coded literal.
- **English fallback is MANDATORY.** A missing or empty `ko` key MUST
  render the English source, never blank / key-name / error.
- Locale resolution order:
  `UserPreference.locale` -> `Accept-Language` -> default `en`.
- Helper contract (mirrors `cli/src/i18n/index.ts`):
  `t(key, locale="en", params?)` with `{name}` interpolation and
  dot-path lookup.

### Catalog-parity gate

- CI runs [`scripts/check-catalog-parity.sh`](../../../scripts/check-catalog-parity.sh):
  every key in `<name>.ko.json` MUST exist in `<name>.en.json`. Orphan
  `ko` keys are blocked; `en` is the source of truth. `ko` MAY be a
  subset (fallback covers it).

### English-only gate escape hatches

Non-English text is allowed only in these paths (allowlisted at the
top of [`scripts/check-english-only.sh`](../../../scripts/check-english-only.sh)):

- `messages.ko.json` (any surface).
- `foo-ko.md` translations.
- The Astro Starlight `ko` locale under `site/src/content/docs/ko/`.
- A small named set of translation-tooling helper files.

Adding to the allowlist requires a one-line reason at the top of the
script. Do not put Hangul in `.py`, `.ts`, `.yaml`, or code tests -
use `\uXXXX` escapes or structural assertions.

## L3: Bragi Narrator

- Bragi renders the final natural-language answer in
  `UserPreference.locale`. Everything beneath the answer (intent,
  tool calls, verdict, audit entry) stays English (L0).
- A localized phrasing MUST NOT change what the typed pipeline
  decides. The narrator is a presentation translator, never a judge.

## Punctuation and Formats

- **ASCII punctuation only** (blocked by
  [`scripts/check-punctuation.sh`](../../../scripts/check-punctuation.sh)):
  `-`, `"`, `'`, `...`. No em-dash / en-dash / smart quotes /
  ellipsis character / no-break space. This applies inside `-ko.md`
  and inside `.ko.json` too.
- Auto-fix: `python3 scripts/normalize-punctuation.py` (fence-aware
  for `.md`; add `--whole-file` for source files whose content is
  entirely code).
- Timestamps: ISO 8601 / RFC 3339. Decimal separator `.`; no digit
  grouping in machine values.

## Common Failure Modes

- **Catalog-parity failure**: a `ko` key without an `en` peer. Fix by
  adding the English source key first, then translating (or removing
  the orphan `ko` key). Never invent `ko` keys the `en` catalog
  doesn't have.
- **Translation-pair failure**: `git hash-object foo.md` does not
  match the `translation_source_sha` in `foo-ko.md`. Update the
  Korean file to reflect the English edit, then run
  `refresh-translation-sha.py`.
- **English-only failure**: Hangul or CJK appeared in a `.py` / `.ts`
  / `.yaml` / test file. Move it to the correct `.ko.json` or
  `-ko.md` sibling, or escape it (`\uXXXX`) if it is a literal
  fixture that must stay in code.
- **Punctuation failure**: an em-dash or smart quote snuck in via
  copy-paste. Run `normalize-punctuation.py`.

## Verify

Before every commit that touches L1 or L2:

```
bash scripts/verify.sh --fast
```

The `--fast` bundle runs all four gates: `english-only`,
`punctuation`, `translations`, `catalog-parity` (plus ruff + guids).

## Related

- Language contract:
  [.github/instructions/language.instructions.md](../../instructions/language.instructions.md).
- Repo-scoped implementation notes:
  [`/memories/repo/i18n.md`](../../../.github/copilot-instructions.md) (memory listing).
- Runnable prompt:
  [.github/prompts/verify.prompt.md](../../prompts/verify.prompt.md).
