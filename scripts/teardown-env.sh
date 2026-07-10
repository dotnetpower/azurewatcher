#!/usr/bin/env bash
# Cost/lifecycle helper for the ops/hub runner + an app environment.
#
#   ./scripts/teardown-env.sh runner-stop            # deallocate the runner VM
#   ./scripts/teardown-env.sh runner-start           # start it before a CI run
#   ./scripts/teardown-env.sh env-destroy <env> <owner/repo>   # destroy an app env
#
# env-destroy dispatches the destroy-env workflow (self-hosted runner, real
# remote state) - it never deletes the ops hub or the state account, and the
# workflow re-checks the confirm guard.
set -euo pipefail

OPS_RG="${OPS_RG:-rg-fdai-ops-krc}"
VM="${VM:-vm-runner-fdai-dev-krc}"

case "${1:-}" in
  runner-stop)
    az vm deallocate -g "$OPS_RG" -n "$VM"
    echo "runner deallocated (compute billing stops; disk still billed)."
    ;;
  runner-start)
    az vm start -g "$OPS_RG" -n "$VM"
    echo "runner started; give the actions-runner service ~30s to reconnect."
    ;;
  env-destroy)
    ENV="${2:?usage: teardown-env.sh env-destroy <dev|staging|prod> [owner/repo]}"
    REPO="${3:-${GH_REPO:-}}"
    [ -n "$REPO" ] || { echo "set owner/repo (arg 3) or GH_REPO env." >&2; exit 1; }
    echo "This destroys the '$ENV' app environment via the destroy-env workflow"
    echo "(real remote state; the ops hub + state account are NOT touched)."
    read -r -p "Type the env name to confirm: " confirm
    [ "$confirm" = "$ENV" ] || { echo "aborted."; exit 1; }
    # The destroy runs on the self-hosted runner with the vetted backend + vars,
    # never a stale local dir. The workflow re-checks confirm == environment.
    gh workflow run destroy-env.yml -R "$REPO" \
      -f environment="$ENV" -f confirm="$ENV"
    echo "destroy-env workflow dispatched; watch: gh run watch -R $REPO"
    ;;
  *)
    echo "usage: teardown-env.sh {runner-stop|runner-start|env-destroy <env>}" >&2
    exit 1
    ;;
esac
