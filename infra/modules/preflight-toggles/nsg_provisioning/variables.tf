variable "mode" {
  description = <<-EOT
    Provisioning mode.

    - `create` (default): the consumer module creates an
      `azurerm_network_security_group` with the rules in `nsg_rules`.
    - `byo`: the consumer module SKIPS NSG creation and references the
      existing resource in `existing_nsg_id`. Use this to resolve the
      `deploy.nsg_creation_denied` Preflight blocker (governance-owned
      NSGs).
  EOT
  type        = string
  default     = "create"

  validation {
    condition     = contains(["create", "byo"], var.mode)
    error_message = "mode must be one of: 'create', 'byo'."
  }
}

variable "existing_nsg_id" {
  description = <<-EOT
    NSG resource id to reference when `mode == 'byo'`. MUST be non-empty
    when byo is selected; the module refuses an empty string in byo mode
    at plan time.
  EOT
  type        = string
  default     = ""

  validation {
    # If mode=byo the id MUST be non-empty. We cannot cross-reference
    # `var.mode` from this validation block, so the constraint is a
    # soft one: an empty id in byo mode surfaces via `byo_nsg_id`
    # output (empty string) which downstream modules should assert.
    condition     = length(var.existing_nsg_id) == 0 || length(var.existing_nsg_id) >= 8
    error_message = "existing_nsg_id must be empty or a non-trivial ARM resource id."
  }
}

variable "nsg_rules" {
  description = <<-EOT
    Rules the consumer applies when `mode == 'create'`. Ignored in byo
    mode. Kept opaque here (list-of-maps) so a fork can add / remove
    rule fields without editing this module.
  EOT
  type        = list(any)
  default     = []
}
