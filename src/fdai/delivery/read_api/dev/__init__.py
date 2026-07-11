"""Development-only helpers for the read-only ASGI (G-5).

Physically separated from the production route code so a packaging /
container build can drop the whole subpackage from the production image.
Nothing here is imported at production runtime.

- :mod:`.local` - the ``FDAI_READ_API_LOCAL_ENTRA`` seed-data harness that
  a developer uses to preview the console without a full backend. Reads
  fixture files only; never touches a real state store.
"""
