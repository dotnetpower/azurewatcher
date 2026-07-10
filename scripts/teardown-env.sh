#!/usr/bin/env bash
# Cost/lifecycle helper for the ops/hub runner + an app environment.
#
#   ./scripts/teardown-env.sh runner-stop            # deallocate the runner VM
#   ./scripts/teardown-env.sh runner-start           # start it before a CI run
#   ./scripts/teardown-env.sh env-destroy <env>      # destroy an app environment
#
# env-destroy runs from the runner (remote state) - it never deletes the ops
# hub or the state account. It refuses when a resource lock is present.
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
    ENV="${2:?usage: teardown-env.sh env-destroy <dev|staging|prod>}"
    echo "This destroys the '$ENV' app environment via the runner (remote state)."
    echo "The ops hub + state account are NOT touched."
    read -r -p "Type the env name to confirm: " confirm
    [ "$confirm" = "$ENV" ] || { echo "aborted."; exit 1; }
    az vm run-command invoke -g "$OPS_RG" -n "$VM" --command-id RunShellScript --scripts "
      set -e; cd /root/deploy/infra 2>/dev/null || { echo 'runner has no /root/deploy/infra'; exit 1; }
      export HOME=/root ARM_SUBSCRIPTION_ID=\$(az account show --query id -o tsv) ARM_USE_AZUREAD=true
      terraform destroy -input=false -auto-approve
    " --query "value[0].message" -o tsv | tail -20
    ;;
  *)
    echo "usage: teardown-env.sh {runner-stop|runner-start|env-destroy <env>}" >&2
    exit 1
    ;;
esac
