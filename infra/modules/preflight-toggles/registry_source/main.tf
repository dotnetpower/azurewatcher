# registry_source capability-mode toggle.
#
# Data-only module. Emits the base registry hostname + image prefix a
# consumer prepends when it references a container image. Use to
# resolve the `deploy.docker_io_egress_denied` Preflight blocker in
# environments that block egress to docker.io.

locals {
  # 'docker_io'   -> images pulled as `library/<name>:<tag>` from docker.io
  # 'acr_mirror'  -> images pulled from the fork's ACR mirror instead.
  base_registry = var.mode == "docker_io" ? "docker.io" : var.acr_mirror_login_server

  # The image reference the consumer builds:
  #   "<base_registry>/<image_prefix><image_name>:<tag>"
  # docker_io hub images use the `library/` prefix; ACR mirror images
  # sit at the repo root by convention (a fork MAY override
  # `image_prefix` to point at a nested project).
  image_prefix = coalesce(var.image_prefix_override, var.mode == "docker_io" ? "library/" : "")
}
