variable "run_as_user" {
  description = "Locked non-root Linux account used by Azure Managed Run Command."
  type        = string
  default     = "fdai-task"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.run_as_user))
    error_message = "run_as_user must be a valid bounded Linux account name."
  }
}

variable "task_root" {
  description = "Absolute guest directory for content-addressed task and run data."
  type        = string
  default     = "/var/lib/fdai/tasks"

  validation {
    condition     = startswith(var.task_root, "/") && !strcontains(var.task_root, "..")
    error_message = "task_root must be an absolute traversal-free path."
  }
}

variable "python_executable" {
  description = "Preinstalled Python executable in the approved VM image."
  type        = string
  default     = "/usr/bin/python3"

  validation {
    condition     = startswith(var.python_executable, "/") && !strcontains(var.python_executable, "..")
    error_message = "python_executable must be an absolute traversal-free path."
  }
}

variable "advertised_capabilities" {
  description = "Additional host capabilities advertised to inventory (GPU is also cross-checked from VM SKU)."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for capability in var.advertised_capabilities :
      contains(["gpu", "network", "filesystem_read", "filesystem_write", "process"], capability)
    ])
    error_message = "advertised_capabilities contains an unsupported capability."
  }
}
