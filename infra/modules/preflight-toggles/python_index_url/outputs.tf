output "effective_index_url" {
  description = "Resolved pip index URL - identical to `var.index_url` (kept as an output so a caller can log via the toggle name only)."
  value       = local.effective_index_url
}

output "index_host" {
  description = <<-EOT
    Host segment of the index URL (scheme + path stripped). Useful
    when a caller needs to add a per-host firewall rule or a
    `PIP_TRUSTED_HOST` value.
  EOT
  value       = local.index_host
}

output "pip_env" {
  description = <<-EOT
    Map of `PIP_*` environment variables a consumer injects into
    build steps. Includes `PIP_INDEX_URL` and `PIP_TRUSTED_HOST`
    (auto-derived from the host when `trusted_hosts` is empty).
  EOT
  value       = local.pip_env
}
