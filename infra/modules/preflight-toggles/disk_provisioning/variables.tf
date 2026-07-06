variable "mode" {
  description = <<-EOT
    Provisioning mode.

    - `inline` (default): the consumer module creates a fresh
      `azurerm_managed_disk` inline with the VM.
    - `attach_existing`: the consumer module SKIPS disk creation and
      references the ids in `existing_disk_ids` instead. Use this to
      resolve the `deploy.disk_inline_creation_denied` Preflight
      blocker.
  EOT
  type        = string
  default     = "inline"

  validation {
    condition     = contains(["inline", "attach_existing"], var.mode)
    error_message = "mode must be one of: 'inline', 'attach_existing'."
  }
}

variable "existing_disk_ids" {
  description = <<-EOT
    Managed-disk resource ids to attach when `mode == 'attach_existing'`.
    Ignored when `mode == 'inline'`. Empty list is legal but the
    consumer module MUST assert non-empty for its own use case.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for id in var.existing_disk_ids : length(id) > 0
    ])
    error_message = "existing_disk_ids MUST NOT contain empty strings."
  }
}

variable "disk_size_gb" {
  description = <<-EOT
    Disk size (GiB) the consumer uses when creating an inline disk.
    Passed through unchanged when `mode == 'inline'`; ignored when
    `mode == 'attach_existing'` (the existing disk's size wins).
  EOT
  type        = number
  default     = 128

  validation {
    condition     = var.disk_size_gb > 0 && var.disk_size_gb <= 32767
    error_message = "disk_size_gb must be between 1 and 32767 (Azure max)."
  }
}
