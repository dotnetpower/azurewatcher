locals {
  role_name = "FDAI VM Task Runner ${substr(sha256(lower(var.virtual_machine_id)), 0, 8)}"
}

resource "azurerm_role_definition" "vm_task_runner" {
  name        = local.role_name
  scope       = var.virtual_machine_id
  description = "Run and cancel FDAI governed task commands on one VM."

  permissions {
    actions = [
      "Microsoft.Compute/virtualMachines/read",
      "Microsoft.Compute/virtualMachines/runCommands/read",
      "Microsoft.Compute/virtualMachines/runCommands/write",
      "Microsoft.Compute/virtualMachines/runCommands/delete",
    ]
    not_actions = []
  }

  assignable_scopes = [var.virtual_machine_id]
}

resource "azurerm_role_assignment" "vm_task_runner" {
  scope              = var.virtual_machine_id
  role_definition_id = azurerm_role_definition.vm_task_runner.role_definition_resource_id
  principal_id       = var.executor_principal_id
  principal_type     = "ServicePrincipal"
}
