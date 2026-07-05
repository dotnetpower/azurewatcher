# METADATA
# title: Require infrastructure encryption on object-storage
# description: |
#   An object-storage account MUST have infrastructure encryption
#   (double encryption at rest) enabled. The default single-layer
#   service-managed encryption is not enough for regulated data.
# custom:
#   rule_id: object-storage.encryption-at-rest.required
#   severity: high
#   category: security
package aiopspilot.object_storage.encryption_at_rest_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "object-storage"
  input.resource.props.infrastructure_encryption_enabled != true
}

deny_reason := "infrastructure_encryption_disabled" if deny
