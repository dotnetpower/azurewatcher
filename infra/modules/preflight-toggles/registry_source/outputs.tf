output "effective_mode" {
  description = "The mode the toggle resolved to ('docker_io' or 'acr_mirror')."
  value       = var.mode
}

output "base_registry" {
  description = <<-EOT
    Base registry hostname the consumer prepends when building an
    image reference (`docker.io` or the ACR login server).
  EOT
  value       = local.base_registry
}

output "image_prefix" {
  description = <<-EOT
    Prefix segment placed between the base registry and the image
    name (`library/` for docker.io hub images, `""` for ACR mirror
    root; overridable via `image_prefix_override`).
  EOT
  value       = local.image_prefix
}

output "image_reference_template" {
  description = <<-EOT
    Convenience: a Go template string a consumer can `format` with
    `image_name` + `tag`. Example: format(module.reg.image_reference_template,
    "python", "3.13-slim").
  EOT
  value       = "${local.base_registry}/${local.image_prefix}%s:%s"
}
