# ADLS Gen2 Document Storage

This module provisions the private document data plane for FDAI. It creates a StorageV2 account
with hierarchical namespace (HNS), disables Shared Key access, and separates governed source data
from derived artifacts by filesystem.

## Resources

| Resource | Purpose |
|----------|---------|
| StorageV2 account | HNS-backed source and artifact storage |
| `documents` filesystem | `quarantine/` and immutable `governed/` source paths |
| `derived` filesystem | Canonical envelopes and extraction artifacts |
| Management policy | Quarantine expiry and derived-data cool tiering |

The root module owns Managed Identity role assignments and the `blob` plus `dfs` private
endpoints. Blob versioning stays disabled because Azure doesn't support it on HNS accounts. FDAI
creates a new opaque path for every immutable document version instead of overwriting source data.
