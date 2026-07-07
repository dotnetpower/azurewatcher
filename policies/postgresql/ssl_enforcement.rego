# METADATA
# title: Require SSL enforcement on postgresql-server
# description: |
#   A postgresql-server MUST enforce SSL; unencrypted client traffic
#   to the database is a data-in-transit exposure.
# custom:
#   rule_id: postgresql-server.ssl-enforcement
#   severity: high
#   category: security
package fdai.postgresql.ssl_enforcement

import rego.v1

default deny := false

deny if {
  input.resource.type == "postgresql-server"
  input.resource.props.ssl_enforcement != "enabled"
}

deny_reason := "ssl_enforcement_disabled" if deny
