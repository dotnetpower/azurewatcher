variable "mode" {
  description = <<-EOT
    The `disk_provisioning` toggle value. `inline` creates a fresh managed
    disk; `attach_existing` attaches the ids in `existing_disk_ids` and creates
    nothing. The Deployment Preflight active-reassembly loop sets this to
    `attach_existing` to resolve a `deploy.disk_inline_creation_denied` blocker
    (see docs/roadmap/preflight-active-reassembly.md).
  EOT
  type        = string
  default     = "inline"
}

variable "existing_disk_ids" {
  description = "Pre-provisioned managed-disk ids to attach when mode == 'attach_existing'."
  type        = list(string)
  default     = []
}

variable "disk_size_gb" {
  description = "Size (GiB) of the inline disk created when mode == 'inline'."
  type        = number
  default     = 128
}

variable "name_prefix" {
  description = "Name prefix for the example inline disk (CAF-style, decided in terraform)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group the inline disk lands in."
  type        = string
}

variable "location" {
  description = "Azure region for the inline disk."
  type        = string
}
