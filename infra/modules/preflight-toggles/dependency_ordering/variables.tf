variable "mode" {
  description = <<-EOT
    Ordering mode.

    - `best_effort` (default): the consumer applies every prerequisite
      resource in parallel and lets the substrate sort dependencies.
    - `strict`: the consumer splits prerequisites into ordered stages
      (`disk` -> `nsg` -> `private_endpoint` -> `compute` by default)
      and drives them through sequential `apply` invocations. Use to
      resolve the `deploy.dependency_ordering_denied` Preflight
      blocker.
  EOT
  type        = string
  default     = "best_effort"

  validation {
    condition     = contains(["strict", "best_effort"], var.mode)
    error_message = "mode must be one of: 'strict', 'best_effort'."
  }
}

variable "custom_stages" {
  description = <<-EOT
    Override the default prerequisite stage list. When empty, the
    module ships the canonical `[disk, nsg, private_endpoint,
    compute]` sequence. Ignored when `mode == 'best_effort'`.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for s in var.custom_stages : length(s) > 0
    ])
    error_message = "custom_stages MUST NOT contain empty strings."
  }
}
