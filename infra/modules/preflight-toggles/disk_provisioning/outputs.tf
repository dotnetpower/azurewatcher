output "effective_mode" {
  description = "The mode the toggle resolved to ('inline' or 'attach_existing')."
  value       = var.mode
}

output "should_create_disk" {
  description = <<-EOT
    Boolean the consumer wraps `count` / `for_each` around when deciding
    whether to emit an inline `azurerm_managed_disk` resource.
  EOT
  value       = local.should_create_disk
}

output "disk_source_ids" {
  description = <<-EOT
    Ids to attach when `mode == 'attach_existing'`; empty list when
    `mode == 'inline'` so a consumer `for_each` is naturally a no-op.
  EOT
  value       = local.disk_source_ids
}

output "inline_disk_size_gb" {
  description = <<-EOT
    Size (GiB) the consumer passes to the inline `azurerm_managed_disk`
    when it creates one. Emitted regardless of mode so a caller that
    ignores it stays consistent across mode changes.
  EOT
  value       = var.disk_size_gb
}
