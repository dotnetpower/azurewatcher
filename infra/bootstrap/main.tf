# -----------------------------------------------------------------------
# Ops (hub) layer composition. Names follow the same CAF pattern as the app
# config: <type>-<workload>-<env>-<region_short>.
# -----------------------------------------------------------------------

locals {
  suffix = "${var.workload}-${var.env}-${var.region_short}"

  # Storage account names: 3-24 lowercase alphanumeric, no hyphens.
  # tf<workload><env><region_short> + 4 random hex for global uniqueness.
  sa_prefix = lower("st${var.workload}tf${var.env}${var.region_short}")

  tags = merge({
    workload   = var.workload
    env        = var.env
    managed_by = "terraform"
    layer      = "ops-bootstrap"
  }, var.additional_tags)
}

# 4 hex chars keep the storage account name globally unique + deterministic
# once created (persisted in this layer's local state).
resource "random_id" "sa" {
  byte_length = 2
}

# -----------------------------------------------------------------------
# Ops resource group - separate from the app RG so it survives app rebuilds.
# -----------------------------------------------------------------------
resource "azurerm_resource_group" "ops" {
  name     = "rg-${var.workload}-ops-${var.region_short}"
  location = var.region
  tags     = local.tags
}

# -----------------------------------------------------------------------
# Ops (hub) VNet - runner subnet + PE subnet. Peered to the app spoke VNet
# by the app config (which owns the spoke side).
# -----------------------------------------------------------------------
resource "azurerm_virtual_network" "ops" {
  name                = "vnet-${var.workload}-ops-${var.region_short}"
  location            = var.region
  resource_group_name = azurerm_resource_group.ops.name
  address_space       = [var.ops_address_space]
  tags                = local.tags
}

resource "azurerm_subnet" "runner" {
  name                 = "snet-runner"
  resource_group_name  = azurerm_resource_group.ops.name
  virtual_network_name = azurerm_virtual_network.ops.name
  address_prefixes     = [var.runner_subnet_prefix]
}

resource "azurerm_subnet" "pe" {
  name                              = "snet-pe"
  resource_group_name               = azurerm_resource_group.ops.name
  virtual_network_name              = azurerm_virtual_network.ops.name
  address_prefixes                  = [var.pe_subnet_prefix]
  private_endpoint_network_policies = "Disabled"
}

# -----------------------------------------------------------------------
# Terraform remote-state storage. Policy-locked to private (public disabled);
# only the runner (via the blob PE below) reaches it. Versioning on so a bad
# apply is recoverable.
# -----------------------------------------------------------------------
resource "azurerm_storage_account" "state" {
  name                            = "${local.sa_prefix}${random_id.sa.hex}"
  resource_group_name             = azurerm_resource_group.ops.name
  location                        = var.region
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  min_tls_version                 = "TLS1_2"
  public_network_access_enabled   = false
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = true
  tags                            = local.tags

  blob_properties {
    versioning_enabled = true
  }
}

resource "azurerm_storage_container" "state" {
  name                  = var.state_container_name
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

# Blob private endpoint + privatelink.blob DNS, linked to the ops VNet so the
# runner resolves the state account privately.
module "state_blob_pe" {
  source                = "../modules/private-endpoint"
  name                  = "pe-st-${local.suffix}"
  location              = var.region
  resource_group_name   = azurerm_resource_group.ops.name
  subnet_id             = azurerm_subnet.pe.id
  vnet_id               = azurerm_virtual_network.ops.id
  target_resource_id    = azurerm_storage_account.state.id
  subresource_name      = "blob"
  private_dns_zone_name = "privatelink.blob.core.windows.net"
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Self-hosted deploy runner - the only host with line-of-sight to the app's
# private endpoints. System-assigned MI authenticates terraform to Azure;
# no public IP (reach via Bastion / az vm run-command / serial console).
# -----------------------------------------------------------------------
resource "azurerm_network_interface" "runner" {
  count               = var.create_runner_vm ? 1 : 0
  name                = "nic-runner-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.ops.name
  tags                = local.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.runner.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "runner" {
  count               = var.create_runner_vm ? 1 : 0
  name                = "vm-runner-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.ops.name
  size                = var.runner_vm_size
  admin_username      = var.runner_admin_username
  network_interface_ids = [
    azurerm_network_interface.runner[0].id,
  ]
  tags = local.tags

  identity {
    type = "SystemAssigned"
  }

  admin_ssh_key {
    username   = var.runner_admin_username
    public_key = var.runner_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/runner-cloud-init.yaml.tftpl", {
    runner_url   = var.github_runner_url
    runner_token = var.github_runner_token
    runner_user  = var.runner_admin_username
  }))
}

# -----------------------------------------------------------------------
# Runner permissions:
#   - Contributor on the app RG so terraform can create/replace app resources.
#   - Storage Blob Data Contributor on the state account for remote-state I/O.
# Key Vault Secrets Officer on the app KV is granted by the app config
# (the KV lives there and may not exist at bootstrap time); the app config
# consumes runner_principal_id from this layer's output.
# -----------------------------------------------------------------------
data "azurerm_resource_group" "app" {
  count = var.create_runner_vm ? 1 : 0
  name  = var.app_resource_group_name
}

resource "azurerm_role_assignment" "runner_app_contributor" {
  count                = var.create_runner_vm ? 1 : 0
  scope                = data.azurerm_resource_group.app[0].id
  role_definition_name = "Contributor"
  principal_id         = azurerm_linux_virtual_machine.runner[0].identity[0].principal_id
}

resource "azurerm_role_assignment" "runner_state_blob" {
  count                = var.create_runner_vm ? 1 : 0
  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_virtual_machine.runner[0].identity[0].principal_id
}
