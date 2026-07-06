# dependency_ordering capability-mode toggle.
#
# Data-only module. Emits a "strict mode" flag and an ordered list of
# prerequisite stages so a consumer stack can serialise IaC apply
# across (disk, NSG, private endpoint, ...) when the target
# subscription's control plane rejects concurrent creates on the same
# scope. Resolves the `deploy.dependency_ordering_denied` Preflight
# blocker.

locals {
  strict_mode = var.mode == "strict"

  # Canonical prerequisite stages the consumer serialises when strict.
  # A fork MAY override via `custom_stages`; keeping a default here so
  # a first-time user gets a working ordering.
  effective_stages = length(var.custom_stages) > 0 ? var.custom_stages : [
    "disk",
    "nsg",
    "private_endpoint",
    "compute",
  ]

  # When best-effort, the ordering collapses to a single stage - the
  # consumer applies everything in parallel and lets the substrate
  # sort out its own dependency graph.
  applied_stages = local.strict_mode ? local.effective_stages : ["all"]
}
