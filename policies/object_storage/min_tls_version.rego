# METADATA
# title: Require min TLS 1.2 on object-storage
# description: |
#   An object-storage account MUST require TLS 1.2 or higher; older
#   TLS versions are considered broken.
# custom:
#   rule_id: object-storage.min-tls-version
#   severity: medium
#   category: security
package aiopspilot.object_storage.min_tls_version

import rego.v1

default deny := false

required_tls := t if {
  t := input.parameters.min_tls_version
} else := "TLS1_2"

deny if {
  input.resource.type == "object-storage"
  input.resource.props.min_tls_version != required_tls
  input.resource.props.min_tls_version != "TLS1_3"
}

deny_reason := sprintf("min_tls_below:%s", [required_tls]) if deny
