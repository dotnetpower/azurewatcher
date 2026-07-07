# METADATA
# title: Require encryption at rest on postgresql-server
# description: |
#   A postgresql-server MUST have encryption at rest enabled; the
#   default provider setting is usually service-managed and enough,
#   but a rule fires when the property comes back false.
# custom:
#   rule_id: postgresql-server.encryption-at-rest
#   severity: high
#   category: security
package fdai.postgresql.encryption_at_rest

import rego.v1

default deny := false

deny if {
  input.resource.type == "postgresql-server"
  input.resource.props.encryption_at_rest_enabled != true
}

deny_reason := "encryption_at_rest_disabled" if deny
