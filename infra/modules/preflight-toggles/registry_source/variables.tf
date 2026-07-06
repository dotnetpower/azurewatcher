variable "mode" {
  description = <<-EOT
    Source-registry mode.

    - `docker_io` (default): pull from `docker.io/library/*`. Use when
      egress to docker.io is unrestricted.
    - `acr_mirror`: pull from the fork's internal ACR mirror
      (`acr_mirror_login_server`). Use to resolve the
      `deploy.docker_io_egress_denied` Preflight blocker.
  EOT
  type        = string
  default     = "docker_io"

  validation {
    condition     = contains(["docker_io", "acr_mirror"], var.mode)
    error_message = "mode must be one of: 'docker_io', 'acr_mirror'."
  }
}

variable "acr_mirror_login_server" {
  description = <<-EOT
    ACR login server FQDN (e.g. `myacr.azurecr.io`) used when
    `mode == 'acr_mirror'`. Ignored otherwise. MUST be non-empty in
    acr_mirror mode; consumer modules assert.
  EOT
  type        = string
  default     = ""

  validation {
    condition = (
      length(var.acr_mirror_login_server) == 0
      || can(regex("^[a-z0-9-]+\\.azurecr\\.io$", var.acr_mirror_login_server))
    )
    error_message = "acr_mirror_login_server must be empty or a valid `<name>.azurecr.io` FQDN."
  }
}

variable "image_prefix_override" {
  description = <<-EOT
    Optional override for the image prefix. When empty, the toggle
    picks a sensible default per mode (`library/` for docker.io hub,
    empty string for ACR).
  EOT
  type        = string
  default     = ""
}
