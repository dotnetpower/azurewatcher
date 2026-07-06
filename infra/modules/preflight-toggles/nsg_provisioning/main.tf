# nsg_provisioning capability-mode toggle.
#
# Data-only module. Emits a normalized configuration map the consumer
# subnet / NIC module reads to decide whether to CREATE an NSG or
# reference a bring-your-own one. See `../README.md`.

locals {
  should_create_nsg = var.mode == "create"

  # When byo, forward the id; when create, empty string so a downstream
  # ternary can pick between the created NSG and the referenced one
  # without checking the mode string.
  byo_nsg_id = var.mode == "byo" ? var.existing_nsg_id : ""
}
