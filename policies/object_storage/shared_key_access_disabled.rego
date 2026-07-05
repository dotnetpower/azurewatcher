# METADATA
# title: Disallow shared-key access on object-storage
# description: |
#   An object-storage account MUST NOT accept shared-key auth; every
#   caller SHOULD use AAD RBAC via a managed-identity.
# custom:
#   rule_id: object-storage.shared-key-access.disabled
#   severity: high
#   category: security
package aiopspilot.object_storage.shared_key_access_disabled

import rego.v1

default deny := false

deny if {
  input.resource.type == "object-storage"
  input.resource.props.allow_shared_key_access == true
}

deny_reason := "shared_key_access_enabled" if deny
