#!/usr/bin/env bash
#
# check-english-only.sh - enforce English on the L0 machine/audit substrate,
# while permitting Korean on the L2/L3 human-facing surfaces.
#
# FDAI is bilingual (English + Korean). Language is layered (see
# .github/instructions/language.instructions.md):
#   * L0 machine / audit  - code identifiers, comments, docstrings, logs,
#     error codes, audit entries, event payloads, generated PR bodies, policy
#     (Rego), config keys. ENGLISH ONLY, permanently - so audit/logs/events stay
#     machine-parseable, grep-able, and deterministically replayable across
#     every fork and cloud. This gate enforces that.
#   * L1 developer docs   - `foo.md` (English) + `foo-ko.md` (Korean) pairs.
#   * L2 product surfaces  - operator console, CLI, ChatOps, notifications,
#     the docs site. Bilingual: Korean is permitted (inline or via message
#     catalogs). English fallback still required for catalog strings.
#   * L3 conversational    - the Bragi narrator answer text renders in the
#     operator's locale. Korean is permitted on the narrator surface.
#
# So this gate scans the L0 substrate for Hangul (U+AC00-U+D7A3 / U+1100-U+11FF)
# or CJK Unified Ideographs (U+4E00-U+9FFF) and fails on a match. It does NOT
# scan the L2/L3 human-facing surfaces (excluded below), where Korean is a
# first-class product language.
#
# IMPORTANT: even inside an L2/L3 surface, an L0 record that passes THROUGH it
# (an audit entry, an event payload, a log key, an identifier, a serialized
# verdict) stays English - localize the labels around it, never the machine
# record. The gate cannot enforce that at sub-file granularity; code review does.
#
# Scope (included by default):
#   Every git-tracked file EXCEPT:
#     * *-ko.md (L1 translation carve-out)
#     * *.ko.json (L2 message-catalog Korean translations; parity-gated by
#                  scripts/check-catalog-parity.sh - ko keys subset of en)
#     * L2/L3 human-facing surfaces (bilingual - Korean permitted):
#         - console/src/**            operator console (L2) + command deck (L3)
#         - cli/src/**                CLI (L2)
#         - src/fdai/delivery/read_api/routes/chat*.py
#                                     server narrator / chat surface (L3)
#         - tests/delivery/read_api/test_chat*.py
#                                     tests asserting localized narrator output
#     * mocks/**, examples/** (design mock-ups, not shipped code)
#     * binary assets (png/jpg/jpeg/gif/webp/pdf/ico/woff/woff2/ttf/otf)
#     * cryptographic signatures (*.sig; binary integrity artifacts)
#     * uv.lock (hash-only content; guaranteed ASCII, exclude to speed up)
#
# Justified allowlist (legitimately non-English, each with a reason):
#     * site/src/content/docs/ko/**            Korean locale presentation;
#                                              every file is a mount of an
#                                              already-carved-out -ko.md source.
#     * .github/skills/documentation-writing/SKILL.md
#                                              teaches Korean translation tone;
#                                              its Korean examples are quoted data.
#     * scripts/apply-tone-corrections.py      Korean tone-correction data tables.
#     * tools/baseline_run.py                  emits a localized Korean report.
#     * site/src/components/StaleTranslationBanner.astro
#                                              banner rendered only on Korean pages.
#
# Exit codes: 0 on success, 1 on any violation.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# Enumerate every file that would end up in the tree (tracked + untracked
# but not gitignored), then filter out excluded paths.
mapfile -t files < <(
  git ls-files -co --exclude-standard \
    ':(exclude)*-ko.md' \
    ':(exclude)*.ko.json' \
    ':(exclude)console/src/**' \
    ':(exclude)cli/src/**' \
    ':(exclude)src/fdai/delivery/read_api/routes/chat*.py' \
    ':(exclude)tests/delivery/read_api/test_chat*.py' \
    ':(exclude)mocks/**' \
    ':(exclude)examples/**' \
    ':(exclude)site/src/content/docs/ko/**' \
    ':(exclude).github/skills/documentation-writing/SKILL.md' \
    ':(exclude)scripts/apply-tone-corrections.py' \
    ':(exclude)tools/baseline_run.py' \
    ':(exclude)site/src/components/StaleTranslationBanner.astro' \
    ':(exclude)*.png' \
    ':(exclude)*.jpg' \
    ':(exclude)*.jpeg' \
    ':(exclude)*.gif' \
    ':(exclude)*.webp' \
    ':(exclude)*.pdf' \
    ':(exclude)*.ico' \
    ':(exclude)*.woff' \
    ':(exclude)*.woff2' \
    ':(exclude)*.ttf' \
    ':(exclude)*.otf' \
    ':(exclude)*.sig' \
    ':(exclude)uv.lock' \
    | sort -u
)

errors=0
for f in "${files[@]}"; do
  [[ -f "$f" ]] || continue

  # Hangul (Syllables + Jamo) OR CJK Unified Ideographs.
  # Using a Perl-compatible regex via grep -P so we can match \x{...}.
  # NOTE: -P must not be combined with -E (grep rejects conflicting
  # matchers, which silently made this gate a no-op before the fix).
  if grep -Pn '[\x{AC00}-\x{D7A3}\x{1100}-\x{11FF}\x{4E00}-\x{9FFF}]' "$f" >/dev/null 2>&1; then
    echo "check-english-only: $f contains non-ASCII natural-language characters" >&2
    grep -Pn '[\x{AC00}-\x{D7A3}\x{1100}-\x{11FF}\x{4E00}-\x{9FFF}]' "$f" | head -5 | sed 's/^/    /' >&2
    errors=$((errors + 1))
  fi
done

if (( errors > 0 )); then
  echo "check-english-only: FAILED with ${errors} file(s) on the L0 machine/audit substrate." >&2
  echo "L0 (code identifiers, comments, logs, audit entries, event payloads, PR" >&2
  echo "bodies, Rego, config keys) is English-only. Fix: write the L0 text in" >&2
  echo "English; put Korean product/UI strings on an L2/L3 surface (console/CLI/" >&2
  echo "narrator) or in a -ko.md doc / .ko.json catalog." >&2
  exit 1
fi

printf 'check-english-only: OK (%d tracked file(s) scanned)\n' "${#files[@]}"
