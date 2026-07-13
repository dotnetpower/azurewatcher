#!/usr/bin/env bash
#
# check-chaos-scenarios.sh - CI gate for the chaos-scenarios catalog.
#
# Runs `load_all()` from `src/fdai/core/chaos/scenario_catalog.py`, which
# fails on:
#   - schema violations (schema/chaos-scenario.schema.json),
#   - unknown expected_signal (not in core/detection/signals.py),
#   - `injector: needs-injector` scenarios landing in promoted/,
#   - duplicate scenario ids across the tree,
#   - malformed override files.
#
# Then rebuilds the compiled symptom index and checks that the on-disk
# artifact matches - a catalog PR that forgets to run
# `scripts/build-symptom-index.py` fails here instead of shipping a
# stale runtime artifact.
#
# Exit code: 0 on all-pass, non-zero on any failure. Safe when the
# catalog is empty (yields zero entries, exits 0).

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

if ! command -v python3 >/dev/null 2>&1; then
    echo "check-chaos-scenarios: python3 not found on PATH" >&2
    exit 2
fi

# ---- 1. load_all() must succeed ------------------------------------------

if ! output="$(python3 -c '
import sys
from fdai.core.chaos.scenario_catalog import ScenarioCatalogError, load_all
try:
    entries = load_all()
except ScenarioCatalogError as exc:
    print(f"chaos-catalog validation failed: {exc}", file=sys.stderr)
    sys.exit(1)
print(f"loaded {len(entries)} entries")
' 2>&1)"; then
    printf 'check-chaos-scenarios: %s\n' "$output" >&2
    exit 1
fi
printf 'check-chaos-scenarios: %s\n' "$output"

# ---- 2. compiled symptom-index artifact matches load_all() ---------------

index_path="rule-catalog/chaos-scenarios/chaos-scenarios.index.json"

if [[ ! -f "$index_path" ]]; then
    echo "check-chaos-scenarios: missing $index_path (run scripts/build-symptom-index.py)" >&2
    exit 1
fi

# Regenerate to a temp file and diff. This catches "author added / removed
# a scenario but forgot to rebuild the index".
tmp_index="$(mktemp)"
trap 'rm -f "$tmp_index"' EXIT

if ! python3 scripts/build-symptom-index.py --out "$tmp_index" >/dev/null 2>&1; then
    echo "check-chaos-scenarios: scripts/build-symptom-index.py failed" >&2
    exit 1
fi

if ! diff -q "$index_path" "$tmp_index" >/dev/null; then
    echo "check-chaos-scenarios: compiled symptom index is stale" >&2
    echo "  fix: python3 scripts/build-symptom-index.py" >&2
    diff -u "$index_path" "$tmp_index" | head -40 >&2 || true
    exit 1
fi

echo "check-chaos-scenarios: OK (catalog validates, symptom index matches)"
