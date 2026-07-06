output "effective_mode" {
  description = "The mode the toggle resolved to ('create' or 'byo')."
  value       = var.mode
}

output "should_create_nsg" {
  description = <<-EOT
    Boolean the consumer wraps `count` / `for_each` around when deciding
    whether to emit an `azurerm_network_security_group` resource.
  EOT
  value       = local.should_create_nsg
}

output "byo_nsg_id" {
  description = <<-EOT
    NSG id to reference when `mode == 'byo'`; empty string when
    `mode == 'create'` so a consumer coalesce (`coalesce(module.nsg.byo_nsg_id,
    azurerm_network_security_group.created[0].id)`) picks the right one.
  EOT
  value       = local.byo_nsg_id
}

output "nsg_rules" {
  description = <<-EOT
    Rules the consumer applies when it creates the NSG. Empty list is
    legal (consumer decides whether an empty NSG is acceptable).
  EOT
  value       = var.nsg_rules
}
