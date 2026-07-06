variable "index_url" {
  description = <<-EOT
    pip index URL. Defaults to the public PyPI mirror. Override with
    an internal artifact-feed URL to resolve the
    `deploy.pypi_egress_denied` Preflight blocker. Supports http, https,
    and file:// (for offline caches mounted into the builder).
  EOT
  type        = string
  default     = "https://pypi.org/simple/"

  validation {
    condition     = can(regex("^(?:https?|file)://[^\\s]+$", var.index_url))
    error_message = "index_url must be an http(s):// or file:// URL with no whitespace."
  }
}

variable "trusted_hosts" {
  description = <<-EOT
    Additional hosts pip should trust (bypasses TLS-only enforcement
    when using an http mirror). Empty list -> the toggle auto-derives
    the host from `index_url` (defensive default).
  EOT
  type        = list(string)
  default     = []
}
