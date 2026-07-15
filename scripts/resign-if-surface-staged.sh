#!/usr/bin/env bash
#
# resign-if-surface-staged.sh - auto re-sign the framework-surface integrity
# manifest at commit time, but ONLY when this repo is the upstream signer.
#
# Called from the pre-commit hook (.githooks/pre-commit and the pre-commit
# framework). It is a deliberate no-op unless ALL of these hold:
#
#   1. the upstream Ed25519 PRIVATE signing key is available
#      (secrets/integrity-signing-key.pem or $FDAI_INTEGRITY_KEY), AND
#   2. a STAGED change touches the framework surface
#      (scripts/lib/framework-surface.txt).
#
# When both hold it runs scripts/sign-integrity.sh (regenerate manifest + sign)
# and stages the refreshed manifest + signature so they land in the SAME commit
# as the surface change. This removes the manual "re-sign before release" chore
# for the maintainer.
#
# Fork safety: a fork never has the private key, so this always no-ops there -
# a fork still cannot mint a manifest that verifies against the committed public
# key, and its surface edits are still caught by check-integ.sh in fork mode on
# push. Automating the signature does NOT weaken the fork-facing tamper-evidence.
#
# Caveat: sign-integrity.sh hashes the WORKING TREE. With partial staging
# (`git add -p` leaving a surface file partially staged), the manifest reflects
# the working tree, not the index. For whole-file commits (the normal case)
# they are identical. Set FDAI_SKIP_RESIGN=1 to bypass.
#
# Exit codes: 0 = no-op or re-signed OK; 1 = signing failed (blocks the commit).

set -uo pipefail

[ "${FDAI_SKIP_RESIGN:-0}" = "1" ] && exit 0

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

# 1. Upstream signer only: no private key -> not us -> nothing to do.
privkey="${FDAI_INTEGRITY_KEY:-secrets/integrity-signing-key.pem}"
[ -f "$privkey" ] || exit 0

# 2. Any staged framework-surface file?
mapfile -t staged < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
[ "${#staged[@]}" -eq 0 ] && exit 0

surface_list="scripts/lib/framework-surface.txt"
[ -f "$surface_list" ] || exit 0

prefixes=()
exacts=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="$(printf '%s' "$line" | tr -d '[:space:]')"
  [ -n "$line" ] || continue
  case "$line" in
    */) prefixes+=("$line") ;;
    *) exacts+=("$line") ;;
  esac
done < "$surface_list"

surface_touched=0
for f in "${staged[@]}"; do
  for e in "${exacts[@]}"; do
    [ "$f" = "$e" ] && surface_touched=1 && break
  done
  [ "$surface_touched" = 1 ] && break
  for p in "${prefixes[@]}"; do
    case "$f" in "$p"*) surface_touched=1 ; break ;; esac
  done
  [ "$surface_touched" = 1 ] && break
done
[ "$surface_touched" = 1 ] || exit 0

# 3. Re-sign and stage the refreshed artifacts into this commit.
echo "resign-integrity: framework surface staged -> re-signing manifest..."
out="$(mktemp)"
if ! bash scripts/sign-integrity.sh >"$out" 2>&1; then
  echo "resign-integrity: BLOCKED - sign-integrity failed:" >&2
  sed 's/^/  /' "$out" >&2
  rm -f "$out"
  exit 1
fi
rm -f "$out"
git add security/integrity/manifest.json security/integrity/manifest.json.sig
echo "resign-integrity: manifest re-signed + staged."
exit 0
