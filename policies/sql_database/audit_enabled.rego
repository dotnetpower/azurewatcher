# METADATA
# title: Require auditing on sql-database
# description: |
#   A sql-database MUST have auditing enabled routing to a log-workspace
#   so admin actions are recoverable for forensics.
# custom:
#   rule_id: sql-database.audit-enabled
#   severity: high
#   category: security
package aiopspilot.sql_database.audit_enabled

import rego.v1

default deny := false

deny if {
  input.resource.type == "sql-database"
  input.resource.props.audit_enabled != true
}

deny_reason := "audit_disabled" if deny
