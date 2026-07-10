# Reference consumer for the `disk_provisioning` capability-mode toggle.
#
# This is the copy-paste pattern a fork wires into its own compute module so
# that the Deployment Preflight active-reassembly loop can flip
# `disk_provisioning` from `inline` to `attach_existing` and have the plan
# comply WITHOUT emitting the policy-denied inline-disk-create operation.
#
# The upstream toggle module is data-only (no resources); this example shows
# the ONE branch the consumer owns: create-vs-attach. It is illustrative and
# validate-only - the upstream deploy does not instantiate it.

module "disk" {
  source            = "../disk_provisioning"
  mode              = var.mode
  existing_disk_ids = var.existing_disk_ids
  disk_size_gb      = var.disk_size_gb
}

# Inline branch: create a managed disk only when the toggle resolved to
# `inline`. `should_create_disk` is guaranteed non-empty by the toggle's own
# variable validation, so this count expression is safe.
resource "azurerm_managed_disk" "inline" {
  count = module.disk.should_create_disk ? 1 : 0

  name                 = "${var.name_prefix}-data"
  resource_group_name  = var.resource_group_name
  location             = var.location
  storage_account_type = "Premium_LRS"
  create_option        = "Empty"
  disk_size_gb         = module.disk.inline_disk_size_gb
}

locals {
  # The consumer never branches on the toggle NAME - it reads the output and
  # picks the effective id set: the freshly created disk (inline) or the
  # pre-provisioned ids (attach_existing). A downstream
  # `azurerm_virtual_machine_data_disk_attachment` iterates this set.
  effective_disk_ids = module.disk.should_create_disk ? azurerm_managed_disk.inline[*].id : module.disk.disk_source_ids
}

output "effective_mode" {
  description = "The mode the toggle resolved to."
  value       = module.disk.effective_mode
}

output "effective_disk_ids" {
  description = "Disk ids the VM attaches, regardless of create-vs-attach mode."
  value       = local.effective_disk_ids
}
