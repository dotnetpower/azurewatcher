variable "virtual_machine_id" {
  description = "ARM resource id of the Linux VM that accepts governed Python tasks."
  type        = string

  validation {
    condition     = can(regex("(?i)^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Compute/virtualMachines/[^/]+$", var.virtual_machine_id))
    error_message = "virtual_machine_id must be an Azure VM ARM resource id."
  }
}

variable "executor_principal_id" {
  description = "Object id of the executor user-assigned Managed Identity."
  type        = string
}
