---
description: Language and naming policy for all AzureWatcher artifacts.
applyTo: "**"
---

# Language Policy

## Scope

This policy governs everything **committed to this repository** and everything the
control plane **emits at runtime** (logs, error strings, audit records, generated PRs).
It does not govern live maintainer chat. Related rules live in
[coding-conventions.instructions.md](coding-conventions.instructions.md) (commits/PRs)
and [generic-scope.instructions.md](generic-scope.instructions.md) (no customer data).

## Rule

- **English is the only allowed natural language** for everything committed to this
  repository. Any other natural language (Korean, etc.) is a defect unless it falls
  under [Allowed Exceptions](#allowed-exceptions). This applies to:
  - source code, identifiers, comments, and docstrings
  - documentation, README files, and text embedded in diagrams, screenshots, or images
  - commit messages, branch names, PR titles and descriptions
  - tests, fixtures, sample data, and config files
  - log messages, error strings, audit entries, and source strings for user-facing text
- **Identifiers, filenames, and branch names must be ASCII** (`a-z A-Z 0-9 _ - .`).
  No accented letters, CJK, or emoji in code symbols or paths.
- **Korean is allowed only in interactive maintainer chat.** It must never appear in
  any file, commit, or artifact that lands in the repository.

## Allowed Exceptions

Non-English or non-ASCII text is permitted **only** in these cases:

- **Proper nouns**: third-party product, library, vendor, or standards names spelled as
  their owners spell them.
- **Quoted data**: a non-English string that is the literal subject under test (parser,
  encoding, i18n fixtures). Encode it explicitly (`\uXXXX` or UTF-8 bytes) and add a
  one-line English comment or an allowlist marker explaining why it is present.
- **Vendored / generated code**: files under a clearly marked third-party or generated
  path are exempt; do not hand-edit them to translate comments.
- **Localization**: product UI may ship translations, but the **source strings are
  English** and translations live in dedicated resource files (e.g., `messages.<locale>.json`),
  never inline in code.
- **Emoji**: not allowed in code, identifiers, commit messages, or PR titles; allowed in
  docs only when they add meaning, never as a substitute for words.

## Formats (machine-parseable)

- Dates and timestamps use **ISO 8601 / RFC 3339** (`2026-07-03`, `2026-07-03T09:15:00Z`).
- Use `.` as the decimal separator and no digit-grouping in machine-read values.
- Prefer plain ASCII punctuation (`-`, `"`, `'`) over smart quotes and em-dashes in code
  and config; unicode typography in prose is discouraged where it affects diff or grep.

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

- **Automated gate**: a CI / pre-commit check should flag non-ASCII natural-language runs
  outside the allowlist. A practical detector is any match of Hangul (`\uAC00-\uD7A3`,
  `\u1100-\u11FF`) or CJK (`\u4E00-\u9FFF`) ranges in tracked text files.
- **PR review**: if any non-English text appears in a diff outside live chat and the
  [Allowed Exceptions](#allowed-exceptions), treat it as a defect and correct it before
  merge, per [coding-conventions.instructions.md](coding-conventions.instructions.md).

> One line: English-only, ASCII identifiers, ISO-8601 formats — Korean lives in chat, not in the repo.
