# disk_provisioning capability-mode toggle.
#
# Data-only module - no `resource` blocks. Emits a normalized
# configuration map the consumer VM / disk module reads to decide
# whether to CREATE a fresh managed disk or ATTACH a pre-provisioned
# one. See `../README.md` for the pattern rationale.
#
# The Deployment Preflight analyzer emits a `terraform_toggle` finding
# that names this module + the `mode` variable so a reviewer can apply
# the fix by changing exactly one value.

locals {
  # Guaranteed non-empty by the variable validation, so a downstream
  # count / for_each on `should_create_disk` is safe.
  should_create_disk = var.mode == "inline"

  # When attaching an existing disk, forward the ids verbatim. When
  # inline, the list is intentionally empty so a downstream
  # `for_each = toset(module.disk.disk_source_ids)` becomes a no-op.
  disk_source_ids = var.mode == "attach_existing" ? var.existing_disk_ids : []
}
