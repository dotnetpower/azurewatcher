locals {
  cloud_init = templatefile("${path.module}/task-host.cloud-init.yaml.tftpl", {
    run_as_user       = var.run_as_user
    task_root         = var.task_root
    python_executable = var.python_executable
  })
}
