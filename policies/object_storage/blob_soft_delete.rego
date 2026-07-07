# METADATA
# title: Require blob soft-delete on object-storage
# description: |
#   An object-storage account MUST have blob soft-delete enabled so
#   an accidental delete is recoverable within the retention window.
# custom:
#   rule_id: object-storage.soft-delete-blob
#   severity: high
#   category: reliability
package fdai.object_storage.blob_soft_delete

import rego.v1

default deny := false

deny if {
  input.resource.type == "object-storage"
  input.resource.props.blob_soft_delete_enabled != true
}

deny_reason := "blob_soft_delete_disabled" if deny
