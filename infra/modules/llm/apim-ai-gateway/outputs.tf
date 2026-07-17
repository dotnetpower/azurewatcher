output "gateway_endpoint" {
  description = "OpenAI-compatible endpoint resolved by the FDAI composition root."
  value       = "${trimsuffix(var.gateway_url, "/")}/${var.api_path}"
}

output "api_name" {
  description = "APIM API name used as the endpoint binding reference."
  value       = azurerm_api_management_api.model.name
}

output "backend_names" {
  description = "Backend ids emitted by the mandatory FDAI route-evidence headers."
  value = {
    ptu      = azurerm_api_management_backend.ptu.name
    standard = azurerm_api_management_backend.standard.name
  }
}
