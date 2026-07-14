---
description: Language and naming policy for all FDAI artifacts.
applyTo: "**"
---

# Language Policy

> **Related on-demand skill**:
> [`.github/skills/i18n-catalog/SKILL.md`](../skills/i18n-catalog/SKILL.md)
> is the runnable workflow for L1 `.md` + `-ko.md` doc pairs, L2 message
> catalog authoring, and the SHA / parity / english-only / punctuation
> gates. Load it when you are editing catalogs, translations, or a gate
> failure sends you here.

## Scope

This policy governs everything **committed to this repository** and everything the
control plane **emits at runtime** (logs, error strings, audit records, generated PRs).
It does not govern live maintainer chat. Related rules live in
[coding-conventions.instructions.md](coding-conventions.instructions.md) (commits/PRs)
and [generic-scope.instructions.md](generic-scope.instructions.md) (no customer data).

## Language Layers (L0 - L3)

FDAI is **bilingual (English + Korean) on the surfaces humans read**, and
**English-only on the surfaces machines read**. Four layers, each with its own rule.
When in doubt, ask: "who reads this - a machine, a developer, or an end user?"

| Layer | Surface | Language rule |
|-------|---------|---------------|
| **L0 machine / audit** | code identifiers, comments, docstrings, logs, error codes, **audit entries, event payloads, generated PR titles/bodies, policy (Rego), config keys** | **English only, permanently. Never localized.** |
| **L1 developer docs** | root `README.md`, `docs/**/*.md` | English canonical + `foo-ko.md` sibling (see [-ko.md](#user-facing-doc-translations-ko)). |
| **L2 product surfaces** | operator console, CLI, ChatOps cards, notifications, the docs site | **Source strings English** + per-surface locale catalogs, localized at render time (see [Product i18n](#product-i18n-l2)). |
| **L3 conversational** | Bragi narrator answers | Rendered in the operator's locale; the intent, tool calls, verdict, and audit underneath stay L0 (English). |

**Why L0 stays English forever:** audit, logs, and events MUST stay
machine-parseable, grep-able, and deterministically replayable across every fork and
cloud. Localizing them would break replay, correlation, and compliance review.
Freezing L0 to English also **shrinks the translation surface to only what a human
actually reads** (L2/L3) - which is what makes multilingual support safe and cheap.

The `## Rule` section below is the L0 + L1-source rule (English-only for everything
committed and emitted, minus the carve-outs). L2/L3 localization is layered on top via
message catalogs, never by translating an L0 string in place.

## Rule

FDAI is **bilingual (English + Korean)**, layered by who reads the surface (see
the [L0-L3 table](#language-layers-l0---l3) above). The rule is **per layer**,
not a blanket "English only".

- **L0 machine / audit substrate is English-only, permanently.** Any other
  natural language here is a defect. This is the machine-parseable, replayable,
  CSP-neutral core, and it covers:
  - source code, identifiers, comments, and docstrings
  - logs, error strings/codes, **audit entries, event payloads, serialized
    verdicts**, and generated PR titles/bodies
  - policy (Rego), config keys, schemas, and the fixtures/sample data that feed
    them
  - `.github/**` (copilot-instructions, instructions/*, workflows, issue/PR
    templates) - **English-only, no translations, no exceptions**
  - commit messages, branch names, PR titles and descriptions
  - **GitHub issues** - titles, descriptions, labels, and comments are
    **English-only, always** (project-tracking artifacts, never translated)
- **L1 developer docs** ship `foo.md` (English) + `foo-ko.md` (Korean) pairs
  (see [-ko.md](#user-facing-doc-translations-ko)).
- **L2 product surfaces and the L3 narrator MAY contain Korean.** The operator
  console, CLI, ChatOps cards, notifications, the docs site, and the Bragi
  narrator answer text are the surfaces humans read; Korean is a first-class
  product language there, authored **inline or via message catalogs**. English
  fallback stays mandatory for catalog strings (see
  [Product i18n](#product-i18n-l2)).
- **L0 records stay English even inside an L2/L3 surface.** When an audit entry,
  event payload, log key, identifier, or serialized verdict passes through a
  console / CLI / narrator file, the surface localizes the **labels around it**,
  never the machine record itself.
- **Identifiers, filenames, and branch names must be ASCII** (`a-z A-Z 0-9 _ - .`)
  on every layer. No accented letters, CJK, or emoji in code symbols or paths.
- **Korean** also appears in interactive maintainer chat and in the `-ko.md`
  docs / `.ko.json` catalogs defined below.

## Allowed Exceptions

Non-English or non-ASCII text is permitted **only** in these cases:

- **Proper nouns**: third-party product, library, vendor, or standards names spelled as
  their owners spell them.
- **Quoted data**: a non-English string that is the literal subject under test (parser,
  encoding, i18n fixtures). Encode it explicitly (`\uXXXX` or UTF-8 bytes) and add a
  one-line English comment or an allowlist marker explaining why it is present.
- **Vendored / generated code**: files under a clearly marked third-party or generated
  path are exempt; do not hand-edit them to translate comments.
- **Localization**: L2/L3 product surfaces (console, CLI, ChatOps, notifications, site,
  narrator) are bilingual - Korean MAY be authored **inline** on those surfaces or via
  locale resource files (e.g. `messages.<locale>.json`). Catalogs are recommended for
  reusable strings (English fallback + parity). This exception does not extend to the
  L0 machine/audit substrate. See [Product i18n](#product-i18n-l2).
- **Emoji**: not allowed in code, identifiers, commit messages, or PR titles; allowed in
  docs only when they add meaning, never as a substitute for words.

## User-Facing Doc Translations (`-ko.md`)

User-facing Markdown documentation ships bilingually. This is the **only** place in the
repository where a natural language other than English is permitted in committed text.

**Scope (translatable)**

- Root `README.md`
- Everything under `docs/**/*.md`

**Out of scope (English-only, no translation)**

- Everything under `.github/**` - `copilot-instructions.md`, `instructions/*.md`,
  workflows, issue and PR templates. These are project guidelines, not user docs.
- Everything under `docs/internals/**` - internal engineering notes (gap
  analyses, summaries of external material, working design memos). These are
  team-facing engineering artifacts, not published user docs, so they stay
  English-only like `.github/**`. A `-ko.md` sibling is permitted but never
  required there.
- Anything under `mocks/**`, `examples/**`, and any future third-party or vendored path.

**File-pair convention**

- The English file is the **canonical source of truth**: `foo.md`.
- The Korean translation is a sibling with the `-ko.md` suffix: `foo-ko.md`.
- A `-ko.md` file **must not exist without** a matching English `foo.md`. Korean-only
  documents are prohibited.
- A `-ko.md` file **must** carry YAML front-matter identifying its source and its
  translation-source SHA:

  ```yaml
  ---
  translation_of: foo.md
  translation_source_sha: <git blob sha of foo.md at translation time>
  translation_revised: 2026-07-05
  ---
  ```

  Compute the SHA with `git hash-object foo.md`.

**Paired-update rule (MUST)**

- **Any change to `foo.md` MUST update `foo-ko.md` in the same PR**, and vice versa.
  A PR that touches only one side is not mergeable. The CI translation check enforces
  this by comparing `git hash-object foo.md` against the `translation_source_sha`
  recorded in `foo-ko.md`.
- If the translator has not yet reflected an English update, the SHA in `-ko.md` will
  no longer match `foo.md` → CI fails → the PR must update both sides before merge.
- Adding a **new** `foo.md` in scope MUST create `foo-ko.md` in the same PR.
- Removing `foo.md` MUST remove `foo-ko.md` in the same PR.

**Content rules**

- The two files carry the **same information, structure, and headings**. The Korean
  file is a translation, not a rewrite or an editorial re-org.
- Preserve unchanged: code blocks, tables of technical values, links, filenames, and
  domain vocabulary in backticks (`T0`, `T1`, `T2`, `HIL`, `trust-router`,
  `deterministic-engine`, `rule-catalog`, `risk-gate`, `remediation-pr`, `shadow-mode`).
  Only translate natural-language prose.
- Cross-references between docs should point language-consistently: links in
  `foo-ko.md` to sibling docs point to their `-ko.md` counterparts; links to
  `.github/**` (English-only) stay pointing to the English file.
- Formats stay identical: ISO 8601 dates, ASCII punctuation, no smart quotes.

## Product i18n (L2)

L2 surfaces (operator console, CLI, ChatOps cards, notifications, the docs site) are
**bilingual**. This operationalizes the [Localization](#allowed-exceptions) exception:

- **Bilingual source is allowed.** A user-facing string on an L2 surface MAY be
  written in Korean (or English) **inline**, or authored as an English key in a
  message catalog. Catalogs are **recommended** for reusable strings - they give a
  mandatory English fallback and keep `en` / `ko` in parity - but inline Korean is
  permitted for surface-specific presentation text. `scripts/check-english-only.sh`
  does **not** scan the L2/L3 surface paths (`console/src/**`, `cli/src/**`, the
  narrator `chat*.py` routes), so Korean there does not fail the gate.
- **Approval terminology:** human-facing L2 labels and default L3 prose SHOULD use
  `Approvals`, `Approval required`, or `Pending approval` instead of the bare `HIL`
  acronym. `HIL` MAY appear when explaining the raw `hil` verdict, in a technical
  glossary, or when an operator asks about the term explicitly. L0 identifiers and
  values such as `hil`, `/hil-queue`, schemas, types, events, and audit records keep
  the canonical machine vocabulary; presentation code never renames serialized values.
- **One catalog pair per surface.** `messages.en.json` (source) + `messages.ko.json`
  (translation), or the surface's native i18n format (e.g. Astro Starlight locales for
  the docs site). Catalogs live in a dedicated resource path.
- **English fallback is mandatory** for catalog strings. A missing or empty translation
  key renders the English source - never a blank, the key name, or an error. A partial
  `ko` catalog ships fine.
- **Locale resolution order:** explicit user preference (`UserPreference.locale`) ->
  request `Accept-Language` -> default `en`.
- **Catalog parity (CI):** every key in `messages.ko.json` MUST exist in
  `messages.en.json` (no orphan translations); the `en` catalog is the source of truth,
  mirroring the `-ko.md` SHA gate. A `ko` catalog MAY lag (fallback covers it) but MUST
  NOT invent keys the `en` catalog does not have.
- **Korean outside an L2/L3 surface path** (a resource file that carries Hangul but
  lives on the L0 substrate) still needs an explicit `scripts/check-english-only.sh`
  allowlist entry with a one-line reason, exactly like the site `ko/` locale and the
  `-ko.md` carve-out.
- **Do NOT localize L0 in place.** When an L0 record (audit entry, log line, event
  payload, PR body, Rego, error code, identifier) surfaces inside a localized L2 view,
  the view localizes the **labels around it**, never the machine record itself.

### L3 - conversational (Bragi narrator)

Bragi renders its final natural-language answer in the operator's locale
(`UserPreference.locale`), but everything beneath the answer - the intent it translates
into, the tool calls, the verdict, and the audit entry - stays L0 English. The narrator
is a **presentation translator**, matching its "translator only" role in
[architecture.instructions.md](architecture.instructions.md); a localized phrasing MUST
NOT change what the typed pipeline decides.

## Formats (machine-parseable)

- Dates and timestamps use **ISO 8601 / RFC 3339** (`2026-07-03`, `2026-07-03T09:15:00Z`).
- Use `.` as the decimal separator and no digit-grouping in machine-read values.
- **ASCII punctuation only (MUST, CI-enforced).** Use `-`, `"`, `'`, and `...`. The
  following Unicode characters are BLOCKED in every tracked text file by
  `scripts/check-punctuation.sh`:
  - U+2014 EM DASH  and  U+2013 EN DASH  -> use ASCII `-`
  - U+2026 HORIZONTAL ELLIPSIS  -> use `...`
  - U+201C / U+201D smart double quotes  -> use ASCII `"`
  - U+2018 / U+2019 smart single quotes  -> use ASCII `'`
  - U+00A0 NO-BREAK SPACE (invisible; breaks grep/diff)  -> use a normal space
  Auto-fix: `python3 scripts/normalize-punctuation.py` (fence-aware for `.md`;
  add `--whole-file` for source files where the whole content is code).

## Why

- The control plane is designed to be **CSP-neutral** (cloud-provider-neutral) and
  portable across teams and clouds.
- Mixed-language artifacts break searchability, reviewability, and tooling (linters,
  policy engines, LLM grounding).
- A single language keeps the rule catalog and audit logs machine-parseable.

## Naming

- Use clear, descriptive English identifiers. "Avoid transliterated abbreviations" means:
  do not romanize non-English words into code (write `approval-queue`, not a phonetic
  spelling of a foreign term).
- Domain vocabulary is defined canonically in
  [architecture.instructions.md](architecture.instructions.md); reuse those terms:
  `trust-router`, `deterministic-engine`, `rule-catalog`, `risk-gate`, `remediation-pr`,
  `shadow-mode`, `HIL` (human-in-the-loop).
- Casing: tiers and acronyms are uppercase (`T0`, `T1`, `T2`, `HIL`); code symbols follow
  their language convention (e.g., kebab-case configs, snake_case Python, camelCase JS).

## Examples

- Good: `// retry the remediation-pr when the risk-gate abstains`
- Bad: a comment or commit body written in Korean, or a non-ASCII identifier.
- Good fixture: `{"input": "\uD55C\uAE00", "note": "non-ASCII parse case"}` (encoded + explained).
- Bad fixture: a raw non-English sentence with no encoding or explanation.

## Automation & Review Check

- **Automated gate**: `scripts/check-english-only.sh` runs in CI and enforces English
  on the **L0 machine/audit substrate** (it does not police L2/L3 surfaces). It matches
  Hangul (`\uAC00-\uD7A3`, `\u1100-\u11FF`) or CJK (`\u4E00-\u9FFF`) ranges in tracked
  text files with `grep -P` (the pattern must use `-P` alone; combining it with `-E`
  makes `grep` reject the conflicting matchers and silently pass everything). The scan
  **excludes** the `-ko.md` translation files and `*.ko.json` catalogs, the **L2/L3
  human-facing surface paths** (`console/src/**`, `cli/src/**`, the narrator
  `src/fdai/delivery/read_api/routes/chat*.py` + their tests - Korean is permitted
  there), plus a small, centrally documented allowlist of other legitimately
  non-English paths (the Korean site locale under
  `site/src/content/docs/ko/`, and a named set of translation-tooling and
  Korean-locale UI files). The allowlist and its per-entry justification live at the
  top of the script; adding to it requires a stated reason.
- **Punctuation gate**: `scripts/check-punctuation.sh` runs in CI and enforces the
  ASCII-only punctuation rule above; it blocks em-dash, en-dash, ellipsis,
  smart-quotes, and no-break-space anywhere in a tracked text file (including inside
  `-ko.md`, code blocks, and comments).
- **Translation-pair gate**: `scripts/check-translations.sh` runs in CI and enforces
  the [paired-update rule](#user-facing-doc-translations-ko): every in-scope `foo.md`
  has a `foo-ko.md`, every `foo-ko.md` has front-matter with `translation_of` and
  `translation_source_sha`, and each `translation_source_sha` matches the current
  `git hash-object` of the source file.
- **Catalog-parity gate**: `scripts/check-catalog-parity.sh` runs in CI and enforces
  the [Product i18n](#product-i18n-l2) rule for L2 message catalogs: for every
  `<name>.en.json` / `<name>.ko.json` sibling pair, the `ko` keys MUST be a subset of
  the `en` keys (no orphan translations; `en` is the source of truth, `ko` MAY lag
  under English fallback). No catalogs present is a pass, so it is safe before any
  catalog exists.
- **PR review**: if Korean appears in a diff on the **L0 machine/audit substrate**
  (code identifiers, comments, logs, audit entries, event payloads, PR bodies, Rego,
  config keys, `.github/**`) outside the [Allowed Exceptions](#allowed-exceptions) or a
  `-ko.md` file, treat it as a defect and correct it before merge, per
  [coding-conventions.instructions.md](coding-conventions.instructions.md). Korean on an
  L2/L3 surface (console, CLI, narrator) is expected, not a defect.

> One line: **L0** (code, identifiers, audit, logs, events, PR bodies, policy, config
> keys, `.github/**`) is English forever; **L1** docs ship `.md` + `-ko.md` pairs;
> **L2** product surfaces (console, CLI, ChatOps, notifications, site) are bilingual -
> Korean inline or via English-source catalogs with mandatory English fallback;
> **L3** the Bragi narrator renders in the operator's locale over an English pipeline.
