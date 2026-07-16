output "cloud_init" {
  description = "Cloud-init document for azurerm_linux_virtual_machine.custom_data."
  value       = local.cloud_init
}

output "cloud_init_base64" {
  description = "Base64 cloud-init document ready for Azure Linux VM custom_data."
  value       = base64encode(local.cloud_init)
}

output "inventory_tags" {
  description = "Tags that explicitly opt the VM into FDAI task targeting."
  value = {
    "fdai:vm-task-ready" = "true"
    "fdai:capabilities"  = join(",", sort(tolist(var.advertised_capabilities)))
  }
}
