resource "azurerm_resource_group" "primary" {
  name     = var.name
  location = var.location
  tags     = var.tags
}

