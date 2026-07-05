# METADATA
# title: Require blob versioning on object-storage
# description: |
#   An object-storage account MUST have blob versioning enabled so
#   each overwrite produces a recoverable prior version.
# custom:
#   rule_id: object-storage.versioning-enabled
#   severity: medium
#   category: reliability
package aiopspilot.object_storage.blob_versioning

import rego.v1

default deny := false

deny if {
  input.resource.type == "object-storage"
  input.resource.props.blob_versioning_enabled != true
}

deny_reason := "blob_versioning_disabled" if deny
