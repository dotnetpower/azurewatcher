# python_index_url capability-mode toggle.
#
# Data-only module. Emits the pip index URL + trusted-host list a
# consumer injects into build steps that install Python packages.
# Use to resolve the `deploy.pypi_egress_denied` Preflight blocker in
# environments that route package installs through an internal mirror.

locals {
  effective_index_url = var.index_url

  # Strip scheme + path so the value fits into PIP_TRUSTED_HOST format.
  # Terraform regex is RE2; no support for lookbehind, so we handle
  # http/https/file schemes explicitly.
  index_host = trimsuffix(
    regex("^(?:https?://|file://)?([^/]+)", var.index_url)[0],
    "/"
  )

  # PIP_* env vars the consumer injects into `docker build` /
  # container-app build steps. Keys are upper-snake so a fork can
  # ferry the map through a `for_each` without renaming.
  pip_env = merge(
    {
      PIP_INDEX_URL = local.effective_index_url
    },
    length(var.trusted_hosts) > 0 ? {
      PIP_TRUSTED_HOST = join(" ", var.trusted_hosts)
      } : {
      # Auto-derive from the index host when no explicit list is given
      # (defensive: prevents pip from refusing an http-only mirror).
      PIP_TRUSTED_HOST = local.index_host
    }
  )
}
